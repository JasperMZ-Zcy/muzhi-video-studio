"""Fail-closed execution gate for the editorial magazine video pipeline.

The gate deliberately checks a small, current execution lock instead of trying
to reinterpret legacy project contracts.  It verifies declared files,
fingerprints, operation bindings and evidence records.  It cannot determine
whether a factual claim is true in the real world, or whether a person actually
watched or listened as recorded; those remain human responsibilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


VALID_OPERATIONS = frozenset(
    {
        "script",
        "plan",
        "animatic",
        "pilot",
        "batch_generate",
        "preview",
        "master",
        "release",
    }
)
RENDER_OPERATIONS = frozenset({"animatic", "pilot", "preview", "master"})

# These paths are produced by the execution wrapper itself.  They are not
# business inputs and would otherwise make an identical operation hash differ
# solely because its audit destination changed.  No other fields are ignored.
BINDING_IGNORED_TOP_LEVEL_KEYS = frozenset(
    {"execution_lock_path", "execution_audit_path", "execution_audit_output_path"}
)

EDITORIAL_PIPELINE = "editorial-magazine-explainer"
STATE_RELATIVE_PATH = Path("artifacts") / "editorial-execution.json"
SCOPE = (
    "Checks declared files, hashes, statuses and bindings only. It does not "
    "establish real-world factual truth or prove that a human actually watched "
    "or listened."
)


def sha256(path: Path) -> str:
    """Return the uppercase SHA-256 fingerprint of a regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_inputs_json(inputs: Mapping[str, Any]) -> str:
    """Return the one canonical representation used to bind an execution call.

    Only the three documented wrapper-audit fields are removed, and only from
    the top level.  Business fields nested inside the request are never silently
    stripped.  Values must already be JSON values; accepting arbitrary objects
    through ``default=str`` would make the binding ambiguous.
    """
    if not isinstance(inputs, Mapping):
        raise ValueError("execution inputs must be a JSON object")
    cleaned = {
        key: value
        for key, value in inputs.items()
        if key not in BINDING_IGNORED_TOP_LEVEL_KEYS
    }
    try:
        return json.dumps(
            cleaned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"execution inputs are not canonical JSON: {exc}") from exc


def canonical_inputs_sha256(inputs: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_inputs_json(inputs).encode("utf-8")).hexdigest().upper()


def _load_object(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: unreadable JSON at {path}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label}: JSON root must be an object")
        return None
    return value


