"""Mechanical closure for semantic contract v2; no semantic or aesthetic verdict."""

from pathlib import Path
import hashlib
import math
import re

STATIC_ROUTES = {"official_evidence", "sourced_chart", "real_media"}
MEDIA_KINDS = {"verified_source", "native_exact", "owned_visual", "generated_visual", "natural_motion"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _ids(value):
    return isinstance(value, list) and all(_text(item) for item in value) and len(value) == len(set(value))


def _inputs(root, implementation, errors, label):
    refs = implementation.get("inputs")
    if not isinstance(refs, list):
        errors.append(label + ": implementation.inputs must be a list")
        return set()
    paths = set()
    base = Path(root).resolve()
    for ref in refs:
        if (not isinstance(ref, dict) or not _text(ref.get("path")) or not _text(ref.get("sha256"))
                or not re.fullmatch(r"[0-9a-fA-F]{64}", ref["sha256"])):
            errors.append(label + ": implementation input needs path and SHA-256")
            continue
        relative = Path(ref["path"])
        target = (base / relative).resolve()
        if (relative.is_absolute() or ".." in relative.parts or not target.is_relative_to(base)
                or not target.is_file()):
            errors.append(label + ": implementation input path missing or unsafe: " + ref["path"])
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != ref["sha256"].lower():
            errors.append(label + ": implementation input SHA-256 drift: " + ref["path"])
            continue
        paths.add(ref["path"])
    return paths


def validate_segment(segment, root, errors, label):
    """Check authored obligations and implementation responsibility for one v2 segment."""
    requirements = segment.get("expression_requirements")
    if not isinstance(requirements, list) or not requirements:
        errors.append(label + ": expression_requirements must be nonempty")
        return
    ids = []
    cues = segment.get("srt_cue_ids")
    for index, req in enumerate(requirements, 1):
        prefix = f"{label} expression requirement {index}"
        if not isinstance(req, dict) or any(not _text(req.get(key)) for key in ("id", "relation", "visible_change", "must_be_seen")):
            errors.append(prefix + ": id/relation/visible_change/must_be_seen required")
            continue
        ids.append(req["id"])
        proof = req.get("proof_kind", "continuous_media")
        if proof not in ("continuous_media", "static_reading"):
            errors.append(prefix + ": proof_kind must be continuous_media or static_reading")
        elif proof == "static_reading" and segment.get("visual_route") not in STATIC_ROUTES:
            errors.append(prefix + ": static_reading requires an exact-source reading route")
        value = req.get("cue_ids")
        if (not isinstance(value, list) or not value or any(type(cue) is not int for cue in value)
                or len(value) != len(set(value)) or value != sorted(value) or not isinstance(cues, list)
                or not set(value).issubset(set(cue for cue in cues if type(cue) is int))):
            errors.append(prefix + ": cue_ids must belong to this segment in order")
    if len(ids) != len(set(ids)):
        errors.append(label + ": duplicate expression requirement ID")
    required = set(ids)
    options = segment.get("resource_options")
    chosen = segment.get("chosen_resource")
    chosen_id = chosen.get("resource_id") if isinstance(chosen, dict) else None
    if not isinstance(options, list):
        options = []
    chosen_coverage = set()
    for option in options:
        if not isinstance(option, dict):
            continue
        prefix = label + " resource option " + str(option.get("resource_id"))
        covers = option.get("covers_requirement_ids")
        gaps = option.get("gaps")
        if not _ids(covers) or not set(covers).issubset(required):
            errors.append(prefix + ": covers_requirement_ids must reference this segment")
            covers = []
        if not isinstance(gaps, list) or any(not _text(gap) for gap in gaps):
            errors.append(prefix + ": gaps must be a list of concrete limitations")
        elif required - set(covers) and not gaps:
            errors.append(prefix + ": uncovered requirements need a stated gap")
        if option.get("resource_id") == chosen_id:
            chosen_coverage = set(covers)
            if not _text(option.get("adaptation")):
                errors.append(prefix + ": chosen adaptation required")
        elif not _text(option.get("reason")):
            errors.append(prefix + ": rejected option needs a reason")
    if not isinstance(chosen, dict) or not isinstance(chosen.get("implementation"), dict):
        errors.append(label + ": v2 needs chosen_resource.implementation")
        return
    implementation = chosen["implementation"]
    paths = _inputs(root, implementation, errors, label)
    mapping = implementation.get("expression_map")
    if not isinstance(mapping, list) or not mapping:
        errors.append(label + ": implementation.expression_map must be nonempty")
        return
    auxiliary = {item["resource_id"]: item for item in implementation.get("auxiliary_sources", [])
                 if isinstance(item, dict) and _text(item.get("resource_id"))} if isinstance(implementation.get("auxiliary_sources", []), list) else {}
    mapped = set()
    for index, item in enumerate(mapping, 1):
        prefix = f"{label} expression_map {index}"
        if not isinstance(item, dict):
            errors.append(prefix + ": object required")
            continue
        rid = item.get("requirement_id")
        part = item.get("responsible_part")
        source = item.get("resource_id")
        inputs = item.get("project_input_paths")
        valid_rid = _text(rid) and rid in required
        if not valid_rid:
            errors.append(prefix + ": unknown requirement_id")
        valid_part = False
        if not _text(part) or part not in {"main", "auxiliary", "original"}:
            errors.append(prefix + ": responsible_part must be main/auxiliary/original")
        elif part == "main" and (source != chosen_id or not valid_rid or rid not in chosen_coverage):
            errors.append(prefix + ": main must match chosen resource and declared coverage")
        elif part == "main":
            valid_part = True
            if str(source).startswith(("shotcraft:", "agent_motion:", "hyperframes:")) and not any(
                    isinstance(path, str) and Path(path).suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}
                    for path in (inputs if isinstance(inputs, list) else [])):
                errors.append(prefix + ": reference mechanism needs hashed project code for execution")
                valid_part = False
        elif part == "auxiliary":
            aux = auxiliary.get(source) if _text(source) else None
            if (not isinstance(aux, dict) or aux.get("usage") not in {"adapted_private_code", "local_visual_asset"} or
                    not isinstance(inputs, list) or aux.get("project_input") not in inputs):
                errors.append(prefix + ": auxiliary must be an implemented source with matching project input, not reference_only")
            else:
                valid_part = True
        elif part == "original" and (not _text(source) or source not in
                                      ("project_original", chosen_id if str(chosen_id).startswith("original") else "")):
            errors.append(prefix + ": original must name project_original or selected original")
        elif part == "original":
            valid_part = True
        if (not isinstance(inputs, list) or not inputs or any(not _text(path) or path not in paths for path in inputs)):
            errors.append(prefix + ": project_input_paths must be hashed implementation inputs")
        if not _text(item.get("planned_state_change")):
            errors.append(prefix + ": planned_state_change required")
        if valid_rid and valid_part and isinstance(inputs, list) and inputs and all(_text(path) and path in paths for path in inputs):
            mapped.add(rid)
    if required - mapped:
        errors.append(label + ": expression requirements lack implemented coverage: " + ", ".join(sorted(required - mapped)))


