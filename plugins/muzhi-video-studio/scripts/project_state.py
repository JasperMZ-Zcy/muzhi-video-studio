#!/usr/bin/env python3
"""Bounded, local project state for the Muzhi Editorial Studio plugin.

This module deliberately manages only ``artifacts/editorial-plugin-state.json``
inside an explicitly named project.  It never migrates or rewrites a project's
existing metadata, and it has no network, global-configuration, or installer
side effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple


PLUGIN_VERSION = "1.1.0"
SCHEMA_VERSION = 1
ARTIFACTS_DIR = "artifacts"
STATE_FILENAME = "editorial-plugin-state.json"
LOCK_FILENAME = ".editorial-plugin-state.lock"
STAGES = ("planning", "assets", "editing", "review", "delivered", "scheduled", "published")
CHANGE_IMPACTS = {
    "audio": ("audio", "editing", "review"),
    "captions": ("captions", "editing", "review"),
    "visuals": ("visuals", "assets", "editing", "review"),
    "covers": ("covers", "release"),
    "publication": ("publication", "release"),
}
FORBIDDEN_OVERRIDE_TERMS = (
    "secret",
    "token",
    "password",
    "credential",
    "auth",
    "publication",
    "publish",
    "platform",
    "post_id",
    "money",
    "budget",
    "cost",
    "payment",
    "price",
    "billing",
    "fund",
)
SECRET_FILE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
SECRET_FILE_TERMS = ("secret", "credential", "password", "token", "private_key")
MAX_METADATA_TEXT_BYTES = 64 * 1024
MAX_METADATA_VALUE_CHARS = 240


class StateError(RuntimeError):
    """Base error for expected, user-actionable state failures."""


class ValidationError(StateError):
    pass


class RevisionConflict(StateError):
    pass


class HashDriftError(StateError):
    pass


class ApprovalError(StateError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _project_dir(project: str | Path) -> Path:
    path = Path(project).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValidationError("--project must be an existing directory")
    return path


def state_path(project: str | Path) -> Path:
    return _state_dir(project) / STATE_FILENAME


def _state_dir(project: str | Path) -> Path:
    directory = _project_dir(project) / ARTIFACTS_DIR
    # State is deliberately confined to the project. Do not follow a user or
    # legacy symlink named "artifacts" into another location for a write.
    if directory.is_symlink():
        raise ValidationError("artifacts directory must not be a symlink")
    if directory.exists() and not directory.is_dir():
        raise ValidationError("artifacts path must be a directory")
    return directory


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_to(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValidationError("file must resolve inside --project") from exc


def _existing_regular_file_in_project(project: str | Path, filename: str | Path) -> Tuple[Path, str]:
    """Resolve a lock/approval file while keeping it inside the named project."""
    root = _project_dir(project)
    supplied = Path(filename).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValidationError("file does not exist") from exc
    relative = _relative_to(root, resolved)
    if not resolved.is_file():
        raise ValidationError("file must be a regular file")
    return resolved, relative


def _new_state() -> Dict[str, Any]:
    created = _now()
    return {
        "schema": SCHEMA_VERSION,
        "version": PLUGIN_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "revision": 0,
        "stage": "planning",
        "created_at": created,
        "updated_at": created,
        "stage_history": [{"stage": "planning", "at": created, "source": "init"}],
        "locks": {},
        "approvals": {},
        "overrides": {"project": {}, "revisions": {}},
    }


def _validate_state(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("plugin state must be a JSON object")
    if value.get("schema") != SCHEMA_VERSION:
        raise ValidationError("unsupported plugin state schema")
    if not isinstance(value.get("version"), str):
        raise ValidationError("plugin state is missing its pinned version")
    if value.get("stage") not in STAGES:
        raise ValidationError("plugin state has an invalid stage")
    if not isinstance(value.get("revision"), int) or value["revision"] < 0:
        raise ValidationError("plugin state has an invalid revision")
    for key in ("locks", "approvals", "overrides"):
        if not isinstance(value.get(key), dict):
            raise ValidationError("plugin state is missing " + key)
    overrides = value["overrides"]
    if not isinstance(overrides.get("project"), dict) or not isinstance(overrides.get("revisions"), dict):
        raise ValidationError("plugin state has malformed overrides")
    return value


def _read_state_from_path(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ValidationError("plugin state does not exist; run init first")
    try:
        with path.open("r", encoding="utf-8") as stream:
            return _validate_state(json.load(stream))
    except json.JSONDecodeError as exc:
        raise ValidationError("plugin state is not valid JSON") from exc


def read_state(project: str | Path) -> Dict[str, Any]:
    """Read state only.  This function creates no directories or files."""
    return _read_state_from_path(state_path(project))


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".editorial-state-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json_dump(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _exclusive_state_lock(directory: Path, timeout_seconds: float = 3.0) -> Iterator[None]:
    """A small local lock, released even when a state operation fails.

    O_EXCL works across normal local Windows/macOS/Linux filesystems.  A very
    old abandoned lock is recoverable; a current lock is never overwritten.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / LOCK_FILENAME
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    while not acquired:
        try:
            descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(_json_dump({"pid": os.getpid(), "created_at": _now()}))
            acquired = True
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                if age > 15 * 60:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RevisionConflict("another local state update is still in progress")
            time.sleep(0.04)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def initialize_project(project: str | Path) -> Tuple[Dict[str, Any], bool]:
    """Create the plugin-owned artifact once, without reading/writing project.json."""
    directory = _state_dir(project)
    path = directory / STATE_FILENAME
    with _exclusive_state_lock(directory):
        if path.exists():
            return _read_state_from_path(path), False
        value = _new_state()
        _atomic_write(path, value)
        return value, True


