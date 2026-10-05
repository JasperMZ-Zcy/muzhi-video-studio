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
    """No private sealed-project exception is distributed in the public plugin."""
    return False


def requires_visual_decision(project: str | Path, plan: dict[str, Any]) -> bool:
    """Public v2 plans require a concrete visual choice; verified v1 work retains its contract."""
    return isinstance(plan, dict) and plan.get("semantic_contract_version") == 2 and not verified_prior_v2_same_script(project, plan)