def validate_visual_decision(segment, cue_times, errors, label, stage="pre-director"):
    """Check the small decision record inside the existing v2 segment.

    This validates only declared roles, timing and references. It cannot decide
    whether the proposed carrier, camera, or viewer interpretation is good.
    """
    record = segment.get("visual_decision")
    if not isinstance(record, dict) or not _text(record.get("viewer_before")):
        errors.append(label + ": visual_decision.viewer_before required for new v2 work")
        return
    roles = record.get("media_roles")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 6:
        errors.append(label + ": visual_decision needs 1-6 concrete media_roles")
        return
    role_ids = set()
    kinds = set()
    chosen = segment.get("chosen_resource")
    implementation = chosen.get("implementation") if isinstance(chosen, dict) else None
    declared_inputs = implementation.get("inputs") if isinstance(implementation, dict) else None
    inputs = {item["path"] for item in (declared_inputs if isinstance(declared_inputs, list) else [])
              if isinstance(item, dict) and _text(item.get("path"))}
    for index, role in enumerate(roles, 1):
        prefix = f"{label} media role {index}"
        if (not isinstance(role, dict) or not _text(role.get("id")) or role["id"] in role_ids or
                not isinstance(role.get("kind"), str) or role["kind"] not in MEDIA_KINDS or not _text(role.get("responsibility")) or
                not _text(role.get("input_need")) or role.get("input_state") not in {"needed", "bound"}):
            errors.append(prefix + ": unique id, known kind, responsibility, input need and state required")
            continue
        role_ids.add(role["id"])
        kinds.add(role["kind"])
        paths = role.get("input_paths", [])
        if not isinstance(paths, list) or any(not _text(path) for path in paths):
            errors.append(prefix + ": input_paths must be a path list")
        elif role["input_state"] == "bound" and (not paths or any(path not in inputs for path in paths)):
            errors.append(prefix + ": bound input_paths must be hashed implementation inputs")
        elif role["input_state"] == "needed" and paths:
            errors.append(prefix + ": needed role cannot claim bound input_paths")
        if stage == "storyboard" and role["input_state"] == "needed":
            errors.append(prefix + ": needed material/behavior cannot be marked complete at real-preview storyboard stage")
    route = segment.get("visual_route")
    if route == "official_evidence" and "verified_source" not in kinds:
        errors.append(label + ": official_evidence needs a verified_source role")
    if route == "sourced_chart" and not {"verified_source", "native_exact"}.issubset(kinds):
        errors.append(label + ": sourced_chart needs source and exact native graphics roles")
    if route == "image_to_video" or (route == "hybrid" and segment.get("uses_image_to_video") is True):
        if "natural_motion" not in kinds:
            errors.append(label + ": image-to-video behavior needs a natural_motion role")
    if segment.get("requires_exact_information") is True and not kinds.intersection({"verified_source", "native_exact"}):
        errors.append(label + ": exact information needs a source or native_exact role")
    requirements = segment.get("expression_requirements")
    if not isinstance(requirements, list):
        return
    previous_attention = None
    for req in requirements:
        if not isinstance(req, dict) or not _text(req.get("id")):
            continue
        prefix = f"{label} expression {req['id']} attention"
        attention = req.get("attention")
        if (not isinstance(attention, dict) or not _text(attention.get("focus")) or
                not _text(attention.get("camera_or_view")) or
                not isinstance(attention.get("clear_before"), list) or
                any(not _text(value) for value in attention["clear_before"])):
            errors.append(prefix + ": focus, camera/view and clear_before list required")
            continue
        if previous_attention is not None and attention["focus"] != previous_attention["focus"]:
            shared_group = (attention.get("parallel_read_group") and
                            attention.get("parallel_read_group") == previous_attention.get("parallel_read_group") and
                            _text(attention.get("dominant_focus")) and
                            attention.get("dominant_focus") == previous_attention.get("dominant_focus"))
            if not attention["clear_before"] and not shared_group:
                errors.append(prefix + ": changed focus needs old-focus retirement in clear_before or a shared parallel_read_group/dominant_focus")
        previous_attention = attention
        assigned = attention.get("media_role_ids")
        if not isinstance(assigned, list) or not assigned or any(not isinstance(value, str) or value not in role_ids for value in assigned):
            errors.append(prefix + ": media_role_ids must refer to declared roles")
        budget = attention.get("budget_seconds")
        hold = attention.get("min_read_seconds", 0)
        cue_ids = req.get("cue_ids")
        span = None
        if isinstance(cue_ids, list) and cue_ids and all(type(cue) is int and cue in cue_times for cue in cue_ids):
            span = cue_times[cue_ids[-1]][1] - cue_times[cue_ids[0]][0]
        if (type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0 or
                span is None or budget > span + .05):
            errors.append(prefix + ": budget_seconds must fit the bound cue window")
        if type(hold) not in (int, float) or not math.isfinite(hold) or hold < 0 or (type(budget) in (int, float) and hold > budget):
            errors.append(prefix + ": min_read_seconds must fit the declared budget")


