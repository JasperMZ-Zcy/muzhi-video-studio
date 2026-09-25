#!/usr/bin/env python3
"""Provider-agnostic, project-local video delivery routing and validation.

The router records a user's provider selection but never reads credentials,
contacts providers, executes a provider reference, renders video, or writes a
global preference.  Delivery validation consumes one normalized contract for
every provider, including manually produced Google Flow flatpacks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


STATE_RELATIVE = "artifacts/video-provider-selection.json"
SCHEMA_VERSION = 1
PLUGIN_VERSION = "1.1.0"
DEFAULT_SCOPE = "future_unsubmitted"
DELIVERY_DURATION_TOLERANCE = 0.08
SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
SAFE_TOOL_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_OUTPUT_CHARS = 12000
FORBIDDEN_REFERENCE_TERMS = (
    "secret",
    "token",
    "password",
    "credential",
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "http",
    "url",
    "config",
    "env",
    "sk-",
)


BUILTIN_REGISTRY: Tuple[Dict[str, Any], ...] = (
    {"id": "local-h3", "name": "Local ComfyUI / MiniMax-H3", "mode": "local_workflow"},
    {"id": "wan", "name": "Wan", "mode": "configured_api"},
    {"id": "minimax", "name": "MiniMax", "mode": "configured_api"},
    {
        "id": "google-flow",
        "name": "Google Flow",
        "mode": "manual",
        "manual_delivery": "first_frame_prompt_flatpack",
    },
)
DELIVERY_REQUIRED_FIELDS = (
    "shot_id",
    "source_provider",
    "path",
    "sha256",
    "duration",
    "width",
    "height",
    "fps",
    "source_audio_removed",
    "source_start",
    "timeline_start",
    "usable_duration",
)


class RouterError(RuntimeError):
    """Expected input, boundary, or contract failure."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _project_dir(project: str | Path) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise RouterError("--project must be an existing directory")
    return root


def _state_path(root: Path) -> Path:
    artifacts = root / "artifacts"
    if (artifacts.is_symlink() or getattr(artifacts, "is_junction", lambda: False)()
            or (artifacts.exists() and artifacts.resolve() != artifacts.absolute())):
        raise RouterError("artifacts directory must not be a symlink")
    if artifacts.exists() and not artifacts.is_dir():
        raise RouterError("artifacts path must be a directory")
    return root / STATE_RELATIVE


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".provider-router-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _new_state() -> Dict[str, Any]:
    timestamp = _now()
    return {
        "schema": SCHEMA_VERSION,
        "version": PLUGIN_VERSION,
        "created_at": timestamp,
        "updated_at": timestamp,
        "custom_registry": {},
        "selection": None,
        "history": [],
        # These router-owned collections are intentionally never cleared by a
        # provider switch. Other local tooling may add receipt details later.
        "delivery_receipts": [],
        "pending_job_ids": [],
    }


def _read_state(root: Path, required: bool = False) -> Optional[Dict[str, Any]]:
    path = _state_path(root)
    if not path.exists():
        if required:
            raise RouterError("provider selection does not exist; select a provider first")
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            state = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RouterError("provider selection state is not valid JSON") from exc
    if not isinstance(state, dict) or state.get("schema") != SCHEMA_VERSION:
        raise RouterError("unsupported provider selection state")
    if not isinstance(state.get("custom_registry"), dict) or not isinstance(state.get("history"), list):
        raise RouterError("provider selection state is malformed")
    return state


def _state_for_write(root: Path) -> Tuple[Path, Dict[str, Any]]:
    path = _state_path(root)
    state = _read_state(root)
    return path, state if state is not None else _new_state()


def _safe_id(value: Any, label: str = "provider id") -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise RouterError(label + " must be a safe lowercase slug")
    return value