def _resolve(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        candidate = Path(value)
        return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _same_path(left: Path | None, right: Path | None) -> bool:
    return left is not None and right is not None and left == right


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _check_record(
    root: Path,
    record: Any,
    label: str,
    errors: list[str],
    evidence: dict[str, Any],
) -> Path | None:
    """Verify one ``{path, sha256}`` reference and add it to diagnostics."""
    if not isinstance(record, Mapping):
        errors.append(f"{label}: expected a file record with path and sha256")
        return None
    path = _resolve(root, record.get("path"))
    expected = record.get("sha256")
    if path is None:
        errors.append(f"{label}: missing path")
        return None
    if not _valid_hash(expected):
        errors.append(f"{label}: sha256 must be a 64-character hex value")
        return None
    try:
        is_file = path.is_file()
    except OSError as exc:
        errors.append(f"{label}: could not inspect path {path}: {exc}")
        return None
    if not is_file:
        errors.append(f"{label}: missing file {path}")
        return None
    try:
        actual = sha256(path)
    except OSError as exc:
        errors.append(f"{label}: could not read file to calculate sha256: {exc}")
        return None
    if actual != expected.upper():
        errors.append(f"{label}: current file hash differs from its execution lock")
        return None
    evidence[label] = {"path": str(path), "sha256": actual}
    return path


def _skill_execution_revision(path: Path, errors: list[str]) -> str | None:
    """Read the portable Skill's front-matter revision without a YAML runtime."""
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        errors.append(f"pinned Skill file: cannot read version metadata: {exc}")
        return None
    if not source.startswith("---"):
        errors.append("pinned Skill file: front matter with metadata.execution_revision is required")
        return None
    parts = source.split("---", 2)
    if len(parts) < 3:
        errors.append("pinned Skill file: malformed front matter")
        return None
    match = re.search(r"(?m)^\s*execution_revision:\s*[\"']?([^\"'#\r\n]+)", parts[1])
    if match is None or not match.group(1).strip():
        errors.append("pinned Skill file: metadata.execution_revision is required")
        return None
    return match.group(1).strip()


def _required_lock(
    root: Path,
    locks: Mapping[str, Any],
    name: str,
    errors: list[str],
    evidence: dict[str, Any],
) -> Path | None:
    if name not in locks:
        errors.append(f"missing required lock: {name}")
        return None
    return _check_record(root, locks[name], f"lock {name}", errors, evidence)


def _check_forbidden_changes(
    root: Path,
    locks: Mapping[str, Any],
    errors: list[str],
    evidence: dict[str, Any],
) -> None:
    records = locks.get("forbidden_changes")
    if not isinstance(records, list) or not records:
        errors.append("missing required lock: forbidden_changes must list every file forbidden this operation")
        return
    for index, record in enumerate(records, start=1):
        _check_record(root, record, f"forbidden_changes[{index}]", errors, evidence)


def _check_operation_binding(
    root: Path,
    state: Mapping[str, Any],
    locks: Mapping[str, Any],
    operation: str,
    inputs: dict[str, Any] | None,
    errors: list[str],
    evidence: dict[str, Any],
) -> None:
    if not isinstance(inputs, dict):
        errors.append("execution inputs are required as the actual JSON parameter object")
        return
    declared = state.get("operation_binding")
    if not isinstance(declared, Mapping):
        errors.append("operation_binding is required to bind the approved call")
        return
    try:
        actual_inputs_hash = canonical_inputs_sha256(inputs)
    except ValueError as exc:
        errors.append(str(exc))
        return
    expected_inputs_hash = declared.get("inputs_sha256")
    if not _valid_hash(expected_inputs_hash):
        errors.append("operation_binding.inputs_sha256 must be a 64-character hex value")
    elif actual_inputs_hash != expected_inputs_hash.upper():
        errors.append("actual execution parameters differ from the approved operation binding")
    evidence["operation_inputs"] = {"sha256": actual_inputs_hash}

    supplied_operation = inputs.get("editorial_operation")
    if supplied_operation != operation:
        errors.append("inputs.editorial_operation must exactly match the requested operation")
    execution_kind = inputs.get("execution_kind")
    music_generation = operation == "animatic" and execution_kind == "music_generation"
    render_requested = execution_kind == "render" or inputs.get("render_requested") is True
    if render_requested and operation not in RENDER_OPERATIONS:
        errors.append("render execution is allowed only for animatic, pilot, preview or master")
    if execution_kind == "music_generation" and operation != "animatic":
        errors.append("music_generation is allowed only at the animatic stage before the full animatic exists")
    if operation == "animatic" and execution_kind is not None and execution_kind not in {"render", "music_generation"}:
        errors.append("animatic accepts execution_kind render or music_generation")
    if operation == "pilot" and execution_kind is not None and execution_kind not in {"render", "generation"}:
        errors.append("pilot accepts execution_kind render or generation")
    if operation in {"preview", "master"} and execution_kind is not None and execution_kind != "render":
        errors.append("preview and master must declare inputs.execution_kind as render")

    # Script and plan precede a renderable entry.  Every later operation binds
    # the actual entry source as well as the whole calling object.
    if operation in {"script", "plan"}:
        return

    # New BGM is generated before the full animatic exists.  Its real input is
    # the locked music brief, not a future FullFilm entry.  Bind it just as
    # tightly as a render entry, while deliberately not demanding generated
    # audio, a completed animatic or a composition file that cannot exist yet.
    if music_generation:
        locked_brief = _required_lock(root, locks, "music_brief", errors, evidence)
        bound_brief_path = _check_record(
            root, declared.get("generation_entry"), "operation binding music brief", errors, evidence
        )
        supplied_brief_path = _resolve(root, inputs.get("generation_entry_path"))
        if supplied_brief_path is None:
            errors.append("inputs.generation_entry_path is required for music_generation")
            return
        try:
            brief_is_file = supplied_brief_path.is_file()
        except OSError as exc:
            errors.append(f"inputs.generation_entry_path could not be inspected: {exc}")
            return
        if not brief_is_file:
            errors.append(f"inputs.generation_entry_path does not name an existing file: {supplied_brief_path}")
            return
        if not _same_path(supplied_brief_path, locked_brief):
            errors.append("inputs.generation_entry_path is not the currently locked music brief")
        if not _same_path(supplied_brief_path, bound_brief_path):
            errors.append("inputs.generation_entry_path is not the music brief bound to this approved operation")
        if locked_brief is not None and bound_brief_path is not None and not _same_path(locked_brief, bound_brief_path):
            errors.append("operation binding music brief differs from the current music brief lock")
        return

    locked_entry = _required_lock(root, locks, "entry", errors, evidence)
    bound_entry = declared.get("entry")
    bound_entry_path = _check_record(root, bound_entry, "operation binding entry", errors, evidence)
    supplied_entry_path = _resolve(root, inputs.get("entry_path"))
    if supplied_entry_path is None:
        errors.append("inputs.entry_path is required from animatic onward")
        return
    if not supplied_entry_path.is_file():
        errors.append(f"inputs.entry_path does not name an existing file: {supplied_entry_path}")
        return
    if not _same_path(supplied_entry_path, locked_entry):
        errors.append("inputs.entry_path is not the currently locked editorial entry")
    if not _same_path(supplied_entry_path, bound_entry_path):
        errors.append("inputs.entry_path is not the entry bound to this approved operation")
    if locked_entry is not None and bound_entry_path is not None and not _same_path(locked_entry, bound_entry_path):
        errors.append("operation binding entry differs from the current entry lock")


def _json_pointer(document: Any, pointer: Any, errors: list[str], label: str) -> dict[str, Any] | None:
    """Select one object from a shared JSON evidence file using RFC 6901 syntax."""
    if pointer is None:
        return document if isinstance(document, dict) else None
    if pointer == "":
        return document if isinstance(document, dict) else None
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        errors.append(f"{label}: json_pointer must be an RFC 6901 path beginning with /")
        return None
    current = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                errors.append(f"{label}: json_pointer does not exist: {pointer}")
                return None
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            errors.append(f"{label}: json_pointer does not resolve to an evidence item: {pointer}")
            return None
    if not isinstance(current, dict):
        errors.append(f"{label}: json_pointer must select an object")
        return None
    return current


def _check_full_program_record(
    report: Mapping[str, Any], label: str, errors: list[str], warnings: list[str]
) -> None:
    if report.get("coverage") != "full_program":
        errors.append(f"{label}: coverage must be full_program, not a sample or frame audit")
    for field in ("started_at", "completed_at"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            errors.append(f"{label}: {field} is required for a complete-program record")

    observer = report.get("observer")
    if observer is None and isinstance(report.get("human_observer"), str) and report["human_observer"].strip():
        observer = {
            "type": "human",
            "name": report["human_observer"],
            "tool": report.get("tool"),
            "method": report.get("method"),
        }
    if not isinstance(observer, Mapping):
        errors.append(f"{label}: observer must declare type, name and tool or method")
        return
    observer_type = observer.get("type")
    if observer_type not in {"human", "ai"}:
        errors.append(f"{label}: observer.type must be human or ai")
    if not isinstance(observer.get("name"), str) or not observer["name"].strip():
        errors.append(f"{label}: observer.name is required")
    has_method = any(
        isinstance(observer.get(field), str) and observer[field].strip() for field in ("tool", "method")
    )
    if not has_method:
        errors.append(f"{label}: observer must name the tool or method used")
    if observer_type == "ai":
        warnings.append(
            f"{label}: AI observer is recorded as AI; it does not prove a human continuous watch or listening experience."
        )


def _check_evidence_gate(
    root: Path,
    gates: Mapping[str, Any],
    name: str,
    errors: list[str],
    evidence: dict[str, Any],
    *,
    approval_required: bool,
    required_kind: str | tuple[str, ...] | None = None,
    full_program: bool = False,
    warnings: list[str] | None = None,
) -> tuple[Path | None, str | None]:
    """Verify a real report, its target and, where required, its approval.

    The execution state stores only references.  The report itself must say
    ``status: passed`` and point at the exact locked target.  The approval must
    say ``status: approved`` and name that same target SHA-256.
    """
    gate = gates.get(name)
    if not isinstance(gate, Mapping):
        errors.append(f"missing required evidence gate: {name}")
        return None, None
    report_path = _check_record(root, gate.get("report"), f"{name} report", errors, evidence)
    target_path = _check_record(root, gate.get("target"), f"{name} target", errors, evidence)
    target_hash = gate.get("target", {}).get("sha256") if isinstance(gate.get("target"), Mapping) else None
    if report_path is None or target_path is None or not _valid_hash(target_hash):
        return target_path, target_hash.upper() if isinstance(target_hash, str) else None
    report_document = _load_object(report_path, errors, f"{name} report")
    report_pointer = gate.get("report", {}).get("json_pointer") if isinstance(gate.get("report"), Mapping) else None
    report = _json_pointer(report_document, report_pointer, errors, f"{name} report") if report_document is not None else None
    if report is not None:
        if report.get("status") != "passed":
            errors.append(f"{name} report: status must be passed")
        report_target = report.get("target")
        report_target_path = _resolve(root, report_target.get("path")) if isinstance(report_target, Mapping) else None
        report_target_hash = report_target.get("sha256") if isinstance(report_target, Mapping) else None
        if (
            not _same_path(report_target_path, target_path)
            or not _valid_hash(report_target_hash)
            or report_target_hash.upper() != target_hash.upper()
        ):
            errors.append(f"{name} report: target path or hash does not match the execution lock")
        if required_kind is not None:
            required_kinds = (required_kind,) if isinstance(required_kind, str) else required_kind
            if report.get("kind") not in required_kinds:
                errors.append(f"{name} report: kind must be one of {', '.join(required_kinds)}")
        if full_program:
            _check_full_program_record(report, f"{name} report", errors, warnings if warnings is not None else [])
    if approval_required:
        approval_path = _check_record(root, gate.get("approval"), f"{name} approval", errors, evidence)
        if approval_path is not None:
            approval_document = _load_object(approval_path, errors, f"{name} approval")
            approval_pointer = gate.get("approval", {}).get("json_pointer") if isinstance(gate.get("approval"), Mapping) else None
            approval = (
                _json_pointer(approval_document, approval_pointer, errors, f"{name} approval")
                if approval_document is not None
                else None
            )
            if approval is not None:
                if approval.get("status") != "approved":
                    errors.append(f"{name} approval: status must be approved")
                approved_target_hash = approval.get("target_sha256")
                if not _valid_hash(approved_target_hash) or approved_target_hash.upper() != target_hash.upper():
                    errors.append(f"{name} approval: approved target hash differs from the report target")
                for field in ("source", "quote", "approved_at"):
                    if not isinstance(approval.get(field), str) or not approval[field].strip():
                        errors.append(f"{name} approval: {field} is required")
    return target_path, target_hash.upper()


def _check_facts(
    root: Path,
    state: Mapping[str, Any],
    errors: list[str],
    evidence: dict[str, Any],
    warnings: list[str],
) -> None:
    facts = state.get("facts")
    if not isinstance(facts, Mapping):
        errors.append("facts must explicitly declare whether official facts are required")
        return
    requires_official_facts = facts.get("requires_official_facts")
    if not isinstance(requires_official_facts, bool):
        errors.append("facts.requires_official_facts must be an explicit boolean")
        return
    if not requires_official_facts:
        if not isinstance(facts.get("scope_reason"), str) or not facts["scope_reason"].strip():
            errors.append("facts.scope_reason is required when official facts are not required this round")
        return
    warnings.append(
        "Official-fact validation checks declared provenance and status only; it cannot establish real-world truth."
    )
    claims = facts.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("requires_official_facts needs at least one claim record")
        return
    allowed_parent_kinds = {
        "official",
        "official_document",
        "official_directory",
        "official_parent_page",
        "official_school_page",
    }
    for index, claim in enumerate(claims, start=1):
        label = f"official claim {index}"
        if not isinstance(claim, Mapping):
            errors.append(f"{label}: claim must be an object")
            continue
        if claim.get("status") != "active":
            errors.append(f"{label}: status must be active; deprecated, rejected or historical material cannot unlock production")
        year = claim.get("year")
        if not isinstance(year, int) or year < 2000:
            errors.append(f"{label}: a current four-digit year is required")
        for field in ("institution", "college", "object"):
            if not isinstance(claim.get(field), str) or not claim[field].strip():
                errors.append(f"{label}: {field} is required")
        parent = claim.get("parent_page")
        if not isinstance(parent, Mapping):
            errors.append(f"{label}: current-year official parent_page is required")
        else:
            _check_record(root, parent, f"{label} parent_page", errors, evidence)
            parent_kind = parent.get("source_type", parent.get("kind"))
            if parent_kind not in allowed_parent_kinds:
                errors.append(f"{label}: parent_page must be an official parent page or directory, not a knowledge card")
            if parent.get("year") != year:
                errors.append(f"{label}: parent_page year must match claim year")
        original = claim.get("original")
        if not isinstance(original, Mapping):
            errors.append(f"{label}: original source file with hash and page is required")
        else:
            _check_record(root, original, f"{label} original", errors, evidence)
            if original.get("year") != year:
                errors.append(f"{label}: original source year must match claim year")
            page = original.get("page")
            if not isinstance(page, int) or page < 1:
                errors.append(f"{label}: original source needs a positive page number")
        review = claim.get("independent_review")
        if not isinstance(review, Mapping):
            errors.append(f"{label}: independent_review is required")
        else:
            for field in ("reviewer", "source"):
                if not isinstance(review.get(field), str) or not review[field].strip():
                    errors.append(f"{label}: independent_review.{field} is required")
        conflicts = claim.get("unresolved_conflicts")
        if not isinstance(conflicts, list):
            errors.append(f"{label}: unresolved_conflicts must be an explicit list")
        elif conflicts:
            errors.append(f"{label}: unresolved conflicts must be cleared before an external factual claim")


def _value_at(value: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _check_profile_policy_inheritance(
    root: Path,
    identity: Mapping[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    """Check policy values really inherit the approved brand profile.

    The existing identity gate verifies that a render is internally consistent.
    This smaller check closes a different gap: a policy and a live composition
    must not drift together away from the approved inherited profile.
    """
    profile_ref = identity.get("brand_profile")
    if not isinstance(profile_ref, Mapping):
        return  # The normal prerequisite already emitted the clear lock error.
    profile_path = _resolve(root, profile_ref.get("path"))
    if profile_path is None or not profile_path.is_file():
        return
    profile = _load_object(profile_path, errors, "approved brand profile")
    policy_path = root / "artifacts" / "editorial-render-policy.json"
    if not policy_path.is_file():
        errors.append("editorial-render-policy.json is required to verify inherited brand profile values")
        return
    policy = _load_object(policy_path, errors, "editorial-render-policy.json")
    if profile is None or policy is None:
        return
    if profile.get("status") not in {"approved", "approved_reference"}:
        errors.append("approved brand profile must have approved or approved_reference status")

    override = identity.get("profile_override")
    override_values: Mapping[str, Any] = {}
    override_fields: set[str] = set()
    if override is not None:
        if not isinstance(override, Mapping):
            errors.append("identity.profile_override must be an object when declared")
        else:
            approval = override.get("authorization")
            values = override.get("values")
            fields = override.get("fields")
            if not isinstance(approval, Mapping) or not all(
                isinstance(approval.get(field), str) and approval[field].strip()
                for field in ("source", "approved_at")
            ):
                errors.append("profile_override needs this-round authorization source and approved_at")
            if not isinstance(values, Mapping) or not isinstance(fields, list) or not all(
                isinstance(field, str) for field in fields
            ):
                errors.append("profile_override needs values and an explicit fields list")
            else:
                override_values = values
                override_fields = set(fields)

    def compare(field: str, approved: Any, active: Any) -> None:
        if approved == active:
            return
        overridden = field in override_fields and _value_at(override_values, field) == active
        if overridden:
            warnings.append(f"brand profile override applied for {field} under this-round authorization")
            return
        errors.append(
            f"editorial render policy {field} differs from the approved brand profile without an explicit current override"
        )

    compare("brand_id", profile.get("brand_id"), policy.get("brand_id"))
    profile_voice = profile.get("voice")
    policy_voice = policy.get("voice")
    if not isinstance(profile_voice, Mapping) or not isinstance(policy_voice, Mapping):
        errors.append("approved brand profile and render policy both need a voice object")
    else:
        compare("voice.profile_id", profile_voice.get("profile_id"), policy_voice.get("profile_id"))
        compare("voice.pitch", profile_voice.get("pitch"), policy_voice.get("pitch"))
        # The profile records tempo as a production invariant.  A policy may
        # omit it because the identity gate verifies tempo from the audio report;
        # if it declares one, it must inherit the profile exactly.
        if "tempo" in policy_voice:
            compare("voice.tempo", profile_voice.get("tempo"), policy_voice.get("tempo"))
    profile_caption = profile.get("caption_style")
    policy_caption = policy.get("caption_style")
    if not isinstance(profile_caption, Mapping) or not isinstance(policy_caption, Mapping):
        errors.append("approved brand profile and render policy both need caption_style")
    else:
        for key, approved_value in profile_caption.items():
            compare(f"caption_style.{key}", approved_value, policy_caption.get(key))
    compare("outro_strings", profile.get("outro_strings"), policy.get("outro_strings"))


def _operation_prerequisites(
    root: Path,
    operation: str,
    state: Mapping[str, Any],
    errors: list[str],
    evidence: dict[str, Any],
    warnings: list[str],
    *,
    music_generation: bool,
) -> None:
    locks = state.get("locks", {})
    identity = state.get("identity", {})
    gates = state.get("gates", {})
    if not isinstance(locks, Mapping):
        errors.append("locks must be an object")
        return
    if not isinstance(identity, Mapping):
        errors.append("identity must be an object")
        return
    if not isinstance(gates, Mapping):
        errors.append("gates must be an object")
        return

    # A current approved brand profile is enough while writing; a project design
    # is intentionally required only once animatics/production begin.
    _check_record(root, identity.get("brand_profile"), "approved brand profile", errors, evidence)
    if operation == "script":
        return
    for name in ("script", "evidence_bundle", "recording"):
        _required_lock(root, locks, name, errors, evidence)
    if operation == "plan":
        return
    if music_generation:
        _required_lock(root, locks, "music_brief", errors, evidence)
        _check_evidence_gate(root, gates, "storyboard", errors, evidence, approval_required=True)
        budget_authorization = state.get("authorization", {}).get("budget_authorization") if isinstance(state.get("authorization"), Mapping) else None
        if not isinstance(budget_authorization, Mapping):
            errors.append("authorization.budget_authorization is required for music_generation")
        else:
            for field in ("source", "quote", "approved_at"):
                if not isinstance(budget_authorization.get(field), str) or not budget_authorization[field].strip():
                    errors.append(f"authorization.budget_authorization.{field} is required for music_generation")
        return
    _check_record(root, identity.get("design"), "approved design", errors, evidence)
    _required_lock(root, locks, "subtitles", errors, evidence)
    _check_forbidden_changes(root, locks, errors, evidence)

    if operation == "animatic":
        return
    _check_evidence_gate(root, gates, "storyboard", errors, evidence, approval_required=True)
    _check_evidence_gate(root, gates, "animatic", errors, evidence, approval_required=True)
    if operation == "pilot":
        return
    _check_evidence_gate(root, gates, "pilot", errors, evidence, approval_required=True)
    if operation == "batch_generate":
        return
    _check_evidence_gate(root, gates, "batch_assets", errors, evidence, approval_required=False)
    _check_evidence_gate(root, gates, "dynamic_duration", errors, evidence, approval_required=False)
    if operation == "preview":
        _check_profile_policy_inheritance(root, identity, errors, warnings)
        return
    _check_evidence_gate(root, gates, "rough_cut", errors, evidence, approval_required=True)
    if operation == "master":
        _check_profile_policy_inheritance(root, identity, errors, warnings)
        return

    # Gate 3.5 needs actual final reports and separately recorded continuous
    # human viewing/listening.  Frame samples and machine probes cannot satisfy
    # these two human records because their required kinds differ.
    final_targets: list[tuple[Path | None, str | None]] = []
    final_targets.append(
        _check_evidence_gate(root, gates, "technical", errors, evidence, approval_required=False)
    )
    final_targets.append(
        _check_evidence_gate(
            root,
            gates,
            "visual",
            errors,
            evidence,
            approval_required=False,
            required_kind="final_visual_review",
            full_program=True,
            warnings=warnings,
        )
    )
    final_targets.append(
        _check_evidence_gate(
            root,
            gates,
            "continuous_viewing",
            errors,
            evidence,
            approval_required=False,
            required_kind=("continuous_dynamic_viewing", "human_continuous_viewing"),
            full_program=True,
            warnings=warnings,
        )
    )
    final_targets.append(
        _check_evidence_gate(
            root,
            gates,
            "full_listening",
            errors,
            evidence,
            approval_required=False,
            required_kind=("complete_audio_listening", "human_full_listening"),
            full_program=True,
            warnings=warnings,
        )
    )
    complete = [(path, fingerprint) for path, fingerprint in final_targets if path is not None and fingerprint]
    if len(complete) == 4 and len({(path, fingerprint) for path, fingerprint in complete}) != 1:
        errors.append("release evidence must all identify the same final target file and hash")


def check_editorial_execution(
    project_root: Path,
    operation: str,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check whether one editorial pipeline operation may proceed.

    Other pipeline types remain untouched.  An editorial project with no current
    ``artifacts/editorial-execution.json`` is deliberately blocked instead of
    treating legacy artifacts as implied approval.
    """
    root = Path(project_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {}
    state_path = root / STATE_RELATIVE_PATH
    project_path = root / "project.json"
    project: dict[str, Any] = {}
    project_invalid = False
    if project_path.is_file():
        loaded_project = _load_object(project_path, errors, "project.json")
        if loaded_project is not None:
            project = loaded_project
        else:
            project_invalid = True
    applies = (
        project.get("pipeline_type") == EDITORIAL_PIPELINE
        or project.get("pipeline") == EDITORIAL_PIPELINE
        or state_path.exists()
        or project_invalid
    )
    if not applies:
        return {
            "applicable": False,
            "passed": True,
            "errors": [],
            "warnings": [],
            "operation": operation,
            "state_path": str(state_path),
            "evidence": {},
            "scope": SCOPE,
        }

    if operation not in VALID_OPERATIONS:
        errors.append(
            "unsupported editorial operation; use one of " + ", ".join(sorted(VALID_OPERATIONS))
        )
    if not state_path.is_file():
        errors.append(
            "editorial-execution.json is required for future editorial work; legacy project evidence is not treated as approval"
        )
        return {
            "applicable": True,
            "passed": False,
            "errors": errors,
            "warnings": warnings,
            "operation": operation,
            "state_path": str(state_path),
            "evidence": evidence,
            "scope": SCOPE,
        }
    state = _load_object(state_path, errors, "editorial-execution.json")
    if state is None:
        return {
            "applicable": True,
            "passed": False,
            "errors": errors,
            "warnings": warnings,
            "operation": operation,
            "state_path": str(state_path),
            "evidence": evidence,
            "scope": SCOPE,
        }

    if state.get("schema_version") != "1.0":
        errors.append("unsupported editorial execution state schema")
    if state.get("pipeline_type") != EDITORIAL_PIPELINE:
        errors.append("execution state pipeline_type must be editorial-magazine-explainer")
    if state.get("operation") != operation:
        errors.append("requested operation differs from the operation declared in the current execution state")
    authorization = state.get("authorization")
    if not isinstance(authorization, Mapping):
        errors.append("authorization with this-round source is required")
    else:
        for field in ("source", "approved_at"):
            if not isinstance(authorization.get(field), str) or not authorization[field].strip():
                errors.append(f"authorization.{field} is required")
    skill_lock = state.get("skill_lock")
    skill_path = _check_record(root, skill_lock, "pinned Skill file", errors, evidence)
    if not isinstance(skill_lock, Mapping) or not isinstance(skill_lock.get("version"), str) or not skill_lock["version"].strip():
        errors.append("pinned Skill file must declare the actual Skill version")
    elif skill_path is not None:
        actual_revision = _skill_execution_revision(skill_path, errors)
        if actual_revision is not None and skill_lock["version"] != actual_revision:
            errors.append("pinned Skill file version differs from metadata.execution_revision")

    if operation in VALID_OPERATIONS:
        locks = state.get("locks") if isinstance(state.get("locks"), Mapping) else {}
        _check_operation_binding(root, state, locks, operation, inputs, errors, evidence)
        music_generation = (
            operation == "animatic"
            and isinstance(inputs, dict)
            and inputs.get("execution_kind") == "music_generation"
        )
        _operation_prerequisites(
            root,
            operation,
            state,
            errors,
            evidence,
            warnings,
            music_generation=music_generation,
        )
        _check_facts(root, state, errors, evidence, warnings)

    return {
        "applicable": True,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "operation": operation,
        "state_path": str(state_path),
        "evidence": evidence,
        "scope": SCOPE,
    }


def _read_cli_inputs(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.inputs is not None and args.inputs_file is not None:
        raise ValueError("use either --inputs or --inputs-file, not both")
    if args.inputs is None and args.inputs_file is None:
        return None
    payload = args.inputs if args.inputs is not None else Path(args.inputs_file).read_text(encoding="utf-8-sig")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("CLI inputs must decode to a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an editorial execution lock without rendering or generating media.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--operation", required=True, choices=sorted(VALID_OPERATIONS))
    parser.add_argument("--inputs", help="Actual invocation parameters as one JSON object")
    parser.add_argument("--inputs-file", type=Path, help="UTF-8 JSON file containing actual invocation parameters")
    args = parser.parse_args(argv)
    try:
        inputs = _read_cli_inputs(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    result = check_editorial_execution(args.project_root, args.operation, inputs)
    # Keep the CLI payload valid even when a Windows console uses a legacy code
    # page while project paths include Chinese characters.  The Python API still
    # returns ordinary Unicode strings.
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI.
    raise SystemExit(main())