def cue_window(root, plan, cue_ids):
    """Return real SRT or explicit authored-screen cue bounds in seconds.

    Authored seconds are a silent research clock, never an inferred voice/SRT.
    Plan validation separately binds source bytes and full cue coverage.
    """
    if plan.get("timebase_kind") == "authored_screen_timing":
        if plan.get("srt_source") or plan.get("audio_source"):
            raise ValueError("authored screen timing cannot claim real SRT or voice")
        entries = plan.get("authored_cues")
        if not isinstance(entries, list) or not entries:
            raise ValueError("authored_cues missing for authored reading")
        times = {}
        prior_id, prior_end = 0, 0.0
        for entry in entries:
            if not isinstance(entry, dict) or type(entry.get("id")) is not int or entry["id"] <= prior_id:
                raise ValueError("authored_cues need unique ordered positive IDs")
            start, end = entry.get("start_seconds"), entry.get("end_seconds")
            if (type(start) not in (int, float) or type(end) not in (int, float) or
                    not math.isfinite(start) or not math.isfinite(end) or start < prior_end - .001 or end <= start or
                    not _text(entry.get("text"))):
                raise ValueError("authored_cues need exact text and ordered finite screen seconds")
            times[entry["id"]] = (float(start), float(end))
            prior_id, prior_end = entry["id"], float(end)
        if (not isinstance(cue_ids, list) or not cue_ids or
                any(type(cue) is not int or cue not in times for cue in cue_ids) or
                cue_ids != sorted(set(cue_ids))):
            raise ValueError("authored reading cue window missing or unordered")
        return times[cue_ids[0]][0], times[cue_ids[-1]][1]
    source = plan.get("srt_source")
    if not _text(source):
        raise ValueError("SRT source missing for static reading")
    relative = Path(source)
    base = Path(root).resolve()
    path = (base / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(base):
        raise ValueError("unsafe SRT source for static reading")
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8-sig"))
    times = {}
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2 or not lines[0].strip().isdecimal():
            continue
        match = re.fullmatch(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", lines[1].strip())
        if match:
            values = [int(value) for value in match.groups()]
            times[int(lines[0])] = (values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000,
                                     values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000)
    if (not isinstance(cue_ids, list) or not cue_ids or
            any(type(cue) is not int or cue not in times for cue in cue_ids) or
            cue_ids != sorted(set(cue_ids))):
        raise ValueError("static reading cue window missing")
    return times[cue_ids[0]][0], times[cue_ids[-1]][1]


def validate_evidence(requirements, action, frames, media, errors, label, segment_interval=None, cue_windows=None,
                      expected_domain="preview_local", local_cue_windows=None, strict_continuous=False,
                      static_time_domain="srt_global"):
    """Check recorded actual intervals/frames, without judging what the pixels mean."""
    required = {item["id"]: item for item in (requirements if isinstance(requirements, list) else [])
                if isinstance(item, dict) and _text(item.get("id"))}
    entries = action.get("evidence_by_requirement") if isinstance(action, dict) else None
    if not isinstance(entries, list):
        errors.append(label + ": evidence_by_requirement must be a list")
        return
    frames = frames if isinstance(frames, list) else []
    frame_paths = {item["path"] for item in frames if isinstance(item, dict) and _text(item.get("path"))}
    media_duration = media.get("duration_seconds") if isinstance(media, dict) else None
    media_path = media.get("path") if isinstance(media, dict) else None
    media_hash = media.get("sha256") if isinstance(media, dict) else None
    needs_media = any(item.get("proof_kind", "continuous_media") == "continuous_media" for item in required.values())
    if needs_media and (not _text(media_path) or not _text(media_hash) or
            not re.fullmatch(r"[0-9a-fA-F]{64}", media_hash)):
        errors.append(label + ": actual preview media identity missing")
    seen = set()
    observed_signatures = set()
    for item in entries:
        if not isinstance(item, dict):
            errors.append(label + ": evidence entry must be an object")
            continue
        rid = item.get("requirement_id")
        if not _text(rid) or rid not in required or rid in seen:
            errors.append(label + ": evidence requirement ID unknown or duplicate")
            continue
        seen.add(rid)
        start, end = item.get("start_seconds"), item.get("end_seconds")
        proof_kind = required[rid].get("proof_kind", "continuous_media")
        if proof_kind == "static_reading" and item.get("evidence_kind") == "static_frame" and expected_domain != "master_global":
            if item.get("time_domain") != static_time_domain:
                errors.append(label + ": static reading must use " + static_time_domain + " cue time: " + rid)
            cue_interval = cue_windows.get(rid) if isinstance(cue_windows, dict) else None
            if (cue_interval is None or type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or
                    start < cue_interval[0] - 0.05 or end > cue_interval[1] + 0.05 or end <= start):
                errors.append(label + ": static reading interval must be inside bound " + static_time_domain + " cue window: " + rid)
            keyframe = item.get("frame_path")
            if not _text(keyframe) or keyframe not in frame_paths:
                errors.append(label + ": static reading needs a real shot frame: " + rid)
            if item.get("frame_sha256") != next((frame.get("sha256") for frame in frames if isinstance(frame, dict) and frame.get("path") == keyframe), None):
                errors.append(label + ": static reading frame SHA-256 differs from shot: " + rid)
            if not _text(item.get("observed_reading")) or item.get("status") != "observed":
                errors.append(label + ": static reading observation missing: " + rid)
            continue
        if item.get("evidence_kind", "continuous_media") != "continuous_media":
            errors.append(label + ": continuous obligation cannot use static frame: " + rid)
            continue
        if item.get("time_domain") != expected_domain:
            errors.append(label + ": media evidence time domain differs: " + rid)
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or type(media_duration) not in (int, float) or not all(math.isfinite(value) for value in
                (start, end, media_duration) if type(value) in (int, float)) or start < 0 or end <= start or
                end > media_duration + 0.05):
            errors.append(label + ": evidence interval outside actual segment media: " + rid)
        elif segment_interval is not None:
            lower, upper = segment_interval
            if (type(lower) not in (int, float) or type(upper) not in (int, float) or
                    not math.isfinite(lower) or not math.isfinite(upper) or
                    start < lower - 0.05 or end > upper + 0.05):
                errors.append(label + ": evidence interval outside bound shot segment: " + rid)
        if item.get("media_path") != media_path or item.get("media_sha256") != media_hash:
            errors.append(label + ": evidence media identity differs from preview: " + rid)
        paths = item.get("keyframe_paths")
        if not isinstance(paths, list) or not paths or any(not _text(path) or path not in frame_paths for path in paths):
            errors.append(label + ": evidence keyframes must name actual shot frames: " + rid)
        if not _text(item.get("observed_state_change")) or item.get("status") != "observed":
            errors.append(label + ": requirement has no recorded observed change: " + rid)
        if strict_continuous and expected_domain == "preview_local":
            window = local_cue_windows.get(rid) if isinstance(local_cue_windows, dict) else None
            if (not isinstance(window, tuple) or len(window) != 2 or
                    type(start) not in (int, float) or type(end) not in (int, float)):
                errors.append(label + ": requirement-specific cue/preview interval missing: " + rid)
            else:
                cue_start, cue_end = window
                if (end < cue_start - .25 or start > cue_end + .25 or
                        end - start > cue_end - cue_start + 1.0):
                    errors.append(label + ": continuous evidence must be local to its own cue, not the whole segment: " + rid)
            signature = (start, end, tuple(paths) if isinstance(paths, list) else (),
                         str(item.get("observed_state_change", "")).strip())
            if signature in observed_signatures:
                errors.append(label + ": distinct requirements cannot reuse one generic interval/frame/observation: " + rid)
            observed_signatures.add(signature)
    if set(required) - seen:
        errors.append(label + ": missing actual evidence for: " + ", ".join(sorted(set(required) - seen)))
