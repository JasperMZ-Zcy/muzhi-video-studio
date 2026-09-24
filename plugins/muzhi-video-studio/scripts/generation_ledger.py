#!/usr/bin/env python3
"""Local, pre-provider cost safeguards for a single editorial project.

This script records a plan, a reservation, an externally returned provider job
identifier, and a manually reported result.  It deliberately makes no network
request, never invokes a provider, and cannot charge an account.  It is a
voluntary execution ledger, not a provider-side billing or job-control system.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
ARTIFACTS_DIR = "artifacts"
LEDGER_FILENAME = "generation-ledger.json"
LOCK_FILENAME = ".generation-ledger.lock"
KINDS = ("asr", "image", "video", "music", "render")
UNITS = ("credits", "usd", "rmb", "none")
ACTIVE_STATES = {"reserved", "pending", "unknown"}
TERMINAL_STATES = {"succeeded", "failed"}
DEFAULT_MAX_OUTSTANDING = 2


class LedgerError(RuntimeError):
    """Base class for user-actionable ledger errors."""


class ValidationError(LedgerError):
    pass


class RevisionConflict(LedgerError):
    pass


class HashDriftError(LedgerError):
    pass


class BudgetError(LedgerError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValidationError(label + " must be a nonnegative number")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(label + " must be a nonnegative number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValidationError(label + " must be a nonnegative number")
    return parsed


def _cost_text(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _text(value: Any, label: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(label + " must not be empty")
    result = value.strip()
    if len(result) > maximum:
        raise ValidationError(label + " is too long")
    return result


def _project_dir(project: str | Path) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValidationError("--project must be an existing directory")
    return root


def _state_dir(project: str | Path) -> Path:
    directory = _project_dir(project) / ARTIFACTS_DIR
    if directory.is_symlink():
        raise ValidationError("artifacts directory must not be a symlink")
    if directory.exists() and not directory.is_dir():
        raise ValidationError("artifacts path must be a directory")
    return directory


def _ledger_path(project: str | Path) -> Path:
    return _state_dir(project) / LEDGER_FILENAME


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_regular_file(project: str | Path, supplied: str | Path, label: str) -> Tuple[Path, str]:
    """Resolve a named project-relative regular file without traversing links."""
    root = _project_dir(project)
    if not isinstance(supplied, (str, Path)):
        raise ValidationError(label + " must be a project-relative path")
    relative = Path(supplied)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValidationError(label + " must be a safe project-relative path")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValidationError(label + " must not traverse a symlink")
    if not cursor.exists() or not cursor.is_file():
        raise ValidationError(label + " must be an existing regular file")
    try:
        resolved = cursor.resolve(strict=True)
        relative_text = resolved.relative_to(root).as_posix()
    except (FileNotFoundError, ValueError) as exc:
        raise ValidationError(label + " must resolve inside --project") from exc
    return resolved, relative_text


def _new_ledger() -> Dict[str, Any]:
    created = _now()
    return {
        "schema": SCHEMA_VERSION,
        "revision": 0,
        "created_at": created,
        "updated_at": created,
        "cost_unit": None,
        "entries": [],
    }


def _validate_entry(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValidationError("ledger entry must be an object")
    required_text = ("id", "fingerprint", "dedupe_fingerprint", "kind", "key", "provider", "model", "unit", "state")
    for key in required_text:
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise ValidationError("ledger entry is missing " + key)
    if entry["kind"] not in KINDS or entry["unit"] not in UNITS:
        raise ValidationError("ledger entry has an invalid kind or unit")
    if entry["state"] not in ACTIVE_STATES | TERMINAL_STATES:
        raise ValidationError("ledger entry has an invalid state")
    if not isinstance(entry.get("inputs"), list) or not entry["inputs"]:
        raise ValidationError("ledger entry is missing inputs")
    for input_record in entry["inputs"]:
        if not isinstance(input_record, dict) or not isinstance(input_record.get("path"), str) or not isinstance(input_record.get("sha256"), str):
            raise ValidationError("ledger entry has malformed inputs")
    _decimal(entry.get("estimated_cost"), "ledger estimated_cost")
    actual = entry.get("actual_cost")
    if actual is not None:
        _decimal(actual, "ledger actual_cost")
    return entry


def _validate_ledger(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA_VERSION:
        raise ValidationError("unsupported generation ledger")
    if not isinstance(value.get("revision"), int) or value["revision"] < 0:
        raise ValidationError("generation ledger has an invalid revision")
    if value.get("cost_unit") not in {None, "credits", "usd", "rmb"}:
        raise ValidationError("generation ledger has an invalid cost unit")
    if not isinstance(value.get("entries"), list):
        raise ValidationError("generation ledger is missing entries")
    for entry in value["entries"]:
        _validate_entry(entry)
    return value


def _read_ledger(path: Path, allow_absent: bool = False) -> Tuple[Dict[str, Any], bool]:
    if not path.exists():
        if allow_absent:
            return _new_ledger(), False
        raise ValidationError("generation ledger does not exist; reserve first")
    try:
        with path.open("r", encoding="utf-8") as stream:
            return _validate_ledger(json.load(stream)), True
    except json.JSONDecodeError as exc:
        raise ValidationError("generation ledger is not valid JSON") from exc


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".generation-ledger-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json_dump(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _exclusive_lock(directory: Path, timeout_seconds: float = 3.0) -> Iterator[None]:
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
                if time.time() - lock.stat().st_mtime > 15 * 60:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RevisionConflict("another local ledger update is still in progress")
            time.sleep(0.04)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _check_expected_revision(ledger: Mapping[str, Any], expected_revision: Optional[int]) -> None:
    if expected_revision is not None and ledger["revision"] != expected_revision:
        raise RevisionConflict(
            "ledger revision changed (expected {0}, current {1})".format(expected_revision, ledger["revision"])
        )


def _mutate(
    project: str | Path,
    expected_revision: Optional[int],
    change: Callable[[Dict[str, Any]], Tuple[bool, Dict[str, Any]]],
) -> Dict[str, Any]:
    directory = _state_dir(project)
    path = directory / LEDGER_FILENAME
    with _exclusive_lock(directory):
        ledger, _ = _read_ledger(path, allow_absent=True)
        _check_expected_revision(ledger, expected_revision)
        changed, result = change(ledger)
        if changed:
            ledger["revision"] += 1
            ledger["updated_at"] = _now()
            _atomic_write(path, ledger)
        response = dict(result)
        response["ledger"] = ledger
        response["changed"] = changed
        return response


def _input_records(project: str | Path, files: Sequence[str]) -> List[Dict[str, str]]:
    if not files:
        raise ValidationError("at least one --input-file is required")
    records: List[Dict[str, str]] = []
    seen_paths: set[str] = set()
    for value in files:
        path, relative = _relative_regular_file(project, value, "--input-file")
        if relative.casefold() in seen_paths:
            raise ValidationError("duplicate --input-file")
        seen_paths.add(relative.casefold())
        records.append({"path": relative, "sha256": _sha256(path)})
    return records


def _fingerprint(
    kind: str,
    key: str,
    inputs: Sequence[Mapping[str, str]],
    provider: str,
    model: str,
    include_key: bool,
    include_provider_model: bool = True,
) -> str:
    payload: Dict[str, Any] = {
        "kind": kind,
        "inputs": sorted(item["sha256"] for item in inputs),
    }
    if include_provider_model:
        payload["provider"] = provider.casefold()
        payload["model"] = model.casefold()
    if include_key:
        payload["key"] = key
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _request(
    project: str | Path,
    kind: str,
    key: str,
    input_files: Sequence[str],
    provider: str,
    model: str,
    estimated_cost: Any,
    budget: Any,
    unit: str,
    quote: Optional[str] = None,
    require_quote: bool = False,
) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ValidationError("invalid --kind")
    semantic_key = _text(key, "--key")
    provider_name = _text(provider, "--provider")
    model_name = _text(model, "--model")
    if unit not in UNITS:
        raise ValidationError("invalid --unit")
    estimate = _decimal(estimated_cost, "--estimated-cost")
    if estimate > 0 and unit == "none":
        raise ValidationError("--unit must be credits, usd, or rmb when --estimated-cost is positive")
    if unit == "none" and estimate != 0:
        raise ValidationError("--unit none requires a zero --estimated-cost")
    if budget is None and estimate > 0:
        raise ValidationError("--budget is required when --estimated-cost is positive")
    budget_value = _decimal(budget, "--budget") if budget is not None else None
    if unit == "none" and budget_value not in {None, Decimal("0")}:
        raise ValidationError("--unit none requires a zero --budget")
    if require_quote:
        _text(quote, "--quote", maximum=4000)
    inputs = _input_records(project, input_files)
    fingerprint = _fingerprint(kind, semantic_key, inputs, provider_name, model_name, include_key=True)
    # A completed formal ASR is reusable per source-audio hash even if a later
    # caller gives that transcript another semantic key or a different provider
    # label.  A changed audio hash deliberately creates a new ASR fingerprint.
    dedupe_fingerprint = _fingerprint(
        kind,
        semantic_key,
        inputs,
        provider_name,
        model_name,
        include_key=kind != "asr",
        include_provider_model=kind != "asr",
    )
    return {
        "kind": kind,
        "key": semantic_key,
        "inputs": inputs,
        "provider": provider_name,
        "model": model_name,
        "estimated_cost": estimate,
        "budget": budget_value,
        "unit": unit,
        "quote": quote.strip() if isinstance(quote, str) else None,
        "fingerprint": fingerprint,
        "dedupe_fingerprint": dedupe_fingerprint,
    }


def _entry_cost(entry: Mapping[str, Any]) -> Decimal:
    actual = entry.get("actual_cost")
    return _decimal(actual, "ledger actual_cost") if actual is not None else _decimal(entry.get("estimated_cost"), "ledger estimated_cost")


def _cost_summary(ledger: Mapping[str, Any], unit: str) -> Dict[str, str]:
    actual_known = Decimal("0")
    estimated_for_unknown = Decimal("0")
    for entry in ledger["entries"]:
        if entry["unit"] != unit:
            continue
        if entry.get("actual_cost") is None:
            estimated_for_unknown += _decimal(entry["estimated_cost"], "ledger estimated_cost")
        else:
            actual_known += _decimal(entry["actual_cost"], "ledger actual_cost")
    return {
        "unit": unit,
        "actual_known": _cost_text(actual_known),
        "estimated_for_unknown": _cost_text(estimated_for_unknown),
        "committed": _cost_text(actual_known + estimated_for_unknown),
    }


def _enforce_project_unit(ledger: Dict[str, Any], request: Mapping[str, Any], mutate: bool) -> None:
    unit = request["unit"]
    estimate: Decimal = request["estimated_cost"]
    established = ledger.get("cost_unit")
    if estimate > 0:
        if established is not None and established != unit:
            raise BudgetError("--unit must match this project's existing monetary ledger unit")
        if mutate and established is None:
            ledger["cost_unit"] = unit
    elif established is not None and unit not in {"none", established}:
        raise BudgetError("--unit must match this project's existing monetary ledger unit")


def _budget_assessment(ledger: Mapping[str, Any], request: Mapping[str, Any]) -> Dict[str, Any]:
    estimate: Decimal = request["estimated_cost"]
    budget: Optional[Decimal] = request["budget"]
    unit: str = request["unit"]
    if estimate == 0:
        return {"required": False, "allowed": True, "summary": _cost_summary(ledger, unit)}
    if budget is None:
        raise ValidationError("--budget is required when --estimated-cost is positive")
    summary = _cost_summary(ledger, unit)
    proposed = _decimal(summary["committed"], "ledger committed") + estimate
    return {
        "required": True,
        "allowed": proposed <= budget,
        "summary": summary,
        "budget": _cost_text(budget),
        "proposed_committed": _cost_text(proposed),
    }


def _max_outstanding(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("--max-outstanding must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("--max-outstanding must be a positive integer") from exc
    if parsed < 1 or str(value).strip() != str(parsed):
        raise ValidationError("--max-outstanding must be a positive integer")
    return parsed


def _outstanding_assessment(ledger: Mapping[str, Any], maximum: int) -> Dict[str, Any]:
    outstanding = sum(1 for entry in ledger["entries"] if entry["state"] in ACTIVE_STATES)
    return {
        "outstanding": outstanding,
        "max_outstanding": maximum,
        "allowed": outstanding < maximum,
    }


def _entry_output_valid(project: str | Path, entry: Mapping[str, Any]) -> bool:
    output = entry.get("output")
    if not isinstance(output, dict) or not isinstance(output.get("path"), str) or not isinstance(output.get("sha256"), str):
        return False
    try:
        path, _ = _relative_regular_file(project, output["path"], "recorded output")
    except ValidationError:
        return False
    return _sha256(path) == output["sha256"]


def _matching_entries(ledger: Mapping[str, Any], request: Mapping[str, Any]) -> List[Dict[str, Any]]:
    target = request["dedupe_fingerprint"] if request["kind"] == "asr" else request["fingerprint"]
    return [entry for entry in ledger["entries"] if entry.get("dedupe_fingerprint" if request["kind"] == "asr" else "fingerprint") == target]


def _classify(project: str | Path, ledger: Mapping[str, Any], request: Mapping[str, Any]) -> Dict[str, Any]:
    matches = _matching_entries(ledger, request)
    if not matches:
        return {"action": "new", "entry": None}
    latest = matches[-1]
    if latest["state"] == "succeeded":
        if _entry_output_valid(project, latest):
            return {"action": "reuse", "entry": latest}
        return {"action": "output_drift", "entry": latest}
    if latest["state"] in {"pending", "unknown"} and latest.get("provider_job_id"):
        return {"action": "resume", "entry": latest}
    if latest["state"] == "reserved":
        return {"action": "reserved_existing", "entry": latest}
    if latest["state"] == "failed":
        return {"action": "retry_required", "entry": latest}
    return {"action": "resume", "entry": latest}


def _public_entry(entry: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if entry is None:
        return None
    fields = ("id", "kind", "key", "state", "provider_job_id", "estimated_cost", "actual_cost", "unit", "fingerprint", "dedupe_fingerprint")
    return {field: entry.get(field) for field in fields}


def plan(
    project: str | Path,
    kind: str,
    key: str,
    input_files: Sequence[str],
    provider: str,
    model: str,
    estimated_cost: Any,
    budget: Any,
    unit: str,
    quote: Optional[str] = None,
    max_outstanding: Any = DEFAULT_MAX_OUTSTANDING,
) -> Dict[str, Any]:
    request = _request(project, kind, key, input_files, provider, model, estimated_cost, budget, unit, quote)
    maximum = _max_outstanding(max_outstanding)
    ledger, exists = _read_ledger(_ledger_path(project), allow_absent=True)
    _enforce_project_unit(ledger, request, mutate=False)
    classification = _classify(project, ledger, request)
    assessment = _budget_assessment(ledger, request)
    return {
        "ledger_exists": exists,
        "action": classification["action"],
        "matching_entry": _public_entry(classification["entry"]),
        "fingerprint": request["fingerprint"],
        "dedupe_fingerprint": request["dedupe_fingerprint"],
        "budget": assessment,
        "outstanding": _outstanding_assessment(ledger, maximum),
        "note": "This is a local planning result only; no provider request or charge was made.",
    }


def reserve(
    project: str | Path,
    kind: str,
    key: str,
    input_files: Sequence[str],
    provider: str,
    model: str,
    estimated_cost: Any,
    budget: Any,
    unit: str,
    quote: str,
    retry_quote: Optional[str] = None,
    expected_revision: Optional[int] = None,
    max_outstanding: Any = DEFAULT_MAX_OUTSTANDING,
) -> Dict[str, Any]:
    request = _request(project, kind, key, input_files, provider, model, estimated_cost, budget, unit, quote, require_quote=True)
    maximum = _max_outstanding(max_outstanding)

    def change(ledger: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        _enforce_project_unit(ledger, request, mutate=False)
        classification = _classify(project, ledger, request)
        action = classification["action"]
        existing = classification["entry"]
        if action in {"reuse", "resume", "reserved_existing"}:
            return False, {
                "action": action,
                "reservation": _public_entry(existing),
                "note": "No additional reservation was created.",
            }
        retry_text: Optional[str] = None
        if action == "output_drift" and not (retry_quote or "").strip():
            raise HashDriftError("recorded successful output changed; reuse is rejected and an explicit --retry-quote is required")
        if action in {"retry_required", "output_drift"}:
            retry_text = _text(retry_quote, "--retry-quote", maximum=4000)
        elif retry_quote is not None:
            raise ValidationError("--retry-quote is only allowed after a matching failed or drifted reservation")
        assessment = _budget_assessment(ledger, request)
        if not assessment["allowed"]:
            raise BudgetError(
                "budget refusal: proposed committed {0} {1} exceeds budget {2}".format(
                    assessment["proposed_committed"], request["unit"], assessment["budget"]
                )
            )
        outstanding = _outstanding_assessment(ledger, maximum)
        if not outstanding["allowed"]:
            raise BudgetError(
                "outstanding reservation limit reached: {0} active reservations (maximum {1})".format(
                    outstanding["outstanding"], outstanding["max_outstanding"]
                )
            )
        _enforce_project_unit(ledger, request, mutate=True)
        entry: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "fingerprint": request["fingerprint"],
            "dedupe_fingerprint": request["dedupe_fingerprint"],
            "kind": request["kind"],
            "key": request["key"],
            "inputs": request["inputs"],
            "provider": request["provider"],
            "model": request["model"],
            "estimated_cost": _cost_text(request["estimated_cost"]),
            "actual_cost": None,
            "unit": request["unit"],
            "state": "reserved",
            "quote": request["quote"],
            "retry_quote": retry_text,
            "retry_of": existing["id"] if existing is not None else None,
            "provider_job_id": None,
            "output": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        ledger["entries"].append(entry)
        return True, {
            "action": "retry_reserved" if retry_text else "reserved",
            "reservation": _public_entry(entry),
            "budget": assessment,
            "outstanding": outstanding,
            "note": "Reservation recorded locally only; no provider request or charge was made.",
        }

    return _mutate(project, expected_revision, change)


def _find_entry(ledger: Mapping[str, Any], reservation_id: str) -> Dict[str, Any]:
    target = _text(reservation_id, "--reservation-id")
    for entry in ledger["entries"]:
        if entry["id"] == target:
            return entry
    raise ValidationError("reservation id was not found in this project")


def attach(
    project: str | Path,
    reservation_id: str,
    provider_job_id: str,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    job_id = _text(provider_job_id, "--provider-job-id", maximum=500)

    def change(ledger: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        entry = _find_entry(ledger, reservation_id)
        if entry["state"] == "reserved":
            entry["state"] = "pending"
            entry["provider_job_id"] = job_id
            entry["updated_at"] = _now()
            return True, {"action": "attached", "reservation": _public_entry(entry)}
        if entry["state"] in {"pending", "unknown"} and entry.get("provider_job_id") == job_id:
            return False, {"action": "attached_existing", "reservation": _public_entry(entry)}
        if entry["state"] in {"pending", "unknown"}:
            raise ValidationError("reservation already has a different provider job id")
        raise ValidationError("only a reserved or unresolved reservation can be attached")

    return _mutate(project, expected_revision, change)


def finish(
    project: str | Path,
    reservation_id: str,
    status: str,
    output_file: Optional[str] = None,
    actual_cost: Any = None,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    if status not in {"succeeded", "failed", "unknown"}:
        raise ValidationError("--status must be succeeded, failed, or unknown")
    output: Optional[Dict[str, str]] = None
    if status == "succeeded":
        if output_file is None:
            raise ValidationError("--output-file is required when --status succeeded")
        path, relative = _relative_regular_file(project, output_file, "--output-file")
        output = {"path": relative, "sha256": _sha256(path)}
    elif output_file is not None:
        raise ValidationError("--output-file is only allowed when --status succeeded")
    actual = _decimal(actual_cost, "--actual-cost") if actual_cost is not None else None

    def change(ledger: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        entry = _find_entry(ledger, reservation_id)
        if entry["unit"] == "none" and actual not in {None, Decimal("0")}:
            raise ValidationError("a no-cost reservation cannot finish with a positive actual cost")
        if entry["state"] in TERMINAL_STATES:
            if entry["state"] == status and entry.get("actual_cost") == (None if actual is None else _cost_text(actual)):
                if status != "succeeded" or entry.get("output") == output:
                    return False, {"action": "finish_existing", "reservation": _public_entry(entry)}
            raise ValidationError("reservation is already finished with different facts")
        if entry["state"] not in {"pending", "unknown"} or not entry.get("provider_job_id"):
            raise ValidationError("attach an externally returned provider job id before finishing")
        entry["state"] = status
        entry["actual_cost"] = None if actual is None else _cost_text(actual)
        entry["output"] = output
        entry["finished_at"] = _now()
        entry["updated_at"] = _now()
        return True, {"action": "finished", "reservation": _public_entry(entry)}

    return _mutate(project, expected_revision, change)


def status(project: str | Path) -> Dict[str, Any]:
    ledger, exists = _read_ledger(_ledger_path(project), allow_absent=True)
    unit = ledger.get("cost_unit") or "none"
    return {
        "ledger_exists": exists,
        "revision": ledger["revision"],
        "costs": _cost_summary(ledger, unit),
        "entries": [_public_entry(entry) for entry in ledger["entries"]],
        "note": "Local ledger only; it neither submits provider work nor verifies provider billing.",
    }


def _add_request_arguments(parser: argparse.ArgumentParser, require_quote: bool) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--key", required=True, help="semantic identifier for this requested output")
    parser.add_argument("--input-file", required=True, action="append", help="project-relative input file; repeat for multiple inputs")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--estimated-cost", required=True)
    parser.add_argument("--budget", help="total project budget in --unit; required when estimated cost is positive")
    parser.add_argument("--unit", required=True, choices=UNITS)
    parser.add_argument("--quote", required=require_quote, help="actual user authorization quote for a reservation")
    parser.add_argument(
        "--max-outstanding",
        default=DEFAULT_MAX_OUTSTANDING,
        help="maximum active local reservations; defaults to 2",
    )


def _add_expected_revision(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-revision", type=int, help="refuse if the ledger revision differs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    plan_parser = commands.add_parser("plan", help="read-only cost and reuse assessment; no provider call")
    _add_request_arguments(plan_parser, require_quote=False)

    reserve_parser = commands.add_parser("reserve", help="record a local pre-provider reservation; no provider call")
    _add_request_arguments(reserve_parser, require_quote=True)
    reserve_parser.add_argument("--retry-quote", help="explicit approval required to retry a matching failed reservation")
    _add_expected_revision(reserve_parser)

    attach_parser = commands.add_parser("attach", help="record an externally returned provider job id; no provider call")
    attach_parser.add_argument("--project", required=True)
    attach_parser.add_argument("--reservation-id", required=True)
    attach_parser.add_argument("--provider-job-id", required=True)
    _add_expected_revision(attach_parser)

    finish_parser = commands.add_parser("finish", help="record an externally observed result; no provider call")
    finish_parser.add_argument("--project", required=True)
    finish_parser.add_argument("--reservation-id", required=True)
    finish_parser.add_argument("--status", required=True, choices=("succeeded", "failed", "unknown"))
    finish_parser.add_argument("--output-file", help="project-relative output file; required for succeeded")
    finish_parser.add_argument("--actual-cost", help="optional known final cost; omitted remains unknown")
    _add_expected_revision(finish_parser)

    status_parser = commands.add_parser("status", help="read the local ledger; no provider call")
    status_parser.add_argument("--project", required=True)
    return parser


def run(arguments: Optional[List[str]] = None) -> Dict[str, Any]:
    args = build_parser().parse_args(arguments)
    if args.command == "plan":
        return plan(
            args.project,
            args.kind,
            args.key,
            args.input_file,
            args.provider,
            args.model,
            args.estimated_cost,
            args.budget,
            args.unit,
            args.quote,
            args.max_outstanding,
        )
    if args.command == "reserve":
        return reserve(
            args.project,
            args.kind,
            args.key,
            args.input_file,
            args.provider,
            args.model,
            args.estimated_cost,
            args.budget,
            args.unit,
            args.quote,
            args.retry_quote,
            args.expected_revision,
            args.max_outstanding,
        )
    if args.command == "attach":
        return attach(args.project, args.reservation_id, args.provider_job_id, args.expected_revision)
    if args.command == "finish":
        return finish(args.project, args.reservation_id, args.status, args.output_file, args.actual_cost, args.expected_revision)
    if args.command == "status":
        return status(args.project)
    raise AssertionError("unreachable")


def main(arguments: Optional[List[str]] = None) -> int:
    try:
        print(_json_dump(run(arguments)), end="")
        return 0
    except LedgerError as exc:
        print(_json_dump({"error": str(exc), "type": type(exc).__name__}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