def _quote(value: Optional[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouterError("--quote must contain the user's actual approval wording")
    return value.strip()


def _safe_tool_ref(value: Optional[str], required: bool) -> Optional[str]:
    if value is None or not value.strip():
        if required:
            raise RouterError("configured_api providers require a safe --tool-ref name")
        return None
    reference = value.strip()
    lowered = reference.lower()
    if not SAFE_TOOL_REF.fullmatch(reference) or any(term in lowered for term in FORBIDDEN_REFERENCE_TERMS):
        raise RouterError("--tool-ref must be a safe capability name, never a URL, credential, env, or config value")
    return reference


def _registry_from_state(state: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    registry = [dict(item) for item in BUILTIN_REGISTRY]
    if state is None:
        return registry
    custom = state.get("custom_registry", {})
    for provider_id in sorted(custom):
        item = custom[provider_id]
        if isinstance(item, dict):
            registry.append(dict(item))
    return registry


def list_providers(project: Optional[str | Path] = None) -> Dict[str, Any]:
    state = None if project is None else _read_state(_project_dir(project))
    return {"mode": "list", "providers": _registry_from_state(state), "project_local": project is not None}


def _provider_by_id(state: Mapping[str, Any], provider_id: str) -> Optional[Dict[str, Any]]:
    for provider in _registry_from_state(state):
        if provider.get("id") == provider_id:
            return provider
    return None


def register_provider(
    project: str | Path,
    provider_id: str,
    name: str,
    mode: str,
    quote: str,
    tool_ref: Optional[str] = None,
) -> Dict[str, Any]:
    root = _project_dir(project)
    path, state = _state_for_write(root)
    provider_id = _safe_id(provider_id)
    if provider_id in {item["id"] for item in BUILTIN_REGISTRY}:
        raise RouterError("a built-in provider cannot be replaced in a project registry")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise RouterError("--name must be a concise non-empty provider name")
    if mode not in {"configured_api", "manual"}:
        raise RouterError("--mode must be configured_api or manual")
    actual_quote = _quote(quote)
    safe_reference = _safe_tool_ref(tool_ref, required=mode == "configured_api")
    record: Dict[str, Any] = {
        "id": provider_id,
        "name": name.strip(),
        "mode": mode,
        "adapter_verified": False,
        "registered_at": _now(),
        "quote": actual_quote,
    }
    if safe_reference is not None:
        record["tool_ref"] = safe_reference
    existing = state["custom_registry"].get(provider_id)
    if existing is not None:
        comparable = {key: value for key, value in record.items() if key not in {"registered_at", "quote"}}
        old_comparable = {key: value for key, value in existing.items() if key not in {"registered_at", "quote"}}
        if comparable == old_comparable:
            return {"mode": "register", "changed": False, "idempotent": True, "provider": existing}
        raise RouterError("custom provider id already exists with different settings")
    state["custom_registry"][provider_id] = record
    state["updated_at"] = _now()
    _atomic_write(path, state)
    return {"mode": "register", "changed": True, "idempotent": False, "provider": record}


def select_provider(
    project: str | Path,
    provider_id: str,
    quote: Optional[str] = None,
    scope: str = DEFAULT_SCOPE,
) -> Dict[str, Any]:
    root = _project_dir(project)
    path, state = _state_for_write(root)
    provider_id = _safe_id(provider_id)
    if scope != DEFAULT_SCOPE:
        raise RouterError("only scope future_unsubmitted is permitted")
    provider = _provider_by_id(state, provider_id)
    if provider is None:
        raise RouterError("provider is not registered for this project")
    prior = state.get("selection")
    if isinstance(prior, dict) and prior.get("provider_id") == provider_id and prior.get("scope") == scope:
        return {"mode": "select", "changed": False, "idempotent": True, "selection": prior}
    actual_quote = _quote(quote)
    selection = {
        "provider_id": provider_id,
        "scope": DEFAULT_SCOPE,
        "quote": actual_quote,
        "selected_at": _now(),
    }
    history_record = dict(selection)
    if isinstance(prior, dict):
        history_record["action"] = "switched"
        history_record["from_provider"] = prior.get("provider_id")
    else:
        history_record["action"] = "selected"
    state["selection"] = selection
    state["history"].append(history_record)
    # No receipt or pending-job field is changed here; a switch only governs
    # later unsubmitted work and cannot rewrite already started delivery.
    state["updated_at"] = _now()
    _atomic_write(path, state)
    return {"mode": "select", "changed": True, "idempotent": False, "selection": selection}


def status(project: str | Path) -> Dict[str, Any]:
    root = _project_dir(project)
    state = _read_state(root)
    if state is None:
        return {
            "mode": "status",
            "selection": None,
            "needs_user_choice": True,
            "providers": _registry_from_state(None),
            "project_local": True,
        }
    selection = state.get("selection")
    return {
        "mode": "status",
        "selection": selection if isinstance(selection, dict) else None,
        "needs_user_choice": not isinstance(selection, dict),
        "providers": _registry_from_state(state),
        "custom_registry": state["custom_registry"],
        "history": state["history"],
        "delivery_receipts": state.get("delivery_receipts", []),
        "pending_job_ids": state.get("pending_job_ids", []),
        "project_local": True,
    }


def contract(project: str | Path) -> Dict[str, Any]:
    _project_dir(project)
    return {
        "mode": "contract",
        "contract_version": 1,
        "provider_agnostic": True,
        "renderer_provider_branches": False,
        "normalized_delivery": {
            "shot_id": "non-empty string",
            "source_provider": "safe provider slug",
            "provider_job_id": "optional string or null; manual delivery may use null",
            "path": "project-relative media file",
            "sha256": "lowercase SHA-256 of path",
            "duration": "positive seconds",
            "width": "positive pixels",
            "height": "positive pixels",
            "fps": "positive rational such as 30000/1001",
            "source_audio_removed": "boolean promise; true means no source audio stream",
            "source_start": "non-negative seconds",
            "timeline_start": "non-negative seconds",
            "usable_duration": "positive seconds not exceeding duration - source_start",
            "playback_rate": "optional; must equal 1",
        },
        "required_fields": list(DELIVERY_REQUIRED_FIELDS),
        "optional_fields": ["provider_job_id", "playback_rate"],
        "duration_tolerance_seconds_when_ffprobe_used": DELIVERY_DURATION_TOLERANCE,
        "quality_review_claimed": False,
    }


def _inside_project(root: Path, resolved: Path) -> str:
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise RouterError("path resolves outside --project") from exc


def _safe_project_file(root: Path, value: Any) -> Tuple[Path, str]:
    if not isinstance(value, str) or not value.strip():
        raise RouterError("path must be a non-empty project-relative string")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise RouterError("path must be a safe project-relative path")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RouterError("symlink traversal is forbidden")
    if not cursor.is_file():
        raise RouterError("declared file does not exist: " + relative.as_posix())
    resolved = cursor.resolve(strict=True)
    return resolved, _inside_project(root, resolved)


def _read_manifest(root: Path, manifest: str | Path) -> Tuple[Optional[Any], Dict[str, Any]]:
    result: Dict[str, Any] = {"name": "delivery_manifest", "passed": False, "errors": []}
    supplied = Path(manifest).expanduser()
    try:
        if supplied.is_absolute():
            try:
                supplied = supplied.resolve(strict=True).relative_to(root)
            except ValueError as exc:
                raise RouterError("delivery manifest must be inside --project") from exc
        path, relative = _safe_project_file(root, str(supplied))
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (RouterError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        result["errors"].append("invalid delivery manifest: " + str(exc))
        return None, result
    result["path"] = relative
    result["passed"] = True
    return payload, result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: Any, nonnegative: bool = False, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (nonnegative and number < 0) or (positive and number <= 0):
        return None
    return number


def _positive_int(value: Any) -> Optional[int]:
    number = _number(value, positive=True)
    if number is None or not number.is_integer():
        return None
    return int(number)


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


def _valid_delivery(root: Path, entry: Any, index: int) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    result: Dict[str, Any] = {"index": index, "passed": False}
    if not isinstance(entry, dict):
        result["error"] = "delivery entry must be an object"
        return None, result
    missing = [field for field in DELIVERY_REQUIRED_FIELDS if field not in entry]
    if missing:
        result["error"] = "delivery entry is missing " + ", ".join(missing)
        return None, result
    if not isinstance(entry["shot_id"], str) or not entry["shot_id"].strip():
        result["error"] = "shot_id must be a non-empty string"
        return None, result
    try:
        provider_id = _safe_id(entry["source_provider"], "source_provider")
    except RouterError as exc:
        result["error"] = str(exc)
        return None, result
    if "provider_job_id" in entry and entry["provider_job_id"] is not None:
        if not isinstance(entry["provider_job_id"], str) or not entry["provider_job_id"].strip():
            result["error"] = "provider_job_id must be a non-empty string or null"
            return None, result
    expected_hash = entry["sha256"].lower() if isinstance(entry["sha256"], str) and SHA256_RE.fullmatch(entry["sha256"]) else None
    if expected_hash is None:
        result["error"] = "sha256 must be a SHA-256 hex digest"
        return None, result
    duration = _number(entry["duration"], positive=True)
    width = _positive_int(entry["width"])
    height = _positive_int(entry["height"])
    fps = _rational(entry["fps"])
    source_start = _number(entry["source_start"], nonnegative=True)
    timeline_start = _number(entry["timeline_start"], nonnegative=True)
    usable_duration = _number(entry["usable_duration"], positive=True)
    if None in {duration, width, height, fps, source_start, timeline_start, usable_duration}:
        result["error"] = "duration, dimensions, fps, starts, and usable_duration are invalid"
        return None, result
    if not isinstance(entry["source_audio_removed"], bool):
        result["error"] = "source_audio_removed must be boolean"
        return None, result
    playback_rate = entry.get("playback_rate", 1)
    if _number(playback_rate, positive=True) != 1.0:
        result["error"] = "playback_rate must equal 1; speed changes are not permitted"
        return None, result
    if usable_duration > duration - source_start + 1e-9:
        result["error"] = "usable_duration exceeds duration minus source_start"
        return None, result
    try:
        path, relative = _safe_project_file(root, entry["path"])
    except RouterError as exc:
        result["error"] = str(exc)
        return None, result
    actual_hash = _sha256(path)
    result.update({"shot_id": entry["shot_id"], "source_provider": provider_id, "path": relative, "sha256": actual_hash})
    if actual_hash != expected_hash:
        result["error"] = "SHA-256 drift"
        return None, result
    return {
        "entry": entry,
        "path": path,
        "relative": relative,
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "source_audio_removed": entry["source_audio_removed"],
    }, result


def _bounded_text(value: Optional[str]) -> str:
    return (value or "")[:MAX_OUTPUT_CHARS]


def _run(command: Sequence[str], cwd: Path) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except FileNotFoundError as exc:
        return {"passed": False, "exit_code": None, "error": str(exc), "stdout": "", "stderr": ""}
    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "exit_code": None,
            "error": "ffprobe timed out",
            "stdout": _bounded_text(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr": _bounded_text(exc.stderr if isinstance(exc.stderr, str) else ""),
        }
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": _bounded_text(completed.stdout),
        "stderr": _bounded_text(completed.stderr),
    }


def _probe_delivery(root: Path, validated: Mapping[str, Any], ffprobe: str) -> Dict[str, Any]:
    path = validated["path"]
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    result: Dict[str, Any] = {
        "name": "ffprobe_delivery",
        "path": validated["relative"],
        "passed": False,
        "command": ["ffprobe", *command[1:-1], validated["relative"]],
    }
    outcome = _run(command, root)
    if not outcome["passed"]:
        result.update(outcome)
        return result
    try:
        payload = json.loads(outcome["stdout"])
    except json.JSONDecodeError:
        result.update({"exit_code": outcome["exit_code"], "error": "ffprobe did not return JSON"})
        return result
    if not isinstance(payload, dict) or not isinstance(payload.get("format"), dict) or not isinstance(payload.get("streams"), list):
        result.update({"exit_code": outcome["exit_code"], "error": "ffprobe JSON is missing format or streams"})
        return result
    duration = _number(payload["format"].get("duration"), positive=True)
    streams = payload["streams"]
    video = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    errors: List[str] = []
    if duration is None or abs(duration - validated["duration"]) > DELIVERY_DURATION_TOLERANCE:
        errors.append("ffprobe duration does not match normalized delivery")
    if len(video) != 1:
        errors.append("delivery must contain exactly one video stream")
    else:
        stream = video[0]
        if stream.get("width") != validated["width"] or stream.get("height") != validated["height"]:
            errors.append("ffprobe dimensions do not match normalized delivery")
        actual_fps = _rational(stream.get("r_frame_rate")) or _rational(stream.get("avg_frame_rate"))
        if actual_fps != validated["fps"]:
            errors.append("ffprobe frame rational does not match normalized delivery")
        else:
            result["fps"] = actual_fps
    if validated["source_audio_removed"] and audio:
        errors.append("source_audio_removed promised no audio stream")
    result.update(
        {
            "exit_code": outcome["exit_code"],
            "duration": duration,
            "streams": {"video": len(video), "audio": len(audio)},
        }
    )
    if errors:
        result["errors"] = errors
        return result
    result["passed"] = True
    return result


def validate_delivery(project: str | Path, manifest: str | Path, ffprobe: Optional[str] = None) -> Dict[str, Any]:
    root = _project_dir(project)
    payload, manifest_check = _read_manifest(root, manifest)
    if payload is None:
        return {"mode": "validate-delivery", "passed": False, "manifest_check": manifest_check, "checks": [], "probe_checks": [], "quality_review_claimed": False}
    entries = payload.get("deliveries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        manifest_check["passed"] = False
        manifest_check["errors"] = ["delivery manifest requires a non-empty deliveries list"]
        return {"mode": "validate-delivery", "passed": False, "manifest_check": manifest_check, "checks": [], "probe_checks": [], "quality_review_claimed": False}
    checks: List[Dict[str, Any]] = []
    validated_entries: List[Mapping[str, Any]] = []
    for index, entry in enumerate(entries):
        validated, check = _valid_delivery(root, entry, index)
        checks.append(check)
        if validated is not None:
            check["passed"] = True
            validated_entries.append(validated)
    probe_checks: List[Dict[str, Any]] = []
    if ffprobe:
        for validated in validated_entries:
            probe_checks.append(_probe_delivery(root, validated, ffprobe))
    passed = manifest_check["passed"] and all(item["passed"] for item in checks)
    if ffprobe:
        passed = passed and len(probe_checks) == len(validated_entries) and all(item["passed"] for item in probe_checks)
    return {
        "mode": "validate-delivery",
        "passed": passed,
        "manifest_check": manifest_check,
        "checks": checks,
        "probe_checks": probe_checks,
        "provider_agnostic": True,
        "renderer_provider_branches": False,
        "quality_review_claimed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listed = commands.add_parser("list", help="list built-in and optional project-local providers")
    listed.add_argument("--project", help="include only this project's custom registry")
    selected = commands.add_parser("select", help="select a provider for future unsubmitted project work")
    selected.add_argument("--project", required=True)
    selected.add_argument("--provider", required=True)
    selected.add_argument("--quote", help="user's actual approval wording; not repeated for an unchanged selection")
    selected.add_argument("--scope", default=DEFAULT_SCOPE, choices=(DEFAULT_SCOPE,))
    registered = commands.add_parser("register", help="add one project-local provider capability descriptor")
    registered.add_argument("--project", required=True)
    registered.add_argument("--id", required=True)
    registered.add_argument("--name", required=True)
    registered.add_argument("--mode", required=True, choices=("configured_api", "manual"))
    registered.add_argument("--tool-ref", help="safe named capability only; never a URL, credential, env, or config")
    registered.add_argument("--quote", required=True)
    current = commands.add_parser("status", help="show only this project's provider selection state")
    current.add_argument("--project", required=True)
    contract_command = commands.add_parser("contract", help="show the single provider-agnostic delivery contract")
    contract_command.add_argument("--project", required=True)
    validate = commands.add_parser("validate-delivery", help="validate normalized media deliveries without rendering")
    validate.add_argument("--project", required=True)
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--ffprobe", help="optional ffprobe path for actual duration, dimensions, FPS, and audio checks")
    return parser


def run(arguments: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    args = build_parser().parse_args(arguments)
    if args.command == "list":
        return list_providers(args.project)
    if args.command == "select":
        return select_provider(args.project, args.provider, args.quote, args.scope)
    if args.command == "register":
        return register_provider(args.project, args.id, args.name, args.mode, args.quote, args.tool_ref)
    if args.command == "status":
        return status(args.project)
    if args.command == "contract":
        return contract(args.project)
    if args.command == "validate-delivery":
        return validate_delivery(args.project, args.manifest, args.ffprobe)
    raise AssertionError("unreachable command")


def main(arguments: Optional[Sequence[str]] = None) -> int:
    try:
        result = run(arguments)
    except RouterError as exc:
        print(_json({"passed": False, "error": str(exc), "quality_review_claimed": False}), end="", file=sys.stderr)
        return 2
    print(_json(result), end="")
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
