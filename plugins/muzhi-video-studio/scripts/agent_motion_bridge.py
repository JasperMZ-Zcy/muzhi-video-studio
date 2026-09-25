#!/usr/bin/env python3
"""Explicit, local-only handoff to a separately installed Agent Motion workspace.

This bridge never executes upstream code, uploads media, renders, or changes a
project's style, voice, generation provider, or existing production gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # status/check must not create plugin cache files.
import motion_plan
import style_registry


COMMIT = "a379a68040b9cb397be3ca4f199201686b673b40"
VERSION = "1.0.0"
PINNED_BLOBS = {
    "package.json": "802846b0bc8c15e15f3192c1311b08d486eef850",
    "LICENSE": "91b8dc7be501009c1141249e9c674865dfb91c87",
    "NOTICE": "d44c3eee5065685038b1558f07fbb735e7fb5627",
    ".agents/skills/motion-craft/SKILL.md": "d2655408efcaeb0384564f057928167cf5b36ec8",
    ".agents/skills/srt-reference-to-three/SKILL.md": "476dae379b16ba666380cf5e513245dd1c8d0e4b",
}
HANDOFF = Path("artifacts/agent-motion-handoff.json")
STYLE_LOCK = Path("artifacts/video-studio-style.json")
ALLOWED_ROUTES = {"native_mg", "official_evidence", "sourced_chart", "hybrid"}
SRT_TIMECODE = re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")
REFERENCE_INDEX = "reference-library/analysis/INDEX.md"
REFERENCE_CATALOG = "reference-library/analysis/catalog.json"
CASE_COUNT = 43
REFERENCE_TREE_DIGEST = "73a827ec0ed1aae6e8455183d1c34fecb628c6d9775e11836d0c53f26aac1cc6"


class BridgeError(RuntimeError):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git_blob(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def reference_snapshot(upstream: Path) -> tuple[int, str]:
    library = upstream / "reference-library" / "analysis"
    if library.is_symlink() or not library.is_dir():
        raise BridgeError("reference library: missing or linked analysis directory")
    paths = sorted((path for path in library.rglob("*") if path.is_file()),
                   key=lambda path: path.relative_to(library).as_posix())
    if not paths or any(path.is_symlink() or not path.resolve().is_relative_to(library.resolve()) for path in paths):
        raise BridgeError("reference library: missing files or escaping links")
    aggregate = hashlib.sha256()
    for path in paths:
        entry = f"{path.relative_to(library).as_posix()}\0{git_blob(path)}\n"
        aggregate.update(entry.encode("utf-8"))
    return len(paths), aggregate.hexdigest()


def milliseconds(timecode: str) -> int:
    hours, minutes, rest = timecode.replace(",", ".").split(":")
    seconds, millis = rest.split(".")
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise BridgeError("SRT: minutes and seconds must be below 60")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def srt_cues(text: str) -> list[tuple[str, str]]:
    cues: list[tuple[str, str]] = []
    block: list[str] = []
    blocks: list[list[str]] = []
    for line in text.splitlines():
        if line.strip():
            block.append(line.strip())
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    previous_start = -1
    for block in blocks:
        if len(block) < 3 or not re.fullmatch(r"\d+", block[0]):
            raise BridgeError("SRT: cue needs a numeric index, timecode line, and subtitle text")
        match = SRT_TIMECODE.fullmatch(block[1])
        if match is None:
            raise BridgeError("SRT: invalid cue timecode line")
        start, end = match.groups()
        start_ms, end_ms = milliseconds(start), milliseconds(end)
        if start_ms >= end_ms:
            raise BridgeError("SRT: cue end must follow its start")
        if start_ms < previous_start:
            raise BridgeError("SRT: cues must follow time order")
        previous_start = start_ms
        cues.append((start, end))
    if not cues:
        raise BridgeError("SRT: no valid timecode line")
    return cues


def local_file(project: Path, name: str, label: str) -> Path:
    if not isinstance(name, str) or not name.strip():
        raise BridgeError(f"{label}: project-relative path is required")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise BridgeError(f"{label}: path must stay inside the project")
    path = (project / relative).resolve()
    if not path.is_relative_to(project) or not path.is_file():
        raise BridgeError(f"{label}: file missing or path escapes the project")
    return path


def checked_hash(project: Path, name: str, expected: str, label: str) -> dict:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise BridgeError(f"{label}: expected SHA-256 is required")
    path = local_file(project, name, label)
    actual = digest(path)
    if actual != expected:
        raise BridgeError(f"{label}: SHA-256 drift")
    return {"path": str(path.relative_to(project)), "sha256": actual}


def upstream_status(upstream: Path) -> dict:
    if not upstream.is_dir():
        raise BridgeError("upstream: existing directory is required")
    checked = {}
    for relative, expected in PINNED_BLOBS.items():
        path = (upstream / relative).resolve()
        if not path.is_relative_to(upstream) or not path.is_file():
            raise BridgeError(f"upstream: missing or escaping {relative}")
        actual = git_blob(path)
        if actual != expected:
            raise BridgeError(f"upstream: pinned Git blob drift in {relative}")
        checked[relative] = actual
    package = json.loads((upstream / "package.json").read_text(encoding="utf-8"))
    if package.get("name") != "agent-motion" or package.get("version") != VERSION:
        raise BridgeError("upstream: package name/version mismatch")
    library_count, library_digest = reference_snapshot(upstream)
    if library_digest != REFERENCE_TREE_DIGEST:
        raise BridgeError("upstream: pinned reference-library snapshot drift")
    runtime = {
        "node_modules": (upstream / "node_modules").is_dir(),
        "python_venv": (upstream / ".venv" / "Scripts" / "python.exe").is_file()
        if os.name == "nt" else (upstream / ".venv" / "bin" / "python").is_file(),
        "runtime_dir": (upstream / ".runtime").is_dir(),
    }
    return {"path": str(upstream), "commit": COMMIT, "version": VERSION,
            "pinned_files_checked": checked, "runtime_presence_only": runtime,
            "pinned_reference_files": library_count, "pinned_reference_digest": library_digest,
            "runtime_note": "Presence is not doctor, render, or visual acceptance."}


def references_for_plan(upstream: Path, plan: dict, segment: dict, cues: list[tuple[str, str]]) -> tuple[dict, list[dict]]:
    if plan.get("reference_index_source") != REFERENCE_INDEX:
        raise BridgeError("reference index: full INDEX.md path is required")
    index_path = (upstream / REFERENCE_INDEX).resolve()
    catalog_path = (upstream / REFERENCE_CATALOG).resolve()
    if (not index_path.is_relative_to(upstream) or not catalog_path.is_relative_to(upstream)
            or not index_path.is_file() or not catalog_path.is_file()):
        raise BridgeError("reference library: index or catalog missing/escaping upstream")
    index_hash = digest(index_path)
    if plan.get("reference_index_sha256") != index_hash:
        raise BridgeError("reference index: SHA-256 drift or missing hash")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    cases = catalog.get("cases")
    if catalog.get("case_count") != CASE_COUNT or not isinstance(cases, list) or len(cases) != CASE_COUNT:
        raise BridgeError("reference catalog: incomplete case index")
    lookup = {}
    index_text = index_path.read_text(encoding="utf-8")
    for case in cases:
        if not isinstance(case, dict) or not re.fullmatch(r"V\d{2}", str(case.get("case_id", ""))):
            raise BridgeError("reference catalog: invalid case ID")
        ident = case["case_id"]
        if ident in lookup or f"| {ident} |" not in index_text:
            raise BridgeError("reference catalog: duplicate case or case absent from full index")
        lookup[ident] = case
    chosen = segment.get("reference_cases")
    if not isinstance(chosen, list) or not chosen:
        raise BridgeError(f"segment {segment['id']}: selected Agent Motion route needs reference_cases")
    result = []
    seen = set()
    for choice in chosen:
        if not isinstance(choice, dict):
            raise BridgeError(f"segment {segment['id']}: malformed reference case")
        ident = choice.get("case_id")
        if ident not in lookup or ident in seen:
            raise BridgeError(f"segment {segment['id']}: unknown or duplicate reference case")
        seen.add(ident)
        expected_path = f"reference-library/analysis/{lookup[ident]['report']}"
        if choice.get("source_path") != expected_path:
            raise BridgeError(f"segment {segment['id']}: reference case path mismatch")
        page = (upstream / expected_path).resolve()
        if not page.is_relative_to(upstream) or not page.is_file() or choice.get("source_sha256") != digest(page):
            raise BridgeError(f"segment {segment['id']}: reference case page missing or SHA-256 drift")
        for field in ("mechanism", "srt_timecode", "style_adaptation", "visible_action"):
            if not isinstance(choice.get(field), str) or not choice[field].strip():
                raise BridgeError(f"segment {segment['id']}: reference case needs {field}")
        timecode = SRT_TIMECODE.fullmatch(choice["srt_timecode"].strip())
        if timecode is None:
            raise BridgeError(f"segment {segment['id']}: reference case SRT timecode is malformed")
        first, last = timecode.groups()
        starts = [i for i, cue in enumerate(cues) if cue[0] == first]
        ends = [i for i, cue in enumerate(cues) if cue[1] == last]
        if not starts or not ends or not any(a <= b for a in starts for b in ends) or milliseconds(first) >= milliseconds(last):
            raise BridgeError(f"segment {segment['id']}: reference case SRT interval outside bound cues")
        sample = choice.get("sample_timecode_evidence")
        if not isinstance(sample, dict) or sample.get("status") != "pending":
            raise BridgeError(f"segment {segment['id']}: prepare accepts only pending voiced-sample evidence")
        result.append({field: choice[field] for field in (
            "case_id", "source_path", "source_sha256", "mechanism", "srt_timecode",
            "style_adaptation", "visible_action")})
        result[-1]["sample_timecode_evidence"] = {"status": "pending"}
    return {"path": REFERENCE_INDEX, "sha256": index_hash,
            "catalog_path": REFERENCE_CATALOG, "catalog_sha256": digest(catalog_path),
            "indexed_cases": len(lookup)}, result


def project_status(project: Path, upstream: Path, plan_name: str, receipt_name: str,
                   srt_name: str, srt_hash: str, voice_name: str, voice_hash: str) -> dict:
    source = upstream_status(upstream)
    source.pop("runtime_presence_only")
    source.pop("runtime_note")
    if not project.is_dir():
        raise BridgeError("project: existing directory is required")
    plan_record = checked_hash(project, plan_name, digest(local_file(project, plan_name, "plan")), "plan")
    plan = json.loads((project / plan_record["path"]).read_text(encoding="utf-8"))
    audit = motion_plan.validate(plan, project, "storyboard")
    if not audit["passed"]:
        raise BridgeError("motion plan storyboard audit failed: " + "; ".join(audit["errors"]))
    srt = checked_hash(project, srt_name, srt_hash, "SRT")
    srt_text = (project / srt["path"]).read_text(encoding="utf-8-sig")
    cues = srt_cues(srt_text)
    selected = []
    reference_index = None
    for segment in plan["segments"]:
        backend = segment.get("motion_backend")
        if backend is None:
            continue
        if backend != "agent_motion":
            raise BridgeError(f"segment {segment.get('id')}: unknown motion_backend")
        route = segment["visual_route"]
        if route not in ALLOWED_ROUTES:
            raise BridgeError(f"segment {segment['id']}: Agent Motion cannot replace {route}")
        item = {"id": segment["id"], "visual_route": route,
                "backend": "agent_motion", "visual_action": segment["visual_action"]}
        reference_index, item["reference_cases"] = references_for_plan(upstream, plan, segment, cues)
        if route == "hybrid":
            scope = segment.get("agent_motion_scope")
            if not isinstance(scope, str) or not scope.strip():
                raise BridgeError(f"segment {segment['id']}: hybrid needs agent_motion_scope")
            item["agent_motion_scope"] = scope.strip()
            item["responsibilities"] = segment["responsibilities"]
            item["uses_image_to_video"] = segment["uses_image_to_video"]
            if segment["uses_image_to_video"]:
                other = segment.get("image_to_video_scope")
                if not isinstance(other, str) or not other.strip() or other.strip() == scope.strip():
                    raise BridgeError(f"segment {segment['id']}: distinct image_to_video_scope is required")
                item["excluded_image_to_video_scope"] = other.strip()
                item["existing_generation_action_preserved"] = segment["generation_action"]
        selected.append(item)
    if not selected:
        raise BridgeError("plan: no segment explicitly selects motion_backend=agent_motion")

    style_path = local_file(project, STYLE_LOCK.as_posix(), "style lock")
    style = style_registry.read_lock(style_path)
    _, styles = style_registry.catalog()
    style_registry.validate_choice(style["style"], style.get("mode"), styles)
    style_record = {"path": STYLE_LOCK.as_posix(), "sha256": digest(style_path),
                    "style": style["style"], "mode": style["mode"]}
    design = checked_hash(project, "design.md", plan["design_sha256"], "design")
    script = checked_hash(project, plan["source_script"], plan["source_sha256"], "source script")
    voice = checked_hash(project, voice_name, voice_hash, "original voice")
    if Path(voice["path"]).suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".aac"}:
        raise BridgeError("original voice: unsupported file extension")
    if (project / voice["path"]).stat().st_size == 0:
        raise BridgeError("original voice: empty file")

    receipt_path = local_file(project, receipt_name, "authorization receipt")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    required = (receipt.get("attestation") == "user_attested"
                and receipt.get("scope") == "local_use_only"
                and receipt.get("upstream_commit") == COMMIT
                and receipt.get("project_root") == str(project)
                and receipt.get("selected_backend") == "agent_motion"
                and receipt.get("no_public_redistribution") is True
                and isinstance(receipt.get("user_quote"), str) and receipt["user_quote"].strip()
                and isinstance(receipt.get("attested_at"), str) and receipt["attested_at"].strip())
    if not required:
        raise BridgeError("authorization receipt: local user-attested scope/project/version incomplete")
    return {"schema_version": 1, "state": "prepared_for_manual_production",
            "project": str(project), "upstream": source, "authorization": {
                "path": str(receipt_path.relative_to(project)), "sha256": digest(receipt_path),
                "attestation": "user_attested", "scope": "local_use_only",
                "note": "User-reported permission; written commercial/re-distribution grant not independently verified."},
            "style_lock": style_record, "plan": plan_record, "reference_index": reference_index,
            "required_upstream_skills": [
                {"path": path, "git_blob_sha1": PINNED_BLOBS[path]} for path in (
                    ".agents/skills/motion-craft/SKILL.md",
                    ".agents/skills/srt-reference-to-three/SKILL.md")],
            "inputs": {"source_script": script, "srt": srt, "original_voice": voice, "design": design},
            "agent_motion_segments": selected, "excluded_segments": [s["id"] for s in plan["segments"] if s.get("motion_backend") is None],
            "semantic_requirement": "Read both pinned upstream Skills; understand the complete bound SRT and voice timing before scene code; keep original voice, style, source evidence, and existing image-to-video provider.",
            "boundary": "Handoff only; reference cases are historical analysis, sample evidence is pending; no upstream execution, upload, rendering, provider switch, approval, or publication."}


def validated_project(raw: str) -> Path:
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise BridgeError("project must be a directory")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "status", "prepare"):
        part = sub.add_parser(command)
        part.add_argument("--upstream", required=True, help="separate local Agent Motion source directory")
        if command != "check":
            part.add_argument("--project", required=True)
        if command == "prepare":
            for flag in ("plan", "receipt", "srt", "srt-sha256", "voice", "voice-sha256"):
                part.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    try:
        upstream = Path(args.upstream).expanduser().resolve(strict=True)
        if args.command == "check":
            result = {"state": "source_checked", "upstream": upstream_status(upstream)}
        else:
            project = validated_project(args.project)
            handoff_path = project / HANDOFF
            if args.command == "status":
                if not handoff_path.is_file() or handoff_path.is_symlink():
                    result = {"state": "not_prepared", "project": str(project), "upstream": upstream_status(upstream)}
                else:
                    old = json.loads(handoff_path.read_text(encoding="utf-8"))
                    if old.get("schema_version") != 1 or old.get("project") != str(project) or old.get("upstream", {}).get("path") != str(upstream):
                        raise BridgeError("handoff: project/upstream binding mismatch")
                    inputs = old["inputs"]
                    current = project_status(project, upstream, old["plan"]["path"], old["authorization"]["path"],
                                             inputs["srt"]["path"], inputs["srt"]["sha256"],
                                             inputs["original_voice"]["path"], inputs["original_voice"]["sha256"])
                    old.pop("prepared_at", None)
                    if current != old:
                        raise BridgeError("handoff: plan, authorization, style, inputs, or source drift")
                    result = {"state": "prepared_readback", "handoff": str(handoff_path),
                              "segments": len(current["agent_motion_segments"]), "boundary": current["boundary"]}
            else:
                current = project_status(project, upstream, args.plan, args.receipt,
                                         args.srt, args.srt_sha256, args.voice, args.voice_sha256)
                artifacts = project / "artifacts"
                if (artifacts.is_symlink() or getattr(artifacts, "is_junction", lambda: False)()
                        or (artifacts.exists() and artifacts.resolve() != artifacts.absolute())
                        or (artifacts.exists() and not artifacts.is_dir())):
                    raise BridgeError("artifacts: must be a local directory, not a link")
                if handoff_path.exists() or handoff_path.is_symlink():
                    raise BridgeError("handoff already exists; inspect with status, do not overwrite")
                artifacts.mkdir(exist_ok=True)
                current["prepared_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                with handoff_path.open("x", encoding="utf-8") as stream:
                    json.dump(current, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                result = {"state": current["state"], "handoff": str(handoff_path),
                          "segments": len(current["agent_motion_segments"]), "boundary": current["boundary"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BridgeError, OSError, ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError,
            style_registry.StyleError) as error:
        print(json.dumps({"state": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
