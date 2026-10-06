"""Read-only project identity and semantic-version policy.

Documents and a caller's ``existing_reviewed`` assertion are not legacy proof.
The compatible branch needs plugin work already recorded, or a bound historical
Gate 1 input bundle. No timestamps, cache versions, or account identity are used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _object(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _bound_file(root: Path, relative: Any, digest: Any) -> bool:
    if not isinstance(relative, str) or not relative or not isinstance(digest, str) or len(digest) != 64:
        return False
    if any(char not in "0123456789abcdefABCDEF" for char in digest):
        return False
    path = Path(relative)
    if path.is_absolute() or any(part in (".", "..") for part in path.parts):
        return False
    target = root / path
    if any(part.is_symlink() for part in (root, *[root.joinpath(*path.parts[:i]) for i in range(1, len(path.parts) + 1)])):
        return False
    if not target.is_file() or not target.resolve().is_relative_to(root.resolve()):
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == digest.lower()


def _recorded_plugin_work(root: Path) -> bool:
    state = _object(root / "artifacts/editorial-plugin-state.json")
    if not state or state.get("schema") != 1 or not isinstance(state.get("version"), str):
        return False
    if state.get("director_review_required_version") is not None:
        return False
    locks = state.get("locks")
    if isinstance(locks, dict):
        for record in locks.values():
            if isinstance(record, dict) and _bound_file(root, record.get("file"), record.get("sha256")):
                return True
    history = state.get("stage_history")
    progressed = (isinstance(state.get("revision"), int) and state["revision"] > 0 and
                  state.get("stage") not in (None, "planning") and isinstance(history, list) and
                  any(isinstance(item, dict) and item.get("stage") == state["stage"] for item in history[1:]))
    if not progressed:
        return False
    ledger = _object(root / "artifacts/generation-ledger.json")
    if ledger and isinstance(ledger.get("entries"), list):
        for entry in ledger["entries"]:
            inputs = entry.get("inputs") if isinstance(entry, dict) else None
            if isinstance(inputs, list) and any(isinstance(item, dict) and
                _bound_file(root, item.get("path"), item.get("sha256")) for item in inputs):
                return True
    return False


def _historical_input_bundle(root: Path) -> bool:
    """Recognize F-style locked work from checked local copies, without external reads."""
    gate = _object(root / "inputs/gate1-lock.json")
    plan = _object(root / "motion-plan.json") or _object(root / "artifacts/motion-plan.json")
    if not gate or not plan or gate.get("schemaVersion") != "1.0" or plan.get("semantic_contract_version") != 1:
        return False
    if not isinstance(gate.get("approval"), dict) or not gate["approval"].get("quote"):
        return False
    for path_key, hash_key in (("source_script", "source_sha256"), ("srt_source", "srt_sha256"),
                               ("audio_source", "audio_sha256"), ("design_source", "design_sha256")):
        if not _bound_file(root, plan.get(path_key), plan.get(hash_key)):
            return False
    approved = gate.get("approvedCopy")
    captions = gate.get("captions")
    clock = gate.get("masterClock")
    return (isinstance(approved, dict) and isinstance(captions, dict) and isinstance(clock, dict) and
            plan.get("source_sha256", "").lower() == str(approved.get("sha256", "")).lower() and
            plan.get("srt_sha256", "").lower() == str(captions.get("sha256", "")).lower() and
            _historical_audio_binding(root, plan, clock))


def _historical_audio_binding(root: Path, plan: dict[str, Any], clock: dict[str, Any]) -> bool:
    locked_audio = clock.get("audioSha256")
    if not isinstance(locked_audio, str) or len(locked_audio) != 64:
        return False
    if any(char not in "0123456789abcdefABCDEF" for char in locked_audio):
        return False
    if plan.get("audio_sha256", "").lower() == locked_audio.lower():
        return True
    # Historical projects may use a frozen WAV derivative of a locked M4A.
    # Bind that derivative to its existing director contract and exact plan;
    # this recognizes recorded work, not proof of decoded audio equivalence.
    director = _object(root / "artifacts/director-storyboard.json")
    if not director or director.get("director_review_contract_version") != 1:
        return False
    if (director.get("voice_source") != plan.get("audio_source") or
            str(director.get("voice_sha256", "")).lower() != plan.get("audio_sha256", "").lower()):
        return False
    if any(director.get(key) != plan.get(key) for key in
           ("source_script", "source_sha256", "srt_source", "srt_sha256", "design_source", "design_sha256")):
        return False
    return _bound_file(root, director.get("motion_plan_source"), director.get("motion_plan_sha256"))


def classify_project(project: str | Path) -> dict[str, Any]:
    """Return kind, minimum_semantic_version, and reason; never modify a project."""
    root = Path(project).resolve()
    if not root.is_dir():
        return {"kind": "unknown", "minimum_semantic_version": 2, "reason": "project directory missing"}
    lock = _object(root / "artifacts/video-studio-style.json")
    state = _object(root / "artifacts/editorial-plugin-state.json")
    if lock and lock.get("directorReviewRequiredVersion") == 2:
        return {"kind": "new", "minimum_semantic_version": 2, "reason": "v2 new style lock"}
    if (lock and lock.get("projectKind") == "new" and
            not _historical_input_bundle(root)):
        return {"kind": "new", "minimum_semantic_version": 2, "reason": "new style lock"}
    if state and state.get("director_review_required_version") is not None:
        return {"kind": "new", "minimum_semantic_version": 2, "reason": "new plugin state"}
    if _recorded_plugin_work(root):
        return {"kind": "legacy", "minimum_semantic_version": 1, "reason": "verified pre-upgrade plugin work"}
    if _historical_input_bundle(root):
        return {"kind": "legacy", "minimum_semantic_version": 1, "reason": "bound historical Gate 1 inputs"}
    return {"kind": "unknown", "minimum_semantic_version": 2,
            "reason": "no verified pre-upgrade work; style claims and documents alone are insufficient"}


def verified_prior_v2_same_script(project: str | Path, plan: dict[str, Any]) -> bool:
    """Recognize an already-rendered v2 comparison from bound old inputs/media.

    A label or copied baseline alone is not enough: a previously sealed byte
    manifest outside this project checkout must identify this exact absolute
    project path and the original plan/board/voice/media bytes. Rebinding a new
    plan or preview, even for the same script, leaves that frozen identity.
    """
    root = Path(project).resolve()
    if not root.is_dir() or not isinstance(plan, dict) or plan.get("semantic_contract_version") != 2:
        return False
    baseline = _object(root / "artifacts/same-script-baseline.json")
    files = baseline.get("files") if isinstance(baseline, dict) and baseline.get("schema_version") == 1 else None
    names = ("source_script", "srt_source", "voice_source", "old_motion_plan", "old_storyboard", "old_media")
    if not isinstance(files, dict) or any(not isinstance(files.get(name), dict) for name in names):
        return False
    if any(not _bound_file(root, files[name].get("path"), files[name].get("sha256")) for name in names):
        return False
    old_media = root / files["old_media"]["path"]
    try:
        with old_media.open("rb") as stream:
            header = stream.read(12)
        if old_media.stat().st_size < 4096 or header[4:8] != b"ftyp":
            return False
    except OSError:
        return False
    for name, plan_hash in (("source_script", "source_sha256"), ("srt_source", "srt_sha256"),
                            ("voice_source", "audio_sha256")):
        if str(plan.get(plan_hash, "")).lower() != files[name]["sha256"].lower():
            return False
    if plan.get("audio_source") != files["voice_source"]["path"]:
        return False
    director = _object(root / "artifacts/director-storyboard.json")
    if not director or director.get("director_review_contract_version") != 1:
        return False
    plan_path = director.get("motion_plan_source")
    if not _bound_file(root, plan_path, director.get("motion_plan_sha256")):
        return False
    try:
        bound_plan = _object(root / plan_path)
    except (TypeError, ValueError):
        return False
    if bound_plan != plan:
        return False
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return False
    locked_paths = {root / plan_path, root / "artifacts/director-storyboard.json"}
    locked_paths.update(root / files[name]["path"] for name in names)
    for segment in segments:
        binding = segment.get("preview_binding") if isinstance(segment, dict) else None
        media = binding.get("preview_media") if isinstance(binding, dict) else None
        if not isinstance(media, dict) or not _bound_file(root, media.get("path"), media.get("sha256")):
            return False
        locked_paths.add(root / media["path"])
    # A closed project's external seal, not a plan field, grants this narrow
    # readback exception. Do not scan the machine for arbitrary "old" claims.
    for ancestor in (root, *list(root.parents)[:4]):
        releases = ancestor / "sealed-releases"
        if not releases.is_dir():
            continue
        for release in releases.iterdir():
            if not release.is_dir():
                continue
            result = _object(release / "封存验证结果.json")
            manifest = _object(release / "文件校验清单.json")
            if (not result or result.get("allArchiveEntriesRead") is not True or
                    result.get("sourceRecheckedAfterArchive") is not True or result.get("mismatchCount") != 0 or
                    not manifest or not isinstance(manifest.get("files"), list)):
                continue
            sealed = {}
            for entry in manifest["files"]:
                if not isinstance(entry, dict) or not isinstance(entry.get("sourcePath"), str):
                    continue
                try:
                    source = Path(entry["sourcePath"]).resolve()
                except (OSError, ValueError):
                    continue
                sealed[source] = str(entry.get("sha256", "")).lower()
            if all(path.resolve() in sealed and _bound_file(root, str(path.relative_to(root)), sealed[path.resolve()])
                   for path in locked_paths):
                return True
    return False


def requires_visual_decision(project: str | Path, plan: dict[str, Any]) -> bool:
    """New v2 work needs a concrete visual choice; frozen same-script work does not migrate."""
    return isinstance(plan, dict) and plan.get("semantic_contract_version") == 2 and not verified_prior_v2_same_script(project, plan)
