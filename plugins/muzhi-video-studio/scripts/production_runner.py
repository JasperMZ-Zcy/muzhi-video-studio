#!/usr/bin/env python3
"""Read-only critical-gate runner for the Muzhi Editorial Studio plugin.

This module does not render, upload, schedule, call an API, or write state.
It maps bounded production stages to the original bundled validators and makes
input/media integrity failures explicit rather than inferring a pass from a
manifest field such as ``passed: true``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


VENDOR_SCRIPTS = (
    Path(__file__).resolve().parent.parent
    / "vendor"
    / "editorial-magazine-explainer-producer"
    / "scripts"
)
INPUT_MANIFEST = "artifacts/editorial-plugin-inputs.json"
STAGES = ("design", "storyboard", "batch", "ingest", "master")
MAX_OUTPUT_CHARS = 12000
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class RunnerError(RuntimeError):
    """An expected validation or command-line error."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _bounded_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return value[:MAX_OUTPUT_CHARS]


def _project_dir(project: str | Path) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise RunnerError("--project must be an existing directory")
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside_project(root: Path, value: Path) -> str:
    try:
        return value.relative_to(root).as_posix()
    except ValueError as exc:
        raise RunnerError("path resolves outside --project") from exc


def _safe_project_file(root: Path, supplied: Any) -> Tuple[Path, str]:
    """Resolve an existing regular file without accepting traversal or links."""
    if not isinstance(supplied, str) or not supplied.strip():
        raise RunnerError("path must be a non-empty project-relative string")
    relative = Path(supplied)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RunnerError("path must be a safe project-relative path")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RunnerError("symlink traversal is forbidden")
    if not cursor.is_file():
        raise RunnerError("declared file does not exist: " + relative.as_posix())
    resolved = cursor.resolve(strict=True)
    return resolved, _inside_project(root, resolved)


def _read_project_json(root: Path, relative: str) -> Any:
    path, _ = _safe_project_file(root, relative)
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunnerError("invalid JSON manifest: " + relative) from exc


def _validator_plan(stage: str) -> List[Dict[str, Any]]:
    if stage not in STAGES:
        raise RunnerError("--stage must be one of " + ", ".join(STAGES))
    plans: Dict[str, List[Dict[str, Any]]] = {
        "design": [
            {
                "name": "design_lock",
                "script": "validate_design_lock.py",
                "arguments": ["--lock", "artifacts/design-lock.json", "--require-approved"],
            }
        ],
        "storyboard": [
            {
                "name": "director_storyboard_plan",
                "script": "validate_director_storyboard.py",
                "arguments": ["--contract", "artifacts/director-storyboard.json", "--stage", "plan"],
            }
        ],
        "batch": [
            {
                "name": "director_storyboard_batch",
                "script": "validate_director_storyboard.py",
                "arguments": ["--contract", "artifacts/director-storyboard.json", "--stage", "batch"],
            },
            {
                "name": "production_enforcement",
                "script": "validate_production_enforcement.py",
                "arguments": ["--manifest", "artifacts/production-enforcement.json"],
            },
        ],
        "ingest": [
            {
                "name": "dynamic_asset_duration",
                "script": "validate_dynamic_asset_duration.py",
                "arguments": ["--manifest", "artifacts/dynamic-asset-duration-records.json"],
            }
        ],
        "master": [
            {
                "name": "editorial_project",
                "script": "validate_editorial_project.py",
                "arguments": [
                    "--project-contract",
                    "artifacts/editorial-project-contract.json",
                    "--qa-manifest",
                    "artifacts/editorial-qa-manifest-v1.json",
                ],
            },
            {
                "name": "production_enforcement",
                "script": "validate_production_enforcement.py",
                "arguments": ["--manifest", "artifacts/production-enforcement.json"],
            },
        ],
    }
    # Copy data so callers cannot mutate the canonical critical-gate mapping.
    return [{"name": item["name"], "script": item["script"], "arguments": list(item["arguments"])} for item in plans[stage]]


