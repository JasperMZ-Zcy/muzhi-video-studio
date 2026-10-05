#!/usr/bin/env python3
"""Read-only, versioned evidence gate for a director storyboard.

This checks integrity and explicit review records, not whether a human actually
understood a film. It does not create a second shot plan or contact a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any

from project_policy import classify_project, requires_visual_decision


CONTRACT = "artifacts/director-storyboard.json"
STYLE_LOCK = "artifacts/video-studio-style.json"
DIMENSIONS = ("semantic", "visible_change", "library_mechanism", "readability", "style", "continuity")
ACTION_STATES = ("entry", "interaction", "result", "reading_hold", "exit")


def _digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def storyboard_digest(contract: dict[str, Any]) -> str:
    return _digest({key: value for key, value in contract.items() if key not in ("approval", "final_review")})


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _file(root: Path, relative: Any, sha: Any, label: str, errors: list[str]) -> Path | None:
    if not _text(relative) or not _text(sha) or len(sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha):
        errors.append(f"{label}: project-relative path and SHA-256 are required")
        return None
    rel = Path(relative)
    if rel.is_absolute() or any(part in (".", "..") for part in rel.parts):
        errors.append(f"{label}: unsafe path")
        return None
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            errors.append(f"{label}: symlink forbidden")
            return None
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        errors.append(f"{label}: file missing or outside project")
        return None
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha.lower():
        errors.append(f"{label}: SHA-256 drift")
        return None
    return path


def _json_file(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, dict):
            return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    errors.append(f"{label}: invalid JSON object")
    return None


def _evidence(root: Path, item: Any, label: str, errors: list[str]) -> None:
    if not isinstance(item, dict) or not _text(item.get("quote")):
        errors.append(f"{label}: actual user quote required")
        return
    path = _file(root, item.get("evidence_path"), item.get("evidence_sha256"), label + " evidence", errors)
    if path is not None and item["quote"] not in path.read_text(encoding="utf-8-sig", errors="replace"):
        errors.append(f"{label}: quote not found in bound evidence")


def _image(path: Path, label: str, errors: list[str]) -> None:
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(path) as frame:
                frame.verify()
            return
        except (OSError, ValueError):
            errors.append(f"{label}: image cannot be decoded")
            return
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        if width > 0 and height > 0:
            return
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10 and int.from_bytes(data[6:8], "little") > 0 and int.from_bytes(data[8:10], "little") > 0:
        return
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return
    errors.append(f"{label}: not a recognizable image; text or arbitrary bytes renamed as a frame are forbidden")


def _review(item: Any, label: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{label}: six review dimensions required")
        return
    for dimension in DIMENSIONS:
        value = item.get(dimension)
        if not isinstance(value, dict) or value.get("status") != "pass" or not _text(value.get("evidence")) or len(value["evidence"].strip()) < 12:
            errors.append(f"{label} {dimension}: explicit pass with concrete evidence required; pending/reject cannot pass")


def _independent_review(root: Path, contract: dict[str, Any], plan: dict[str, Any],
                        shots: list[Any], errors: list[str]) -> None:
    review = contract.get("independent_review")
    if not isinstance(review, dict) or review.get("reviewer_role") != "independent":
        errors.append("independent review: independent reviewer record required")
        return
    for key in ("source_script", "source_sha256", "motion_plan_source", "motion_plan_sha256"):
        if review.get(key) != contract.get(key):
            errors.append(f"independent review: {key} differs from current director contract")
    source = _file(root, review.get("source_script"), review.get("source_sha256"), "independent review script", errors)
    _file(root, review.get("motion_plan_source"), review.get("motion_plan_sha256"), "independent review plan", errors)
    source_text = source.read_text(encoding="utf-8-sig", errors="replace") if source else ""
    entries = review.get("segments")
    segments = plan.get("segments", [])
    if not isinstance(entries, list) or [entry.get("segment_id") for entry in entries if isinstance(entry, dict)] != [
            segment.get("id") for segment in segments if isinstance(segment, dict)]:
        errors.append("independent review: every current plan segment required in order")
        return
    by_shot = {shot.get("segment_id"): shot for shot in shots if isinstance(shot, dict)}
    for entry, segment in zip(entries, segments):
        if not isinstance(entry, dict) or not isinstance(segment, dict):
            continue
        sid = segment.get("id")
        label = f"independent review {sid}"
        if entry.get("status") != "pass" or any(not _text(entry.get(key)) for key in
                                                    ("source_quote", "original_intent", "observed_change", "evidence_scope")):
            errors.append(f"{label}: original intent, observed change, evidence scope and pass required")
        elif entry["source_quote"] not in source_text:
            errors.append(f"{label}: source quote not found in current script")
        shot = by_shot.get(sid, {})
        frames = shot.get("keyframes")
        frame_hashes = [frame.get("sha256") for frame in frames if isinstance(frame, dict)] if isinstance(frames, list) else []
        if not frame_hashes or entry.get("keyframe_sha256") != frame_hashes:
            errors.append(f"{label}: observation must bind current shot keyframes")
        media = segment.get("preview_binding", {}).get("preview_media") if isinstance(segment.get("preview_binding"), dict) else None
        if isinstance(media, dict) and entry.get("preview_media_sha256") != media.get("sha256"):
            errors.append(f"{label}: observation must bind current preview media")


def validate(project: str | Path, stage: str = "plan", contract_path: str = CONTRACT) -> dict[str, Any]:
    root = Path(project).resolve()
    errors: list[str] = []
    if not root.is_dir():
        return {"passed": False, "errors": ["project directory missing"], "quality_review_claimed": False}
    if stage not in ("plan", "batch", "master"):
        return {"passed": False, "errors": ["unknown stage"], "quality_review_claimed": False}
    identity = classify_project(root)
    required = identity["minimum_semantic_version"] == 2
    contract_file = root / contract_path
    if contract_file.is_symlink() or not contract_file.resolve().is_relative_to(root):
        errors.append("director contract: unsafe path")
        contract = None
    elif contract_file.is_file():
        contract = _json_file(contract_file, errors, "director contract")
    else:
        contract = None
    if contract is None:
        if required:
            errors.append("new project requires versioned director contract")
        return {"passed": not errors, "stage": stage, "legacy_not_certified": not required and not errors,
                "errors": errors, "quality_review_claimed": False}
    if contract.get("director_review_contract_version") != 1:
        errors.append("director_review_contract_version: unsupported or missing")
    plan = None
    for name, path_key, hash_key in (("script", "source_script", "source_sha256"),
                                     ("SRT", "srt_source", "srt_sha256"),
                                     ("design", "design_source", "design_sha256"),
                                     ("motion plan", "motion_plan_source", "motion_plan_sha256"),
                                     ("visual board", "board_path", "board_sha256")):
        path = _file(root, contract.get(path_key), contract.get(hash_key), name, errors)
        if name == "design" and contract.get(path_key) != "design.md":
            errors.append("design: must bind this project's design.md")
        if name == "motion plan":
            plan = _json_file(path, errors, name) if path else None
    digest = storyboard_digest(contract)
    strict_decision = isinstance(plan, dict) and requires_visual_decision(root, plan)
    if plan is not None:
        from motion_plan import validate as validate_motion_plan
        semantic_result = validate_motion_plan(plan, root, "storyboard")
        if not semantic_result["passed"]:
            errors.extend("motion plan semantic: " + item for item in semantic_result["errors"])
        if any(plan.get(key) != contract.get(key) for key in ("source_script", "source_sha256", "srt_source", "srt_sha256", "design_source", "design_sha256")):
            errors.append("director contract: script/SRT/design binding differs from motion plan")
        if plan.get("semantic_contract_version") not in (1, 2):
            errors.append("motion plan: semantic contract v1 or v2 required")
        if required and plan.get("semantic_contract_version") != 2:
            errors.append("new or unverified project requires semantic contract v2")
        segment_ids = [item.get("id") for item in plan.get("segments", []) if isinstance(item, dict)]
        if len(segment_ids) != len(set(segment_ids)) or not segment_ids:
            errors.append("motion plan: unique segments required")
        if plan.get("semantic_contract_version") == 2:
            from resource_handoff import verify_preview

            for segment_id in segment_ids:
                preview = verify_preview(root, plan, segment_id)
                errors.extend(f"v2 preview {segment_id}: " + issue for issue in preview["errors"])
    else:
        segment_ids = []
    kind = contract.get("timebase_kind")
    mode = contract.get("run_mode")
    if mode not in ("production", "automation_test"):
        errors.append("run_mode: production or automation_test required")
    if kind != "real_voice_srt":
        exception = contract.get("automation_test")
        if (mode != "automation_test" or kind != "authored_screen_timing" or not isinstance(exception, dict) or
                exception.get("project_id") != root.name or exception.get("kind") != "no_voice_test" or
                exception.get("scope") != "this_project_only" or not _text(exception.get("date"))):
            errors.append("formal production requires real_voice_srt; no-voice exception is project-bound")
        else:
            _evidence(root, exception, "automation test exception", errors)
    elif isinstance(plan, dict) and plan.get("timebase_kind") == "authored_screen_timing":
        errors.append("formal real_voice_srt cannot inherit authored_screen_timing plan")
    if kind == "real_voice_srt":
        _file(root, contract.get("voice_source"), contract.get("voice_sha256"), "real original voice", errors)
    shots = contract.get("shots")
    shot_ids: list[str] = []
    if not isinstance(shots, list) or not shots:
        errors.append("director contract: nonempty shots required")
        shots = []
    for index, shot in enumerate(shots):
        label = f"shot {index + 1}"
        if not isinstance(shot, dict):
            errors.append(f"{label}: object required")
            continue
        sid = shot.get("segment_id")
        if not _text(sid) or sid not in segment_ids:
            errors.append(f"{label}: must reference motion-plan segment ID")
        else:
            shot_ids.append(sid)
        frames = shot.get("keyframes")
        if not isinstance(frames, list) or not frames:
            errors.append(f"{label}: real keyframes required")
        else:
            roles = set()
            frame_hashes = set()
            for frame_index, frame in enumerate(frames):
                if not isinstance(frame, dict):
                    errors.append(f"{label} keyframe {frame_index + 1}: object required")
                    continue
                path = _file(root, frame.get("path"), frame.get("sha256"), f"{label} keyframe {frame_index + 1}", errors)
                if path is not None:
                    _image(path, f"{label} keyframe {frame_index + 1}", errors)
                if _text(frame.get("sha256")):
                    frame_hashes.add(frame["sha256"].lower())
                if not _text(frame.get("role")):
                    errors.append(f"{label} keyframe {frame_index + 1}: role required")
                if _text(frame.get("role")):
                    roles.add(frame["role"])
            route = next((item.get("visual_route") for item in plan.get("segments", []) if isinstance(item, dict) and item.get("id") == sid), None) if isinstance(plan, dict) else None
            if len(frame_hashes) < 2 and not (_text(shot.get("static_reading_reason")) and route in ("official_evidence", "sourced_chart", "real_media")):
                errors.append(f"{label}: changing relationship needs at least two distinct real keyframes; static reading needs a route-specific reason")
        route = next((item.get("visual_route") for item in plan.get("segments", []) if isinstance(item, dict) and item.get("id") == sid), None) if isinstance(plan, dict) else None
        static_reading = _text(shot.get("static_reading_reason")) and route in ("official_evidence", "sourced_chart", "real_media")
        action = shot.get("visual_action_check")
        if not isinstance(action, dict) or any(not _text(action.get(key)) for key in ACTION_STATES):
            errors.append(f"{label}: entry/interaction/result/reading_hold/exit required")
        elif not static_reading and len({action["entry"].strip(), action["interaction"].strip(), action["result"].strip()}) < 3:
            errors.append(f"{label}: entry/interaction/result must describe distinct visible states")
        if isinstance(plan, dict) and plan.get("semantic_contract_version") == 2 and sid in segment_ids:
            from expression_contract import cue_window, validate_evidence

            segment = next(item for item in plan["segments"] if isinstance(item, dict) and item.get("id") == sid)
            binding = segment.get("preview_binding")
            media = binding.get("preview_media") if isinstance(binding, dict) else None
            requirements = segment.get("expression_requirements", [])
            static_only = (isinstance(requirements, list) and bool(requirements) and
                           all(isinstance(item, dict) and item.get("proof_kind") == "static_reading" for item in requirements))
            if static_only and not static_reading:
                errors.append(f"{label}: static reading needs a permitted route and static_reading_reason")
            if not isinstance(media, dict) and not (static_only and static_reading and isinstance(binding, dict) and binding.get("static_reading") is True):
                errors.append(f"{label}: v2 actual preview media binding required for continuous obligations")
            if isinstance(media, dict):
                _file(root, media.get("path"), media.get("sha256"), f"{label} actual preview media", errors)
            windows = {}
            local_windows = {}
            segment_start = None
            if strict_decision:
                try:
                    segment_start = cue_window(root, plan, segment.get("srt_cue_ids"))[0]
                except (ValueError, OSError, UnicodeError) as exc:
                    errors.append(f"{label}: {exc}")
            for req in requirements if isinstance(requirements, list) else []:
                if isinstance(req, dict) and isinstance(req.get("id"), str) and (req.get("proof_kind") == "static_reading" or strict_decision):
                    try:
                        window = cue_window(root, plan, req.get("cue_ids"))
                        if req.get("proof_kind") == "static_reading":
                            windows[req["id"]] = window
                        if segment_start is not None:
                            local_windows[req["id"]] = (window[0] - segment_start, window[1] - segment_start)
                    except (ValueError, OSError, UnicodeError) as exc:
                        errors.append(f"{label}: {exc}")
            validate_evidence(requirements, action, frames if isinstance(frames, list) else [], media, errors, label,
                              cue_windows=windows, expected_domain="preview_local", local_cue_windows=local_windows,
                              strict_continuous=strict_decision,
                              static_time_domain="authored_global" if plan.get("timebase_kind") == "authored_screen_timing" else "srt_global")
        _review(shot.get("review"), label, errors)
    if shot_ids != segment_ids:
        errors.append("director contract: shots must cover each motion-plan segment once in order")
    if isinstance(plan, dict) and plan.get("semantic_contract_version") == 2:
        _independent_review(root, contract, plan, shots, errors)
    approval = contract.get("approval")
    if isinstance(approval, dict) and approval.get("status") == "rejected":
        errors.append("user explicitly rejected this storyboard")
    if stage != "plan":
        waiver = contract.get("automation_test")
        waived = (mode == "automation_test" and isinstance(waiver, dict) and waiver.get("board_approval_waived") is True and
                  waiver.get("project_id") == root.name and waiver.get("scope") == "this_project_only" and
                  _text(waiver.get("date")) and _text(waiver.get("board_approval_quote")))
        if not isinstance(approval, dict) or approval.get("status") != "approved" or approval.get("approved_digest") != digest:
            if waived:
                _evidence(root, {**waiver, "quote": waiver["board_approval_quote"]}, "board approval test waiver", errors)
            else:
                errors.append("user approval missing, rejected, or stale for this storyboard digest")
        else:
            _evidence(root, approval, "user approval", errors)
    if stage == "master":
        final = contract.get("final_review")
        if not isinstance(final, dict) or final.get("status") != "pass" or final.get("storyboard_digest") != digest or final.get("full_playback") is not True:
            errors.append("final review: full playback and current storyboard digest required")
        else:
            _file(root, final.get("media_path"), final.get("media_sha256"), "final media", errors)
            if not _text(final.get("playback_evidence")) or len(final["playback_evidence"].strip()) < 12:
                errors.append("final review: concrete normal-speed full-playback evidence required")
            reviews = final.get("shots")
            if not isinstance(reviews, list) or [item.get("segment_id") for item in reviews if isinstance(item, dict)] != segment_ids:
                errors.append("final review: every segment must be covered in order")
            else:
                end = 0.0
                master_duration = final.get("duration_seconds")
                for index, item in enumerate(reviews):
                    label = f"final shot {index + 1}"
                    _file(root, item.get("media_path"), item.get("media_sha256"), label + " media", errors)
                    if item.get("media_path") != final.get("media_path") or item.get("media_sha256") != final.get("media_sha256"):
                        errors.append(f"{label}: reviewed interval must bind the final master media, not a separate clip")
                    start, stop = item.get("start_seconds"), item.get("end_seconds")
                    if (not isinstance(start, (int, float)) or isinstance(start, bool) or
                            not isinstance(stop, (int, float)) or isinstance(stop, bool) or
                            not math.isfinite(start) or not math.isfinite(stop) or
                            abs(start - end) > 0.05 or stop <= start):
                        errors.append(f"{label}: invalid or gapped coverage interval")
                    else:
                        end = float(stop)
                    _review(item.get("review"), label, errors)
                    if isinstance(plan, dict) and plan.get("semantic_contract_version") == 2:
                        from expression_contract import validate_evidence

                        segment = next((entry for entry in plan.get("segments", []) if isinstance(entry, dict) and
                                        entry.get("id") == item.get("segment_id")), None)
                        master_frames = item.get("keyframes")
                        if not isinstance(master_frames, list) or not master_frames:
                            errors.append(f"{label}: v2 master needs actual reviewed keyframes")
                            master_frames = []
                        for frame_index, frame in enumerate(master_frames):
                            if isinstance(frame, dict):
                                image_path = _file(root, frame.get("path"), frame.get("sha256"),
                                                   f"{label} keyframe {frame_index + 1}", errors)
                                if image_path is not None:
                                    _image(image_path, f"{label} keyframe {frame_index + 1}", errors)
                        if isinstance(segment, dict):
                            validate_evidence(segment.get("expression_requirements", []),
                                              {"evidence_by_requirement": item.get("evidence_by_requirement")},
                                              master_frames,
                                              {"path": final.get("media_path"), "sha256": final.get("media_sha256"),
                                               "duration_seconds": master_duration}, errors, label,
                                              (start, stop), expected_domain="master_global")
                duration = final.get("duration_seconds")
                if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or abs(end - duration) > 0.05:
                    errors.append("final review: full duration not covered")
    return {"passed": not errors, "stage": stage, "storyboard_digest": digest,
            "ready_for_user_review": stage == "plan" and not errors,
            "generation_ready": stage != "plan" and not errors,
            "legacy_not_certified": False, "errors": errors, "quality_review_claimed": False,
            "boundary": "integrity and recorded judgments only; no automatic semantic, aesthetic, or user-identity proof"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "digest"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--stage", choices=("plan", "batch", "master"), default="plan")
    args = parser.parse_args()
    root = Path(args.project).resolve()
    if args.command == "digest":
        errors: list[str] = []
        data = _json_file(root / CONTRACT, errors, "director contract")
        result = {"passed": data is not None, "storyboard_digest": storyboard_digest(data) if data else None, "errors": errors}
    else:
        result = validate(root, args.stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