def _check_expected_revision(state: Mapping[str, Any], expected_revision: Optional[int]) -> None:
    if expected_revision is not None and state["revision"] != expected_revision:
        raise RevisionConflict(
            "state revision changed (expected {0}, current {1})".format(expected_revision, state["revision"])
        )


def _mutate(
    project: str | Path,
    expected_revision: Optional[int],
    change: Any,
) -> Dict[str, Any]:
    directory = _state_dir(project)
    path = directory / STATE_FILENAME
    with _exclusive_state_lock(directory):
        state = _read_state_from_path(path)
        _check_expected_revision(state, expected_revision)
        changed, result = change(state)
        if changed:
            state["revision"] += 1
            state["updated_at"] = _now()
            _atomic_write(path, state)
        response = dict(result)
        response["state"] = state
        response["changed"] = changed
        return response


def set_stage(
    project: str | Path,
    stage: str,
    quote: Optional[str] = None,
    post_id: Optional[str] = None,
    platform: Optional[str] = None,
    published_at: Optional[str] = None,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    if stage not in STAGES:
        raise ValidationError("invalid stage")
    if stage in {"scheduled", "published"} and not (quote or "").strip():
        raise ValidationError("--quote is required for scheduled and published stages")
    if stage == "published":
        missing = [
            flag
            for flag, value in (("--post-id", post_id), ("--platform", platform), ("--published-at", published_at))
            if not (value or "").strip()
        ]
        if missing:
            raise ValidationError("published requires " + ", ".join(missing))
        _validate_published_at(published_at)

    def change(state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        publication = None
        if stage == "published":
            publication = {
                "post_id": post_id.strip(),
                "platform": platform.strip(),
                "published_at": published_at.strip(),
                "quote": quote.strip(),
            }
        unchanged = state["stage"] == stage and state.get("publication") == publication
        if unchanged:
            return False, {"stage": stage, "idempotent": True}
        state["stage"] = stage
        # Scheduling is an approval point, not publication metadata.  In
        # particular it cannot synthesize a post id or a platform.
        if stage == "published":
            state["publication"] = publication
        else:
            state.pop("publication", None)
        state.setdefault("stage_history", []).append(
            {"stage": stage, "at": _now(), "quote": quote.strip() if quote else None}
        )
        return True, {"stage": stage, "idempotent": False}

    return _mutate(project, expected_revision, change)


def _validate_published_at(value: Optional[str]) -> None:
    """Require a real ISO-8601 date-time carrying an explicit UTC offset."""
    if not isinstance(value, str):
        raise ValidationError("--published-at must be an ISO-8601 timestamp with a timezone")
    candidate = value.strip()
    # datetime.fromisoformat historically did not accept Z on every supported
    # Python version, whereas it accepts the equivalent explicit +00:00.
    normalized = candidate[:-1] + "+00:00" if candidate.endswith(("Z", "z")) else candidate
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError("--published-at must be an ISO-8601 timestamp with a timezone") from exc
    if "T" not in candidate.upper() or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError("--published-at must be an ISO-8601 timestamp with a timezone")


def lock_asset(
    project: str | Path,
    key: str,
    filename: str | Path,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    if not key or not key.strip():
        raise ValidationError("--key must not be empty")
    file_path, relative = _existing_regular_file_in_project(project, filename)
    asset_hash = _sha256(file_path)

    def change(state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        record = {"file": relative, "sha256": asset_hash, "locked_at": _now()}
        prior = state["locks"].get(key)
        if prior and prior.get("file") == relative and prior.get("sha256") == asset_hash:
            return False, {"lock": prior, "idempotent": True}
        state["locks"][key] = record
        return True, {"lock": record, "idempotent": False}

    return _mutate(project, expected_revision, change)


def approve_asset(
    project: str | Path,
    key: str,
    quote: str,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    if not (quote or "").strip():
        raise ValidationError("--quote must not be empty")

    def change(state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        lock = state["locks"].get(key)
        if not isinstance(lock, dict):
            raise ValidationError("asset key is not locked")
        file_path, _ = _existing_regular_file_in_project(project, lock.get("file", ""))
        actual_hash = _sha256(file_path)
        if actual_hash != lock.get("sha256"):
            raise HashDriftError("locked asset has changed; lock its new hash before approving")
        per_key = state["approvals"].setdefault(key, {})
        previous = per_key.get(actual_hash)
        if previous:
            # The approval record is immutable and a second command requires no
            # confirmation or duplicated state entry for the same asset hash.
            return False, {"approval": previous, "idempotent": True}
        approval = {"sha256": actual_hash, "approved_at": _now(), "quote": quote.strip()}
        per_key[actual_hash] = approval
        return True, {"approval": approval, "idempotent": False}

    return _mutate(project, expected_revision, change)


def verify_asset(project: str | Path, key: str, require_approval: bool = True) -> Dict[str, Any]:
    """Verify a locked hash, optionally without asserting a user approval.

    ``require_approval=False`` is for agent-side integrity checks. It confirms
    the locked file has not drifted, but it never represents that check as a
    user visual/creative approval.
    """
    state = read_state(project)
    lock = state["locks"].get(key)
    if not isinstance(lock, dict):
        raise ValidationError("asset key is not locked")
    file_path, relative = _existing_regular_file_in_project(project, lock.get("file", ""))
    actual_hash = _sha256(file_path)
    if actual_hash != lock.get("sha256"):
        raise HashDriftError(
            "hash drift for {0}: locked {1}, current {2}".format(relative, lock.get("sha256"), actual_hash)
        )
    approval = state["approvals"].get(key, {}).get(actual_hash)
    if not approval and require_approval:
        raise ApprovalError("current locked hash has not been approved")
    return {
        "verified": True,
        "approved": bool(approval),
        "key": key,
        "file": relative,
        "sha256": actual_hash,
        "approval": approval,
        "revision": state["revision"],
    }


def _is_forbidden_override_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(term in lowered for term in FORBIDDEN_OVERRIDE_TERMS)


def _walk_value_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for name, child in value.items():
            yield str(name)
            yield from _walk_value_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_value_keys(child)


def set_override(
    project: str | Path,
    scope: str,
    key: str,
    value_json: str,
    quote: str,
    expected_revision: Optional[int] = None,
    revision_id: Optional[str] = None,
) -> Dict[str, Any]:
    if scope not in {"project", "revision"}:
        raise ValidationError("--scope must be project or revision")
    parts = key.split(".")
    if not key or any(not part.strip() for part in parts):
        raise ValidationError("--key must be a non-empty dotted key")
    if _is_forbidden_override_key(key):
        raise ValidationError("security, authentication, publication, and money overrides are forbidden")
    if not (quote or "").strip():
        raise ValidationError("--quote must not be empty")
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as exc:
        raise ValidationError("--value must be valid JSON") from exc
    if any(_is_forbidden_override_key(name) for name in _walk_value_keys(value)):
        raise ValidationError("override value contains a forbidden field")

    def change(state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        overrides = state["overrides"]
        bucket_name = "project"
        revision_key = None
        if scope == "revision":
            bucket_name = "revisions"
            revision_key = revision_id.strip() if revision_id else "revision-" + str(state["revision"])
            if not revision_key:
                raise ValidationError("--revision-id must not be empty")
            bucket = overrides["revisions"].setdefault(revision_key, {})
        else:
            bucket = overrides["project"]
        record = {"value": value, "quote": quote.strip(), "set_at": _now(), "scope": scope}
        if bucket.get(key) and bucket[key].get("value") == value and bucket[key].get("quote") == quote.strip():
            return False, {"override": bucket[key], "idempotent": True, "revision_id": revision_key}
        bucket[key] = record
        return True, {"override": record, "idempotent": False, "revision_id": revision_key}

    return _mutate(project, expected_revision, change)


def plan_change(domain: str) -> Dict[str, Any]:
    if domain not in CHANGE_IMPACTS:
        raise ValidationError("invalid change domain")
    return {"domain": domain, "affected": list(CHANGE_IMPACTS[domain])}


def _bounded_scalar(value: Any) -> Any:
    """Return a non-sensitive, bounded scalar or omit containers entirely."""
    if isinstance(value, str):
        return value[:MAX_METADATA_VALUE_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def _object_scalar_at(value: Any, *parts: str) -> Any:
    cursor = value
    for part in parts:
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return _bounded_scalar(cursor)


def _legacy_project_summary(path: Path, root: Path) -> Dict[str, Any]:
    """Inspect only the three migration-relevant legacy fields, never objects."""
    result: Dict[str, Any] = {"path": _relative_to(root, path), "exists": path.is_file()}
    if not path.is_file():
        return result
    result["bytes"] = path.stat().st_size
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            parsed = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result["json"] = False
        return result
    result["json"] = isinstance(parsed, dict)
    if not isinstance(parsed, dict):
        return result
    current_status = None
    for parts in (("current", "status"), ("currentStatus",), ("current_status",), ("status",)):
        current_status = _object_scalar_at(parsed, *parts)
        if current_status is not None:
            break
    selected = {
        "current_status": current_status,
        "production_current_gate": _object_scalar_at(parsed, "production", "currentGate"),
        "publication_status": _object_scalar_at(parsed, "publication", "status"),
    }
    # Omit absent fields: this is observation only, never a plugin-created
    # fallback stage such as planning.
    result["selected"] = {name: value for name, value in selected.items() if value is not None}
    return result


def _metadata_summary(path: Path, root: Path) -> Dict[str, Any]:
    """Return bounded job-card metadata without returning its contents."""
    result: Dict[str, Any] = {"path": _relative_to(root, path), "exists": path.is_file()}
    if not path.is_file():
        return result
    result["bytes"] = path.stat().st_size
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                json.load(stream)
            result["json"] = True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result["json"] = False
        return result
    if suffix in {".md", ".markdown", ".txt"}:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_METADATA_TEXT_BYTES)
            text = raw.decode("utf-8-sig", errors="replace")
        except OSError:
            result["text"] = False
            return result
        result["text"] = True
        title = next((line[1:].strip() for line in text.splitlines() if line.startswith("#") and line[1:].strip()), None)
        if title:
            result["title"] = title[:MAX_METADATA_VALUE_CHARS]
        # One labelled scalar helps a person resume a project without exposing
        # document bodies or broad project metadata.
        match = re.search(r"(?im)^\s*(?:status|stage|当前状态|阶段)\s*[:：]\s*(.+?)\s*$", text)
        if match:
            result["status_hint"] = match.group(1).strip()[:MAX_METADATA_VALUE_CHARS]
    return result


def read_status(project: str | Path) -> Dict[str, Any]:
    """Return current plugin state, or a bounded non-migration inspection."""
    root = _project_dir(project)
    artifacts = _state_dir(root)
    path = artifacts / STATE_FILENAME
    if path.exists():
        return {"state": _read_state_from_path(path), "migration": {"status": "plugin_state_present"}}
    candidates = [
        root / "project.json",
        root / "job-card.json",
        root / "jobcard.json",
        root / "job_card.json",
        root / ARTIFACTS_DIR / "job-card.json",
        root / ARTIFACTS_DIR / "jobcard.json",
        root / ARTIFACTS_DIR / "job_card.json",
        root / ARTIFACTS_DIR / "editorial-job-card.md",
        root / ARTIFACTS_DIR / "HANDOFF.md",
        root / "HANDOFF.md",
    ]
    job_cards = [_metadata_summary(candidate, root) for candidate in candidates[1:] if candidate.is_file()]
    return {
        "state": None,
        "migration": {
            "status": "not_claimed_migrated",
            "claimed_migrated": False,
            "project_json": _legacy_project_summary(candidates[0], root),
            "job_cards": job_cards,
        },
    }


def _is_secret_filename(relative: Path) -> bool:
    for part in relative.parts:
        lowered = part.lower()
        if lowered == "secrets" or lowered.startswith(".env"):
            return True
        if any(term in lowered for term in SECRET_FILE_TERMS):
            return True
    return relative.suffix.lower() in SECRET_FILE_SUFFIXES


def _manifest_file(project: Path, item: Any) -> Tuple[Path, Path]:
    if not isinstance(item, str) or not item.strip():
        raise ValidationError("manifest files must be non-empty strings")
    relative = Path(item)
    # An explicit package manifest is project-relative.  Refusing absolute and
    # parent paths prevents a manifest from becoming a general file copier.
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValidationError("manifest file must be a safe project-relative path")
    if _is_secret_filename(relative):
        raise ValidationError("manifest contains a secret-like filename")
    lexical = project.joinpath(relative)
    cursor = project
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValidationError("symlink traversal is forbidden in package manifests")
    if not lexical.exists() or not lexical.is_file():
        raise ValidationError("manifest file does not exist: " + relative.as_posix())
    try:
        resolved = lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValidationError("manifest file disappeared during preflight") from exc
    _relative_to(project, resolved)
    return resolved, relative


def _read_manifest(argument: str) -> List[Any]:
    raw: Any
    candidate = Path(argument).expanduser()
    if candidate.is_file():
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError("manifest is not valid JSON") from exc
    else:
        try:
            raw = json.loads(argument)
        except json.JSONDecodeError as exc:
            raise ValidationError("--manifest must be JSON or a path to a JSON file") from exc
    if isinstance(raw, dict):
        raw = raw.get("files")
    if not isinstance(raw, list):
        raise ValidationError("manifest must be a JSON list or an object with a files list")
    return raw


def _reject_symlink_ancestors(path: Path) -> None:
    """Reject an output path if it would traverse any existing symlink."""
    lexical = Path(os.path.abspath(str(path)))
    cursor = lexical
    while True:
        if cursor.is_symlink():
            raise ValidationError("destination must not traverse a symlink")
        parent = cursor.parent
        if parent == cursor:
            return
        cursor = parent


def package_files(project: str | Path, manifest: str, destination: str | Path) -> Dict[str, Any]:
    """Copy a preflighted, flat allowlist into a destination without deleting.

    A differing existing basename aborts before the destination is created or
    any source is copied.  Identical existing files are left untouched.
    """
    root = _project_dir(project)
    entries = _read_manifest(manifest)
    staged: List[Tuple[Path, Path, str, str, int]] = []
    basenames: set[str] = set()
    for entry in entries:
        source, relative = _manifest_file(root, entry)
        basename = source.name
        folded = basename.casefold()
        if folded in basenames:
            raise ValidationError("flat package basename collision: " + basename)
        basenames.add(folded)
        staged.append((source, relative, basename, _sha256(source), source.stat().st_size))
    if not staged:
        raise ValidationError("manifest files list must not be empty")

    target = Path(destination).expanduser()
    _reject_symlink_ancestors(target)
    if target.exists() and target.is_symlink():
        raise ValidationError("destination must not be a symlink")
    if target.exists() and not target.is_dir():
        raise ValidationError("destination must be a directory path")
    parent = target.parent.resolve()
    if not parent.exists() or not parent.is_dir():
        raise ValidationError("destination parent must already exist")

    # Complete preflight happens before copying or making the destination.
    target_path = target.resolve() if target.exists() else parent / target.name
    existing_identical: List[str] = []
    to_copy: List[Tuple[Path, str, str]] = []
    if target.exists():
        for source, _, basename, source_hash, source_size in staged:
            destination_file = target_path / basename
            if destination_file.exists():
                if destination_file.is_symlink() or not destination_file.is_file():
                    raise ValidationError("destination collision is not a regular file: " + basename)
                if destination_file.stat().st_size != source_size or _sha256(destination_file) != source_hash:
                    raise ValidationError("destination has different existing file: " + basename)
                existing_identical.append(basename)
            else:
                to_copy.append((source, basename, source_hash))
    else:
        to_copy = [(source, basename, source_hash) for source, _, basename, source_hash, _ in staged]

    # Stage all bytes before any package outputs are made visible.  For a new
    # destination, renaming the completed staging directory is one operation.
    staging = Path(tempfile.mkdtemp(prefix=".editorial-package-", dir=str(parent)))
    try:
        for source, basename, source_hash in to_copy:
            staged_file = staging / basename
            shutil.copyfile(source, staged_file)
            if _sha256(staged_file) != source_hash:
                raise HashDriftError("source changed while packaging: " + basename)
        if not target.exists():
            os.replace(staging, target_path)
            staging = None  # type: ignore[assignment]
        else:
            for _, basename, _ in to_copy:
                os.replace(staging / basename, target_path / basename)
        return {
            "destination": str(target_path),
            "files": [basename for _, _, basename, _, _ in staged],
            "copied": [basename for _, basename, _ in to_copy],
            "existing_identical": existing_identical,
            "hashes": {basename: source_hash for _, _, basename, source_hash, _ in staged},
        }
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def _add_expected_revision(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-revision", type=int, help="refuse if the current state revision differs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create plugin-owned state only when absent")
    init.add_argument("--project", required=True)

    status = commands.add_parser("status", help="read state or bounded non-migration inspection")
    status.add_argument("--project", required=True)

    stage = commands.add_parser("set-stage", help="set a bounded editorial stage")
    stage.add_argument("--project", required=True)
    stage.add_argument("--stage", required=True, choices=STAGES)
    stage.add_argument("--quote")
    stage.add_argument("--post-id")
    stage.add_argument("--platform")
    stage.add_argument("--published-at")
    _add_expected_revision(stage)

    lock = commands.add_parser("lock", help="lock a project-local asset hash")
    lock.add_argument("--project", required=True)
    lock.add_argument("--key", required=True)
    lock.add_argument("--file", required=True)
    _add_expected_revision(lock)

    approve = commands.add_parser("approve", help="record immutable approval for a locked asset hash")
    approve.add_argument("--project", required=True)
    approve.add_argument("--key", required=True)
    approve.add_argument("--quote", required=True)
    _add_expected_revision(approve)

    verify = commands.add_parser("verify", help="verify a locked asset hash (approval required by default)")
    verify.add_argument("--project", required=True)
    verify.add_argument("--key", required=True)
    verify.add_argument(
        "--hash-only",
        action="store_true",
        help="verify only the locked hash; does not claim a user approval",
    )

    override = commands.add_parser("override", help="set a project-local creative override")
    override.add_argument("--project", required=True)
    override.add_argument("--scope", required=True, choices=("project", "revision"))
    override.add_argument("--key", required=True)
    override.add_argument("--value", required=True)
    override.add_argument("--quote", required=True)
    override.add_argument("--revision-id")
    _add_expected_revision(override)

    plan = commands.add_parser("plan-change", help="report the smallest affected handoff set")
    plan.add_argument("--domain", required=True, choices=tuple(CHANGE_IMPACTS))

    package = commands.add_parser("package", help="copy explicitly listed project files flat")
    package.add_argument("--project", required=True)
    package.add_argument("--manifest", required=True)
    package.add_argument("--destination", required=True)
    return parser


def run(arguments: Optional[List[str]] = None) -> Dict[str, Any]:
    args = build_parser().parse_args(arguments)
    if args.command == "init":
        state, created = initialize_project(args.project)
        return {"created": created, "state": state}
    if args.command == "status":
        return read_status(args.project)
    if args.command == "set-stage":
        return set_stage(
            args.project,
            args.stage,
            args.quote,
            args.post_id,
            args.platform,
            args.published_at,
            args.expected_revision,
        )
    if args.command == "lock":
        return lock_asset(args.project, args.key, args.file, args.expected_revision)
    if args.command == "approve":
        return approve_asset(args.project, args.key, args.quote, args.expected_revision)
    if args.command == "verify":
        return verify_asset(args.project, args.key, require_approval=not args.hash_only)
    if args.command == "override":
        return set_override(
            args.project,
            args.scope,
            args.key,
            args.value,
            args.quote,
            args.expected_revision,
            args.revision_id,
        )
    if args.command == "plan-change":
        return plan_change(args.domain)
    if args.command == "package":
        return package_files(args.project, args.manifest, args.destination)
    raise AssertionError("unreachable command")


def main(arguments: Optional[List[str]] = None) -> int:
    try:
        print(_json_dump(run(arguments)), end="")
        return 0
    except StateError as exc:
        print(_json_dump({"error": str(exc), "type": type(exc).__name__}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