def plan_stage(stage: str) -> Dict[str, Any]:
    return {"mode": "plan", "stage": stage, "checks": _validator_plan(stage)}


def _as_sha256(value: Any) -> Optional[str]:
    if isinstance(value, str) and SHA256_RE.fullmatch(value):
        return value.lower()
    return None


def _verify_inputs(root: Path) -> Dict[str, Any]:
    """Verify the declared input allowlist before stage validators run."""
    result: Dict[str, Any] = {"name": "editorial_plugin_inputs", "passed": False, "files": [], "errors": []}
    try:
        payload = _read_project_json(root, INPUT_MANIFEST)
    except RunnerError as exc:
        result["errors"].append(str(exc))
        return result
    if not isinstance(payload, dict):
        result["errors"].append("input manifest must be a JSON object")
        return result
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        result["errors"].append("input manifest requires a non-empty files list")
        return result
    required_roles = payload.get("requiredroles", payload.get("required_roles", []))
    if not isinstance(required_roles, list) or any(not isinstance(role, str) or not role.strip() for role in required_roles):
        result["errors"].append("requiredroles must be a list of non-empty strings when present")
        return result
    seen_roles: set[str] = set()
    for index, entry in enumerate(files):
        file_result: Dict[str, Any] = {"index": index, "passed": False}
        if not isinstance(entry, dict):
            file_result["error"] = "file entry must be an object"
            result["files"].append(file_result)
            continue
        supplied_path = entry.get("path")
        file_result["path"] = supplied_path if isinstance(supplied_path, str) else None
        expected_hash = _as_sha256(entry.get("sha256"))
        if expected_hash is None:
            file_result["error"] = "file entry requires a SHA-256 hex digest"
            result["files"].append(file_result)
            continue
        role = entry.get("role")
        if role is not None and (not isinstance(role, str) or not role.strip()):
            file_result["error"] = "file role must be a non-empty string when present"
            result["files"].append(file_result)
            continue
        if isinstance(role, str):
            seen_roles.add(role)
            file_result["role"] = role
        try:
            path, relative = _safe_project_file(root, supplied_path)
            actual_hash = _sha256(path)
        except RunnerError as exc:
            file_result["error"] = str(exc)
            result["files"].append(file_result)
            continue
        file_result["path"] = relative
        file_result["sha256"] = actual_hash
        if actual_hash != expected_hash:
            file_result["error"] = "SHA-256 drift"
            result["files"].append(file_result)
            continue
        file_result["passed"] = True
        result["files"].append(file_result)
    missing_roles = sorted(set(required_roles) - seen_roles)
    if missing_roles:
        result["errors"].append("missing required roles: " + ", ".join(missing_roles))
    if any(not item["passed"] for item in result["files"]):
        result["errors"].append("one or more declared input files failed verification")
    result["passed"] = not result["errors"]
    return result


def _run_command(command: Sequence[str], cwd: Path, timeout: int = 120) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return {"passed": False, "exit_code": None, "stdout": "", "stderr": "", "error": str(exc)}
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "exit_code": None,
            "stdout": _bounded_text(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr": _bounded_text(exc.stderr if isinstance(exc.stderr, str) else ""),
            "error": "command timed out",
        }
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": _bounded_text(completed.stdout),
        "stderr": _bounded_text(completed.stderr),
    }


def _run_validator(root: Path, item: Mapping[str, Any]) -> Dict[str, Any]:
    script = VENDOR_SCRIPTS / str(item["script"])
    check: Dict[str, Any] = {
        "name": item["name"],
        "script": item["script"],
        "arguments": list(item["arguments"]),
    }
    if not script.is_file():
        check.update({"passed": False, "exit_code": None, "error": "bundled validator is missing"})
        return check
    check.update(_run_command([sys.executable, str(script), *item["arguments"]], root))
    return check


def check_stage(project: str | Path, stage: str) -> Dict[str, Any]:
    root = _project_dir(project)
    plan = _validator_plan(stage)
    input_check = _verify_inputs(root)
    checks = [_run_validator(root, item) for item in plan]
    passed = input_check["passed"] and all(check["passed"] for check in checks)
    return {
        "mode": "check",
        "stage": stage,
        "passed": passed,
        "input_check": input_check,
        "checks": checks,
        "quality_review_claimed": False,
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _positive_int(value: Any) -> bool:
    return _is_number(value) and float(value).is_integer() and int(value) > 0


def _media_manifest(root: Path, manifest: str | Path) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    result: Dict[str, Any] = {"name": "media_manifest", "passed": False, "errors": []}
    try:
        supplied = Path(manifest).expanduser()
        # CLI callers may hand over an absolute local path, but the manifest
        # itself remains bounded to this project and receives the same
        # no-traversal check as a relative manifest path.
        if supplied.is_absolute():
            try:
                supplied = supplied.resolve(strict=True).relative_to(root)
            except ValueError as exc:
                raise RunnerError("media manifest must be inside --project") from exc
        path, relative = _safe_project_file(root, str(supplied))
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (RunnerError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["errors"].append("invalid media manifest: " + str(exc))
        return None, result
    result["path"] = relative
    if not isinstance(payload, dict):
        result["errors"].append("media manifest must be a JSON object")
        return None, result
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        result["errors"].append("media manifest requires a non-empty files list")
    tolerance = payload.get("max_duration_tol")
    if not _is_number(tolerance) or float(tolerance) < 0:
        result["errors"].append("media manifest requires non-negative max_duration_tol")
    if result["errors"]:
        return None, result
    result["passed"] = True
    return payload, result


def _validate_media_entry(root: Path, entry: Any, index: int, tolerance: float) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    result: Dict[str, Any] = {"index": index, "passed": False}
    required = ("path", "sha256", "kind", "expected_duration", "allow_audio")
    if not isinstance(entry, dict):
        result["error"] = "media file entry must be an object"
        return None, result
    missing = [key for key in required if key not in entry]
    if missing:
        result["error"] = "media file entry is missing " + ", ".join(missing)
        return None, result
    if entry.get("kind") not in {"video", "audio"}:
        result["error"] = "kind must be video or audio"
        return None, result
    if _as_sha256(entry.get("sha256")) is None:
        result["error"] = "media file entry requires a SHA-256 hex digest"
        return None, result
    if not _is_number(entry.get("expected_duration")) or float(entry["expected_duration"]) < 0:
        result["error"] = "expected_duration must be a non-negative number"
        return None, result
    if not isinstance(entry.get("allow_audio"), bool):
        result["error"] = "allow_audio must be true or false"
        return None, result
    if entry["kind"] == "audio" and not entry["allow_audio"]:
        result["error"] = "audio entries must set allow_audio to true"
        return None, result
    if entry["kind"] == "video":
        if not _positive_int(entry.get("expected_width")) or not _positive_int(entry.get("expected_height")):
            result["error"] = "video expected_width and expected_height must be positive integers"
            return None, result
        if entry.get("expected_fps") is not None and _rational(entry["expected_fps"]) is None:
            result["error"] = "video expected_fps must be a positive rational such as 30000/1001"
            return None, result
    # A pure audio entry has no meaningful dimensions, and a silent video has
    # no meaningful audio settings.  Those fields are intentionally optional
    # in both cases so an honest manifest never needs fake placeholders.
    if entry["allow_audio"]:
        if not _positive_int(entry.get("sample_rate")) or not _positive_int(entry.get("channels")):
            result["error"] = "audio-enabled entries require positive sample_rate and channels"
            return None, result
    try:
        path, relative = _safe_project_file(root, entry["path"])
    except RunnerError as exc:
        result["error"] = str(exc)
        return None, result
    actual_hash = _sha256(path)
    result.update({"path": relative, "sha256": actual_hash})
    if actual_hash != _as_sha256(entry["sha256"]):
        result["error"] = "SHA-256 drift"
        return None, result
    return {
        "entry": entry,
        "path": path,
        "relative": relative,
        "sha256": actual_hash,
        "tolerance": tolerance,
    }, result


def _rational(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+/\d+", value):
        return None
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    if fraction <= 0:
        return None
    return str(fraction.numerator) + "/" + str(fraction.denominator)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _probe_check(root: Path, validated: Mapping[str, Any], ffprobe: str) -> Dict[str, Any]:
    entry = validated["entry"]
    path = validated["path"]
    result: Dict[str, Any] = {
        "name": "media_probe",
        "path": validated["relative"],
        "sha256": validated["sha256"],
        "bytes": path.stat().st_size,
        "passed": False,
    }
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,sample_rate,channels,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    outcome = _run_command(command, root)
    result["command"] = ["ffprobe", *command[1:-1], validated["relative"]]
    if not outcome["passed"]:
        result.update(outcome)
        return result
    try:
        payload = json.loads(outcome["stdout"])
    except json.JSONDecodeError:
        result.update({"exit_code": outcome["exit_code"], "error": "ffprobe did not return JSON", "stdout": outcome["stdout"], "stderr": outcome["stderr"]})
        return result
    if not isinstance(payload, dict) or not isinstance(payload.get("format"), dict) or not isinstance(payload.get("streams"), list):
        result.update({"exit_code": outcome["exit_code"], "error": "ffprobe JSON is missing format or streams"})
        return result
    duration = _number(payload["format"].get("duration"))
    if duration is None:
        result.update({"exit_code": outcome["exit_code"], "error": "ffprobe duration is missing or invalid"})
        return result
    streams = payload["streams"]
    video_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    errors: List[str] = []
    expected_duration = float(entry["expected_duration"])
    if abs(duration - expected_duration) > validated["tolerance"]:
        errors.append("duration outside max_duration_tol")
    if entry["kind"] == "video":
        if len(video_streams) != 1:
            errors.append("video entry must contain exactly one video stream")
        else:
            video = video_streams[0]
            if video.get("width") != int(entry["expected_width"]) or video.get("height") != int(entry["expected_height"]):
                errors.append("video dimensions do not match manifest")
            frame_rate = _rational(video.get("r_frame_rate")) or _rational(video.get("avg_frame_rate"))
            if frame_rate is None:
                errors.append("video frame rational is missing or invalid")
            else:
                result["frame_rate"] = frame_rate
                if entry.get("expected_fps") is not None:
                    expected_fps = _rational(entry["expected_fps"])
                    result["expected_fps"] = expected_fps
                    if frame_rate != expected_fps:
                        errors.append("video frame rational does not match expected_fps")
        if entry["allow_audio"]:
            if len(audio_streams) != 1:
                errors.append("allow_audio video entry must contain exactly one audio stream")
        elif audio_streams:
            errors.append("unexpected extra audio stream")
    else:
        if video_streams:
            errors.append("audio entry must not contain a video stream")
        if len(audio_streams) != 1:
            errors.append("audio entry must contain exactly one audio stream")
    if audio_streams:
        audio = audio_streams[0]
        try:
            actual_rate = int(audio.get("sample_rate"))
        except (TypeError, ValueError):
            actual_rate = None
        if actual_rate != int(entry["sample_rate"]):
            errors.append("audio sample_rate does not match manifest")
        if audio.get("channels") != int(entry["channels"]):
            errors.append("audio channels do not match manifest")
    result.update(
        {
            "exit_code": outcome["exit_code"],
            "duration": duration,
            "expected_duration": expected_duration,
            "max_duration_tol": validated["tolerance"],
            "streams": {"video": len(video_streams), "audio": len(audio_streams)},
        }
    )
    if errors:
        result["errors"] = errors
        return result
    result["passed"] = True
    return result


def _decode_check(root: Path, media_check: Mapping[str, Any], ffmpeg: str) -> Dict[str, Any]:
    relative = str(media_check["path"])
    path, _ = _safe_project_file(root, relative)
    command = [ffmpeg, "-v", "error", "-threads", "2", "-i", str(path), "-map", "0", "-f", "null", "-"]
    result = {
        "name": "full_decode",
        "path": relative,
        "threads": 2,
        "command": ["ffmpeg", "-v", "error", "-threads", "2", "-i", relative, "-map", "0", "-f", "null", "-"],
    }
    result.update(_run_command(command, root))
    return result


def _resolve_tool(explicit: Optional[str], default_name: str) -> Optional[str]:
    if explicit:
        return explicit
    return shutil.which(default_name)


def media_audit(
    project: str | Path,
    manifest: str | Path,
    ffprobe: Optional[str] = None,
    ffmpeg: Optional[str] = None,
    decode: bool = False,
) -> Dict[str, Any]:
    """Audit only declared media, keeping all output read-only and reproducible."""
    root = _project_dir(project)
    payload, manifest_check = _media_manifest(root, manifest)
    if payload is None:
        return {"mode": "media-audit", "passed": False, "manifest_check": manifest_check, "checks": [], "decode_checks": []}
    probe_tool = _resolve_tool(ffprobe, "ffprobe")
    if not probe_tool:
        return {
            "mode": "media-audit",
            "passed": False,
            "manifest_check": manifest_check,
            "checks": [{"name": "ffprobe", "passed": False, "error": "ffprobe is unavailable"}],
            "decode_checks": [],
        }
    tolerance = float(payload["max_duration_tol"])
    checks: List[Dict[str, Any]] = []
    validated_entries: List[Mapping[str, Any]] = []
    for index, entry in enumerate(payload["files"]):
        validated, entry_check = _validate_media_entry(root, entry, index, tolerance)
        if validated is None:
            entry_check["name"] = "media_manifest_entry"
            checks.append(entry_check)
            continue
        probe = _probe_check(root, validated, probe_tool)
        checks.append(probe)
        if probe["passed"]:
            validated_entries.append(validated)
    decode_checks: List[Dict[str, Any]] = []
    if decode:
        decoder = _resolve_tool(ffmpeg, "ffmpeg")
        if not decoder:
            decode_checks.append({"name": "ffmpeg", "passed": False, "error": "ffmpeg is unavailable", "threads": 2})
        else:
            # Intentionally serial: one full decode at a time, at most two
            # decoder threads, so QC cannot turn into an uncontrolled render.
            for check in checks:
                if check.get("name") == "media_probe" and check.get("passed"):
                    decode_checks.append(_decode_check(root, check, decoder))
    passed = manifest_check["passed"] and bool(checks) and all(item["passed"] for item in checks)
    if decode:
        passed = passed and bool(decode_checks) and all(item["passed"] for item in decode_checks)
    return {
        "mode": "media-audit",
        "passed": passed,
        "manifest_check": manifest_check,
        "checks": checks,
        "decode_checks": decode_checks,
        "quality_review_claimed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="show original bundled validators for a production stage")
    plan.add_argument("--stage", required=True, choices=STAGES)
    check = commands.add_parser("check", help="verify inputs then execute original bundled validators")
    check.add_argument("--project", required=True)
    check.add_argument("--stage", required=True, choices=STAGES)
    audit = commands.add_parser("media-audit", help="audit only declared media bytes and probe facts")
    audit.add_argument("--project", required=True)
    audit.add_argument("--manifest", required=True, help="project-relative media manifest JSON")
    audit.add_argument("--ffprobe", help="ffprobe executable or path; defaults to PATH")
    audit.add_argument("--ffmpeg", help="ffmpeg executable or path; used only with --decode")
    audit.add_argument("--decode", action="store_true", help="serial full ffmpeg decode with two threads")
    return parser


def run(arguments: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    args = build_parser().parse_args(arguments)
    if args.command == "plan":
        return plan_stage(args.stage)
    if args.command == "check":
        return check_stage(args.project, args.stage)
    if args.command == "media-audit":
        return media_audit(args.project, args.manifest, args.ffprobe, args.ffmpeg, args.decode)
    raise AssertionError("unreachable command")


def main(arguments: Optional[Sequence[str]] = None) -> int:
    try:
        result = run(arguments)
    except RunnerError as exc:
        print(_json({"passed": False, "error": str(exc), "quality_review_claimed": False}), end="", file=sys.stderr)
        return 2
    print(_json(result), end="")
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
