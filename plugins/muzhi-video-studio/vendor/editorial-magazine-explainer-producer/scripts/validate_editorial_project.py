#!/usr/bin/env python3
"""Validate hard contracts for the editorial-magazine explainer pipeline.

The validator is intentionally dependency-free and read-only. It checks the
machine-readable contracts; it does not replace visual review or a full watch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_FAMILIES = {
    "independent_component_animation",
    "full_editorial_illustration",
    "silent_google_flow",
}
SEMANTIC_COMPONENT_SOURCES = {
    "generated_component",
    "extracted_generated_component",
    "approved_reusable_asset",
}
LIFECYCLE_KEYS = (
    "enter",
    "settle",
    "act_or_receive",
    "yield",
    "resolve",
    "exit",
)
REQUIRED_QA_CHECKS = (
    "typecheck",
    "probe",
    "full_decode_zero_errors",
    "black_frame_check",
    "silence_check",
    "loudness_lra_true_peak",
    "flow_source_audio_absent",
    "caption_coverage_and_last_sentence",
    "locked_fingerprints_match",
    "all_semantic_stages_reviewed",
    "all_flow_and_full_illustrations_reviewed",
    "asset_class_scale_and_center_audit",
    "native_container_text_audit",
    "adaptive_composition_fit_audit",
    "longest_captions_final_resolution",
    "caption_hierarchy_contrast_and_safe_placement",
    "caption_main_visual_non_occlusion",
    "empty_semantic_containers_absent",
    "production_markers_absent",
    "typography_mobile_readability_and_non_duplication",
    "layer_exit_and_takeover",
    "critical_continuous_ranges_reviewed",
    "full_encoded_master_watched",
    "desktop_copy_hash_match",
)
QA_1_1_CHECKS = {
    "asset_class_scale_and_center_audit",
    "caption_hierarchy_contrast_and_safe_placement",
    "caption_main_visual_non_occlusion",
}
QA_1_2_CHECKS = {
    "native_container_text_audit",
    "adaptive_composition_fit_audit",
}
QA_2_0_CHECKS = {
    "director_storyboard_batch_gate",
    "full_voiced_animatic_approved",
    "semantic_visual_routing_audit",
    "official_source_and_chart_footer_audit",
    "i2v_duration_and_padding_audit",
    "new_bgm_for_project_and_hash_difference",
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PLACEHOLDER_RE = re.compile(r"^__FILL(?:_OR_[A-Z]+|_[A-Z0-9_]+)?__$")
REQUIRED_GATE_KEYS = (
    "gate_0",
    "gate_1",
    "gate_2",
    "gate_2_5_flow_handoff",
    "gate_3",
    "gate_4_publication",
)
REQUIRED_GATE2_WHOLE_FILM_ARTIFACTS = (
    "keyframe_overview",
    "rhythm_density_audit",
    "typography_role_and_form_audit",
    "empty_semantic_container_audit",
    "layer_exit_and_metaphor_audit",
    "flow_shot_list",
    "gate2_checklist",
)
GATE2_1_2_WHOLE_FILM_ARTIFACTS = (
    "container_native_text_and_fit_plan_audit",
)
GATE2_2_0_WHOLE_FILM_ARTIFACTS = (
    "plain_language_director_brief",
    "director_storyboard_contract",
    "visual_storyboard",
    "full_voiced_animatic",
    "semantic_visual_routing_audit",
    "i2v_duration_coverage_audit",
    "new_bgm_brief_and_hash_comparison",
)
REQUIRED_LOCK_DOMAINS = {
    "audio",
    "captions",
    "timeline",
    "flow",
    "bgm",
    "components",
    "typography",
}
REQUIRED_FLOW_LOCK_INVARIANTS = {
    "source_files",
    "normalized_files",
    "speed",
    "crop_window",
    "absolute_timing",
    "action_order",
}
REQUIRED_TRACKING_HORIZONS = {"24h", "72h", "7d"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"top-level JSON value must be an object: {path}")
    return data


def is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        stripped = value.strip()
        return bool(stripped) and not PLACEHOLDER_RE.match(stripped)
    return True


def require_filled(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> Any:
    value = obj.get(key)
    if not is_filled(value):
        errors.append(f"{path}.{key}: required value is missing or still a template placeholder")
    return value


def require_true(obj: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    if obj.get(key) is not True:
        errors.append(f"{path}.{key}: must be true")


def as_object(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    return value


def as_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    return value


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def schema_at_least(data: dict[str, Any], major: int, minor: int) -> bool:
    raw = str(data.get("schema_version", "0.0")).strip()
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", raw)
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (major, minor)


def require_exact_numeric_range(
    value: Any,
    expected: tuple[float, float],
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(value, list) or len(value) != 2 or not all(numeric(item) for item in value):
        errors.append(f"{path}: must be a numeric [min, max] range")
        return
    if tuple(value) != expected:
        errors.append(f"{path}: must equal [{expected[0]}, {expected[1]}] for this pipeline")


def validate_normalized_rect(value: Any, path: str, errors: list[str]) -> None:
    rect = as_object(value, path, errors)
    coordinates = {key: rect.get(key) for key in ("x", "y", "width", "height")}
    if not all(numeric(item) for item in coordinates.values()):
        errors.append(f"{path}: x, y, width and height must be numeric")
        return
    if coordinates["x"] < 0 or coordinates["y"] < 0:
        errors.append(f"{path}: x and y must be non-negative")
    if coordinates["width"] <= 0 or coordinates["height"] <= 0:
        errors.append(f"{path}: width and height must be greater than zero")
    if coordinates["x"] + coordinates["width"] > 1.000001 or coordinates["y"] + coordinates["height"] > 1.000001:
        errors.append(f"{path}: the text region must stay inside its parent container")


def validate_pixel_bounds(value: Any, path: str, errors: list[str]) -> dict[str, Any]:
    bounds = as_object(value, path, errors)
    coordinates = {key: bounds.get(key) for key in ("left", "top", "right", "bottom")}
    if not all(numeric(item) for item in coordinates.values()):
        errors.append(f"{path}: left, top, right and bottom must be numeric")
        return {}
    if coordinates["left"] < 0 or coordinates["top"] < 0:
        errors.append(f"{path}: left and top must be non-negative")
    if coordinates["right"] <= coordinates["left"] or coordinates["bottom"] <= coordinates["top"]:
        errors.append(f"{path}: right/bottom must exceed left/top")
    return bounds


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()\-—…]", "", value).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_root_from(data: dict[str, Any], path: str, errors: list[str], verify_files: bool) -> Path | None:
    raw = require_filled(data, "project_root", path, errors)
    if not isinstance(raw, str) or not is_filled(raw):
        return None
    root = Path(raw)
    if not root.is_absolute():
        errors.append(f"{path}.project_root: must be an absolute path")
        return None
    if verify_files and not root.is_dir():
        errors.append(f"{path}.project_root: directory does not exist: {root}")
    return root


def verify_path_hash(
    root: Path | None,
    raw_path: Any,
    expected_sha: Any,
    path: str,
    errors: list[str],
    verify_files: bool,
) -> None:
    if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
        errors.append(f"{path}.sha256: must be a 64-character SHA-256")
        return
    if not is_filled(raw_path):
        errors.append(f"{path}.path: required value is missing or still a template placeholder")
        return
    if not verify_files:
        return
    file_path = Path(str(raw_path))
    if not file_path.is_absolute():
        if root is None:
            errors.append(f"{path}.path: cannot resolve relative path without project_root")
            return
        file_path = root / file_path
    if not file_path.is_file():
        errors.append(f"{path}.path: file does not exist: {file_path}")
        return
    actual = sha256_file(file_path)
    if actual.lower() != expected_sha.lower():
        errors.append(f"{path}.sha256: actual file hash does not match")


def load_verified_evidence_manifest(
    root: Path | None,
    raw_path: Any,
    expected_sha: Any,
    path: str,
    errors: list[str],
    verify_files: bool,
) -> dict[str, Any] | None:
    verify_path_hash(root, raw_path, expected_sha, path, errors, verify_files)
    if not verify_files or root is None or not is_filled(raw_path):
        return None
    file_path = Path(str(raw_path))
    if not file_path.is_absolute():
        file_path = root / file_path
    if not file_path.is_file():
        return None
    try:
        return load_json(file_path)
    except ValueError as exc:
        errors.append(str(exc))
        return None


def validate_shot_contract(
    shot: dict[str, Any],
    path: str = "shot",
    seen_shots: set[str] | None = None,
    master_duration: float | None = None,
    require_native_fit: bool = False,
) -> list[str]:
    errors: list[str] = []
    shot_id = require_filled(shot, "shot_id", path, errors)
    if isinstance(shot_id, str) and seen_shots is not None:
        if shot_id in seen_shots:
            errors.append(f"{path}.shot_id: duplicate {shot_id}")
        seen_shots.add(shot_id)
    start = shot.get("start_seconds")
    end = shot.get("end_seconds")
    valid_range = numeric(start) and numeric(end) and end > start
    if not valid_range:
        errors.append(f"{path}: start_seconds and end_seconds must define a positive range")
    elif master_duration is not None and (start < 0 or end > master_duration + 0.001):
        errors.append(f"{path}: shot range must stay inside the master clock")
    for key in (
        "spoken_text",
        "semantic_proposition",
        "subject",
        "action",
        "acted_on_object",
        "result",
        "viewer_takeaway",
        "family_reason",
    ):
        require_filled(shot, key, path, errors)
    family = shot.get("shot_family")
    if family not in ALLOWED_FAMILIES:
        errors.append(f"{path}.shot_family: must be one of {sorted(ALLOWED_FAMILIES)}")

    stable = shot.get("stable_primary_composition_seconds")
    if not numeric(stable) or stable <= 0:
        errors.append(f"{path}.stable_primary_composition_seconds: must be greater than zero")
    else:
        if stable < 1.5 and not is_filled(shot.get("sub_1_5_second_exception")):
            errors.append(f"{path}: a full primary composition under 1.5s needs an explicit exception")
        if valid_range and stable > (end - start) + 0.001:
            errors.append(f"{path}.stable_primary_composition_seconds: cannot exceed shot duration")

    cues = as_object(shot.get("cues"), f"{path}.cues", errors)
    for key in ("scene_start", "action_cue", "text_cue"):
        if not numeric(cues.get(key)):
            errors.append(f"{path}.cues.{key}: must be numeric")
    if valid_range and all(numeric(cues.get(key)) for key in ("scene_start", "action_cue", "text_cue")):
        if abs(cues["scene_start"] - start) > 0.001:
            errors.append(f"{path}.cues.scene_start: must equal shot start_seconds")
        for key in ("action_cue", "text_cue"):
            if cues[key] < start or cues[key] > end:
                errors.append(f"{path}.cues.{key}: must stay inside the shot range")

    contract_v1_2 = require_native_fit or schema_at_least(shot, 1, 2)
    layers = as_list(shot.get("layers"), f"{path}.layers", errors)
    layer_ids: set[str] = set()
    if family == "independent_component_animation" and not layers:
        errors.append(f"{path}.layers: component animation needs independently addressable layers")
    has_generated_core_actor = False
    for layer_index, raw_layer in enumerate(layers):
        layer_path = f"{path}.layers[{layer_index}]"
        layer = as_object(raw_layer, layer_path, errors)
        layer_id = require_filled(layer, "layer_id", layer_path, errors)
        if isinstance(layer_id, str):
            if layer_id in layer_ids:
                errors.append(f"{layer_path}.layer_id: duplicate {layer_id}")
            layer_ids.add(layer_id)
        role = require_filled(layer, "role", layer_path, errors)
        source = require_filled(layer, "asset_source", layer_path, errors)
        if role in {"semantic_actor", "acted_on_object", "key_tool", "result_state"} and layer.get("core_semantic_actor") is not True:
            errors.append(f"{layer_path}.core_semantic_actor: key semantic roles must be marked true")
        if layer.get("core_semantic_actor") is True:
            if source not in SEMANTIC_COMPONENT_SOURCES:
                errors.append(
                    f"{layer_path}.asset_source: a core semantic actor must be a generated/extracted component or approved reusable asset"
                )
            else:
                has_generated_core_actor = True
        require_true(layer, "independently_addressable", layer_path, errors)
        lifecycle = as_object(layer.get("lifecycle"), f"{layer_path}.lifecycle", errors)
        for key in LIFECYCLE_KEYS:
            require_filled(lifecycle, key, f"{layer_path}.lifecycle", errors)
    if family == "independent_component_animation" and not has_generated_core_actor:
        errors.append(f"{path}.layers: at least one core semantic actor must use a real generated/reusable component")

    stages = as_list(shot.get("stages"), f"{path}.stages", errors)
    if not stages:
        errors.append(f"{path}.stages: at least one semantic stage is required")
    core_stage_count = 0
    for stage_index, raw_stage in enumerate(stages):
        stage_path = f"{path}.stages[{stage_index}]"
        stage = as_object(raw_stage, stage_path, errors)
        require_filled(stage, "stage_id", stage_path, errors)
        core = stage.get("core_semantic_action") is True
        if core:
            core_stage_count += 1
        explanation_required = stage.get("explanation_required") is True
        if core and not explanation_required:
            errors.append(f"{stage_path}: a core semantic action requires explanatory typography")
        if explanation_required:
            phrase = require_filled(stage, "explanation_phrase", stage_path, errors)
            caption_text = require_filled(stage, "caption_text", stage_path, errors)
            role = require_filled(stage, "explanation_role", stage_path, errors)
            if role not in {"judgment", "classification", "causality", "relationship", "conclusion"}:
                errors.append(f"{stage_path}.explanation_role: must add judgment, classification, causality, relationship or conclusion")
            require_filled(stage, "explanation_form", stage_path, errors)
            require_true(stage, "adds_information_beyond_caption", stage_path, errors)
            if normalize_text(phrase) and normalize_text(phrase) == normalize_text(caption_text):
                errors.append(f"{stage_path}: explanatory phrase duplicates the caption")
        action_cue = stage.get("action_cue")
        text_cue = stage.get("text_cue")
        keyword_cue = stage.get("spoken_keyword_cue")
        if not numeric(action_cue) or not numeric(text_cue) or not numeric(keyword_cue):
            errors.append(f"{stage_path}: spoken_keyword_cue, action_cue and text_cue must be numeric")
        elif valid_range and (
            action_cue < start
            or action_cue > end
            or text_cue < start
            or text_cue > end
            or keyword_cue < start
            or keyword_cue > end
        ):
            errors.append(f"{stage_path}: action_cue and text_cue must stay inside the shot range")
        else:
            if keyword_cue - action_cue > 0.18 + 0.001:
                errors.append(f"{stage_path}.action_cue: semantic action begins more than 0.18s before the spoken keyword")
            if text_cue < keyword_cue - 0.05:
                errors.append(f"{stage_path}.text_cue: explanatory text appears before the spoken meaning")
        hold = stage.get("recognizable_hold_seconds")
        if core and (not numeric(hold) or hold < 0.8):
            errors.append(f"{stage_path}.recognizable_hold_seconds: core action needs at least 0.8s unless redesigned")
    if family == "independent_component_animation" and core_stage_count == 0:
        errors.append(f"{path}.stages: component animation needs at least one core semantic stage")

    containers = as_list(shot.get("semantic_containers", []), f"{path}.semantic_containers", errors)
    for container_index, raw_container in enumerate(containers):
        container_path = f"{path}.semantic_containers[{container_index}]"
        container = as_object(raw_container, container_path, errors)
        require_filled(container, "container_id", container_path, errors)
        require_filled(container, "kind", container_path, errors)
        if container.get("communicative") is True and not is_filled(container.get("text")):
            errors.append(f"{container_path}: communicative container must have local text")
        if contract_v1_2 and container.get("communicative") is True:
            if container.get("text_source") != "local_compositor":
                errors.append(f"{container_path}.text_source: must equal local_compositor")
            parent_layer_id = require_filled(container, "parent_layer_id", container_path, errors)
            if isinstance(parent_layer_id, str) and parent_layer_id not in layer_ids:
                errors.append(f"{container_path}.parent_layer_id: must reference a real layer in this shot")
            if container.get("coordinate_space") != "parent_local":
                errors.append(f"{container_path}.coordinate_space: must equal parent_local")
            validate_normalized_rect(
                container.get("text_region_normalized"),
                f"{container_path}.text_region_normalized",
                errors,
            )
            padding = container.get("padding_percent")
            if not numeric(padding) or not 0 <= padding <= 20:
                errors.append(f"{container_path}.padding_percent: must be between 0 and 20")
            if container.get("perspective_mode") != "matched_parent":
                errors.append(f"{container_path}.perspective_mode: must equal matched_parent")
            require_true(container, "clip_to_container", container_path, errors)
            require_true(container, "moves_with_parent", container_path, errors)
            if container.get("visual_hierarchy_role") not in {"primary", "secondary", "metadata"}:
                errors.append(f"{container_path}.visual_hierarchy_role: invalid")
            minimum_font = container.get("minimum_font_px")
            if not numeric(minimum_font) or minimum_font < 32:
                errors.append(f"{container_path}.minimum_font_px: must be at least 32")
        if container.get("communicative") is not True and not is_filled(container.get("decorative_reason")):
            errors.append(f"{container_path}: non-communicative container needs a decorative_reason")

    if contract_v1_2 and family == "independent_component_animation":
        fit = as_object(shot.get("adaptive_composition_fit"), f"{path}.adaptive_composition_fit", errors)
        require_true(fit, "required", f"{path}.adaptive_composition_fit", errors)
        if fit.get("fit_mode") != "contain":
            errors.append(f"{path}.adaptive_composition_fit.fit_mode: must equal contain")
        baseline_scale = fit.get("approved_baseline_scale")
        if not numeric(baseline_scale) or baseline_scale <= 0:
            errors.append(f"{path}.adaptive_composition_fit.approved_baseline_scale: must be greater than zero")
        require_exact_numeric_range(
            fit.get("target_scale_change_percent_range"),
            (8, 12),
            f"{path}.adaptive_composition_fit.target_scale_change_percent_range",
            errors,
        )
        require_exact_numeric_range(
            fit.get("allowed_tuning_percent_range"),
            (4, 15),
            f"{path}.adaptive_composition_fit.allowed_tuning_percent_range",
            errors,
        )
        hard_bounds = validate_pixel_bounds(
            fit.get("hard_safe_bounds_px"),
            f"{path}.adaptive_composition_fit.hard_safe_bounds_px",
            errors,
        )
        preferred_bounds = validate_pixel_bounds(
            fit.get("preferred_stage_bounds_px"),
            f"{path}.adaptive_composition_fit.preferred_stage_bounds_px",
            errors,
        )
        if hard_bounds and preferred_bounds and not (
            hard_bounds["left"] <= preferred_bounds["left"]
            and hard_bounds["top"] <= preferred_bounds["top"]
            and hard_bounds["right"] >= preferred_bounds["right"]
            and hard_bounds["bottom"] >= preferred_bounds["bottom"]
        ):
            errors.append(f"{path}.adaptive_composition_fit: preferred stage must stay inside hard safe bounds")
        require_exact_numeric_range(
            fit.get("preferred_primary_axis_fill_ratio_range"),
            (0.72, 0.9),
            f"{path}.adaptive_composition_fit.preferred_primary_axis_fill_ratio_range",
            errors,
        )
        for key, expected in (("maximum_width_fill_ratio", 0.9), ("maximum_height_fill_ratio", 0.92), ("maximum_center_offset_x_px", 90)):
            if fit.get(key) != expected:
                errors.append(f"{path}.adaptive_composition_fit.{key}: must equal {expected}")
        require_true(fit, "per_shot_tuning_required", f"{path}.adaptive_composition_fit", errors)

    require_true(shot, "previous_primary_exit_defined", path, errors)
    caption_layout = as_object(shot.get("caption_layout"), f"{path}.caption_layout", errors)
    require_filled(caption_layout, "approved_text", f"{path}.caption_layout", errors)
    if caption_layout.get("single_line_required") is not True and not is_filled(
        caption_layout.get("approved_two_line_exception")
    ):
        errors.append(f"{path}.caption_layout: two-line captions need an approved exception")
    require_true(
        caption_layout,
        "final_resolution_boundary_test_required",
        f"{path}.caption_layout",
        errors,
    )
    require_filled(shot, "transition_in", path, errors)
    require_filled(shot, "transition_out", path, errors)
    required_assets = as_list(shot.get("required_assets"), f"{path}.required_assets", errors)
    if not required_assets or not all(is_filled(item) for item in required_assets):
        errors.append(f"{path}.required_assets: list every required asset")
    prohibited = set(as_list(shot.get("prohibited_shortcuts"), f"{path}.prohibited_shortcuts", errors))
    required_prohibitions = {
        "whole_image_motion_as_semantic_animation",
        "generated_readable_chinese",
        "empty_communicative_container",
        "production_markers_in_final_frame",
    }
    if contract_v1_2:
        required_prohibitions.update({
            "detached_overlay_text_for_semantic_container",
            "uniform_global_scale_without_per_shot_fit",
        })
    if not required_prohibitions.issubset(prohibited):
        errors.append(f"{path}.prohibited_shortcuts: missing hard production prohibitions")
    if shot.get("gate_2_status") not in {"waiting_user_review", "approved", "rejected"}:
        errors.append(f"{path}.gate_2_status: invalid")
    return errors


def validate_project(data: dict[str, Any], verify_files: bool = False) -> list[str]:
    errors: list[str] = []
    if data.get("pipeline") != "editorial-magazine-explainer":
        errors.append("pipeline: must equal editorial-magazine-explainer")
    require_filled(data, "project_id", "project", errors)
    require_filled(data, "title", "project", errors)
    project_root = project_root_from(data, "project", errors, verify_files)

    authorization = as_object(data.get("authorization"), "authorization", errors)
    require_true(authorization, "execution_confirmed", "authorization", errors)

    if schema_at_least(data, 1, 4):
        production_clock = as_object(data.get("production_clock"), "production_clock", errors)
        require_true(
            production_clock,
            "starts_after_locked_script_evidence_and_final_audio",
            "production_clock",
            errors,
        )
        for key in ("locked_script_ready", "evidence_pack_ready", "final_narration_ready", "same_day_delivery_target"):
            require_true(production_clock, key, "production_clock", errors)
        require_filled(production_clock, "started_at", "production_clock", errors)
        if production_clock.get("fixed_stage_time_limits") is not False:
            errors.append("production_clock.fixed_stage_time_limits: must be false")
        if production_clock.get("quality_gates_may_be_skipped_for_deadline") is not False:
            errors.append("production_clock.quality_gates_may_be_skipped_for_deadline: must be false")

    sources = as_object(data.get("sources"), "sources", errors)
    input_mode = sources.get("input_mode")
    if input_mode not in {"recording_plus_approved_copy", "recording_plus_srt", "approved_copy_only"}:
        errors.append("sources.input_mode: invalid or missing")
    require_filled(sources, "original_audio", "sources", errors)
    if input_mode in {"recording_plus_approved_copy", "approved_copy_only"}:
        require_filled(sources, "approved_copy", "sources", errors)
    if schema_at_least(data, 1, 4):
        require_filled(sources, "evidence_pack", "sources", errors)
    if input_mode == "recording_plus_srt":
        require_filled(sources, "input_srt", "sources", errors)
    require_true(sources, "originals_preserved", "sources", errors)

    clock = as_object(data.get("master_clock"), "master_clock", errors)
    require_filled(clock, "audio_path", "master_clock", errors)
    duration = clock.get("duration_seconds")
    if not numeric(duration) or duration <= 0:
        errors.append("master_clock.duration_seconds: must be greater than zero")
    sample_count = clock.get("sample_count")
    if not isinstance(sample_count, int) or sample_count <= 0:
        errors.append("master_clock.sample_count: must be a positive integer")
    sha = clock.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        errors.append("master_clock.sha256: must be a 64-character SHA-256")
    require_true(clock, "locked", "master_clock", errors)
    if clock.get("time_stretch_allowed") is not False:
        errors.append("master_clock.time_stretch_allowed: must be false")
    verify_path_hash(project_root, clock.get("audio_path"), sha, "master_clock", errors, verify_files)

    captions = as_object(data.get("captions"), "captions", errors)
    require_filled(captions, "srt_path", "captions", errors)
    if not isinstance(captions.get("count"), int) or captions.get("count", 0) <= 0:
        errors.append("captions.count: must be a positive integer")
    require_true(captions, "last_sentence_verified", "captions", errors)
    require_true(captions, "locked", "captions", errors)
    caption_sha = captions.get("sha256")
    if not isinstance(caption_sha, str) or not SHA256_RE.fullmatch(caption_sha):
        errors.append("captions.sha256: must be a 64-character SHA-256")
    verify_path_hash(project_root, captions.get("srt_path"), caption_sha, "captions", errors, verify_files)
    if captions.get("single_line_default") is not True:
        errors.append("captions.single_line_default: must be true for this vertical short-video pipeline")
    if captions.get("automatic_wrap_allowed") is not False:
        errors.append("captions.automatic_wrap_allowed: must be false")
    require_true(
        captions,
        "longest_caption_boundary_test_required",
        "captions",
        errors,
    )

    voice = as_object(data.get("voice"), "voice", errors)
    profile = require_filled(voice, "profile", "voice", errors)
    if profile == "approved-youth-bright-profile":
        require_true(
            voice,
            "duration_and_sample_count_must_match_master",
            "voice",
            errors,
        )
        require_true(voice, "report_required", "voice", errors)

    bgm = as_object(data.get("bgm"), "bgm", errors)
    if bgm.get("required") is True and bgm.get("user_opt_out") is True:
        errors.append("bgm: required and user_opt_out cannot both be true")
    if bgm.get("required") is not True and bgm.get("user_opt_out") is not True:
        errors.append("bgm: background music is required unless user_opt_out is true")
    if bgm.get("required") is True:
        for key in ("no_lyrics", "speech_first", "fade_in_out", "sidechain_ducking", "provenance_required"):
            require_true(bgm, key, "bgm", errors)
        if schema_at_least(data, 1, 4):
            require_filled(bgm, "music_brief", "bgm", errors)
            require_filled(bgm, "provider_or_source", "bgm", errors)
            require_true(bgm, "newly_created_or_newly_licensed_for_project", "bgm", errors)
            if bgm.get("reused_from_previous_project") is not False:
                errors.append("bgm.reused_from_previous_project: must be false")

    if schema_at_least(data, 1, 4):
        gates = as_object(data.get("gates"), "gates", errors)
        for key in ("gate_2a_director_interpretation", "gate_2d_design_lock", "gate_2s_full_storyboard", "gate_2m_full_voiced_animatic", "gate_2p_motion_pilot", "gate_2b_full_production_map"):
            if key not in gates:
                errors.append(f"gates.{key}: required Gate key is missing")

    gates = as_object(data.get("gates"), "gates", errors)
    for key in REQUIRED_GATE_KEYS:
        if key not in gates:
            errors.append(f"gates.{key}: required Gate key is missing")
    gate_2 = gates.get("gate_2")
    allowed_by_gate = {
        "gate_0": {"not_started", "in_progress", "approved", "rejected"},
        "gate_1": {"not_started", "in_progress", "approved", "rejected"},
        "gate_2": {"not_started", "in_progress", "waiting_user_review", "approved", "rejected"},
        "gate_2_5_flow_handoff": {"not_started", "in_progress", "waiting_user_review", "approved", "rejected"},
        "gate_3": {"not_started", "in_progress", "waiting_user_review", "approved", "rejected"},
        "gate_4_publication": {"not_started", "in_progress", "published", "tracking"},
    }
    for key, allowed in allowed_by_gate.items():
        if key in gates and gates.get(key) not in allowed:
            errors.append(f"gates.{key}: invalid state {gates.get(key)!r}")
    if gates.get("gate_0") != "approved":
        errors.append("gates.gate_0: execution contract requires Gate 0 approval")
    gate_evidence = as_object(data.get("gate_evidence"), "gate_evidence", errors)
    gate_1_evidence = as_object(gate_evidence.get("gate_1"), "gate_evidence.gate_1", errors)
    if gates.get("gate_1") == "approved":
        require_true(gate_1_evidence, "internal_consolidation_complete", "gate_evidence.gate_1", errors)
        require_filled(gate_1_evidence, "completed_at", "gate_evidence.gate_1", errors)
    if gate_2 in {"in_progress", "waiting_user_review", "approved"} and gates.get("gate_1") != "approved":
        errors.append("gates.gate_2: Gate 1 must be approved first")
    gate_2_evidence = as_object(gate_evidence.get("gate_2"), "gate_evidence.gate_2", errors)
    if gate_2 == "approved":
        require_true(gate_2_evidence, "all_shots_included", "gate_evidence.gate_2", errors)
        require_true(gate_2_evidence, "whole_package_user_approved", "gate_evidence.gate_2", errors)
        require_filled(gate_2_evidence, "approved_by", "gate_evidence.gate_2", errors)
        require_filled(gate_2_evidence, "user_approval_quote", "gate_evidence.gate_2", errors)
        require_filled(gate_2_evidence, "approved_at", "gate_evidence.gate_2", errors)
        verify_path_hash(
            project_root,
            gate_2_evidence.get("manifest_path"),
            gate_2_evidence.get("manifest_sha256"),
            "gate_evidence.gate_2.manifest",
            errors,
            verify_files,
        )
        if verify_files and project_root is not None and is_filled(gate_2_evidence.get("manifest_path")):
            manifest_path = Path(str(gate_2_evidence["manifest_path"]))
            if not manifest_path.is_absolute():
                manifest_path = project_root / manifest_path
            if manifest_path.is_file():
                try:
                    manifest_data = load_json(manifest_path)
                    errors.extend(validate_gate2_manifest(manifest_data, verify_files=True))
                    if manifest_data.get("project_id") != data.get("project_id"):
                        errors.append("gate_evidence.gate_2.manifest: project_id mismatch")
                    manifest_ids = set(manifest_data.get("all_shot_ids", []))
                    project_ids = {shot.get("shot_id") for shot in data.get("shots", []) if isinstance(shot, dict)}
                    if manifest_ids != project_ids:
                        errors.append("gate_evidence.gate_2.manifest: shot set does not match project contract")
                    approval = manifest_data.get("approval", {})
                    if approval.get("user_approval_quote") != gate_2_evidence.get("user_approval_quote"):
                        errors.append("gate_evidence.gate_2.manifest: approval quote mismatch")
                    if approval.get("approved_at") != gate_2_evidence.get("approved_at"):
                        errors.append("gate_evidence.gate_2.manifest: approval time mismatch")
                except ValueError as exc:
                    errors.append(str(exc))
    if gates.get("gate_2_5_flow_handoff") not in {"not_started"} and gate_2 != "approved":
        errors.append("gates.gate_2_5_flow_handoff: Gate 2 must be approved first")
    if gates.get("gate_3") not in {"not_started"} and gate_2 != "approved":
        errors.append("gates.gate_3: Gate 2 must be approved first")
    if data.get("local_production_started") is True and gate_2 != "approved":
        errors.append("local_production_started: Gate 2 and its approval evidence must pass first")

    shots = as_list(data.get("shots"), "shots", errors)
    if not shots:
        errors.append("shots: at least one shot contract is required")
    seen_shots: set[str] = set()
    for index, raw_shot in enumerate(shots):
        path = f"shots[{index}]"
        shot = as_object(raw_shot, path, errors)
        errors.extend(
            validate_shot_contract(
                shot,
                path,
                seen_shots,
                float(duration) if numeric(duration) else None,
                require_native_fit=schema_at_least(data, 1, 2),
            )
        )
    if gate_2 == "approved":
        for index, shot in enumerate(shots):
            if isinstance(shot, dict) and shot.get("gate_2_status") != "approved":
                errors.append(f"shots[{index}].gate_2_status: every shot must be approved before whole-package Gate 2 approval")

    ordered_shots = [shot for shot in shots if isinstance(shot, dict) and numeric(shot.get("start_seconds")) and numeric(shot.get("end_seconds"))]
    ordered_shots.sort(key=lambda item: item["start_seconds"])
    if ordered_shots and ordered_shots[0]["start_seconds"] > 0.001:
        errors.append("shots: timeline must begin at 0 or declare an explicit opening shot")
    for previous, current in zip(ordered_shots, ordered_shots[1:]):
        if current["start_seconds"] < previous["end_seconds"] - 0.001:
            errors.append(f"shots: {previous.get('shot_id')} overlaps {current.get('shot_id')}")
        elif current["start_seconds"] > previous["end_seconds"] + 0.001:
            errors.append(f"shots: uncovered gap between {previous.get('shot_id')} and {current.get('shot_id')}")
    if ordered_shots and numeric(duration) and ordered_shots[-1]["end_seconds"] < duration - 0.001:
        errors.append("shots: timeline does not cover the end of the master clock")

    flow = as_object(data.get("flow"), "flow", errors)
    if flow.get("source_audio_must_be_removed") is not True:
        errors.append("flow.source_audio_must_be_removed: must be true")
    if flow.get("handoff_created") is True:
        if gate_2 != "approved" or flow.get("all_flow_shots_gate_2_approved") is not True:
            errors.append("flow.handoff_created: requires explicit whole-package Gate 2 approval")
        flow_shots = as_list(flow.get("shots"), "flow.shots", errors)
        if not flow_shots:
            errors.append("flow.shots: handoff is created but no approved Flow shots are listed")
        for index, raw_flow_shot in enumerate(flow_shots):
            path = f"flow.shots[{index}]"
            flow_shot = as_object(raw_flow_shot, path, errors)
            require_filled(flow_shot, "shot_id", path, errors)
            require_true(flow_shot, "no_text_reference", path, errors)
            require_true(flow_shot, "production_prompt_complete", path, errors)
            require_filled(flow_shot, "spoken_text", path, errors)
            require_filled(flow_shot, "return_path", path, errors)
            if not numeric(flow_shot.get("target_duration_seconds")) or flow_shot.get("target_duration_seconds", 0) <= 0:
                errors.append(f"{path}.target_duration_seconds: must be greater than zero")
            if not numeric(flow_shot.get("action_cue")):
                errors.append(f"{path}.action_cue: must be numeric")
            verify_path_hash(project_root, flow_shot.get("reference_path"), flow_shot.get("reference_sha256"), f"{path}.reference", errors, verify_files)
            verify_path_hash(project_root, flow_shot.get("prompt_path"), flow_shot.get("prompt_sha256"), f"{path}.prompt", errors, verify_files)
            if flow.get("return_received") is True:
                require_true(flow_shot, "returned", path, errors)
                require_true(flow_shot, "content_inspected", path, errors)
                require_true(flow_shot, "source_audio_removed", path, errors)
                require_filled(flow_shot, "actual_content_mapping", path, errors)
                verify_path_hash(project_root, flow_shot.get("raw_path"), flow_shot.get("raw_sha256"), f"{path}.raw", errors, verify_files)
                verify_path_hash(
                    project_root,
                    flow_shot.get("normalized_path"),
                    flow_shot.get("normalized_sha256"),
                    f"{path}.normalized",
                    errors,
                    verify_files,
                )
                if (
                    not numeric(flow_shot.get("action_landmark_seconds"))
                    or flow_shot.get("action_landmark_seconds", 0) <= 0
                    or not numeric(flow_shot.get("placed_action_cue"))
                ):
                    errors.append(f"{path}: action landmark and placed action cue must be numeric")
                elif numeric(flow_shot.get("action_cue")) and abs(flow_shot["placed_action_cue"] - flow_shot["action_cue"]) > 0.001:
                    errors.append(f"{path}.placed_action_cue: must match the approved action_cue")
        if gates.get("gate_2_5_flow_handoff") != "approved":
            errors.append("flow.handoff_created: Gate 2.5 must be approved")
    if flow.get("return_received") is True:
        for key in (
            "raw_files_preserved",
            "content_inspected",
            "source_audio_removed",
            "normalized_to_project_spec",
            "action_landmark_aligned_to_action_cue",
        ):
            require_true(flow, key, "flow", errors)

    has_flow_shots = any(isinstance(shot, dict) and shot.get("shot_family") == "silent_google_flow" for shot in shots)
    if has_flow_shots:
        if gates.get("gate_2_5_flow_handoff") == "approved" and flow.get("handoff_created") is not True:
            errors.append("gates.gate_2_5_flow_handoff: approved status requires a real Flow handoff")
        listed_flow_ids = {
            item.get("shot_id") for item in flow.get("shots", []) if isinstance(item, dict) and is_filled(item.get("shot_id"))
        }
        expected_flow_ids = {
            shot.get("shot_id") for shot in shots if isinstance(shot, dict) and shot.get("shot_family") == "silent_google_flow"
        }
        if flow.get("handoff_created") is True and listed_flow_ids != expected_flow_ids:
            errors.append("flow.shots: handoff shot IDs must exactly match all silent_google_flow shots")
        if data.get("final_composition_started") is True:
            if not all(
                flow.get(key) is True
                for key in (
                    "handoff_created",
                    "return_received",
                    "raw_files_preserved",
                    "content_inspected",
                    "source_audio_removed",
                    "normalized_to_project_spec",
                    "action_landmark_aligned_to_action_cue",
                )
            ):
                errors.append("final_composition_started: every Flow shot must complete handoff and return acceptance first")
    if data.get("final_composition_started") is True and gate_2 != "approved":
        errors.append("final_composition_started: Gate 2 must be approved first")

    gate_3 = gates.get("gate_3")
    gate_3_evidence = as_object(gate_evidence.get("gate_3"), "gate_evidence.gate_3", errors)
    if gate_3 in {"in_progress", "waiting_user_review", "approved"} and data.get("final_composition_started") is not True:
        errors.append("gates.gate_3: final composition must have started and Flow return acceptance must pass")
    if gate_3 == "approved":
        require_true(gate_3_evidence, "user_approved_master", "gate_evidence.gate_3", errors)
        require_filled(gate_3_evidence, "approved_by", "gate_evidence.gate_3", errors)
        require_filled(gate_3_evidence, "user_approval_quote", "gate_evidence.gate_3", errors)
        require_filled(gate_3_evidence, "approved_at", "gate_evidence.gate_3", errors)
        verify_path_hash(
            project_root,
            gate_3_evidence.get("qa_manifest_path"),
            gate_3_evidence.get("qa_manifest_sha256"),
            "gate_evidence.gate_3.qa_manifest",
            errors,
            verify_files,
        )
        if verify_files and project_root is not None and is_filled(gate_3_evidence.get("qa_manifest_path")):
            qa_path = Path(str(gate_3_evidence["qa_manifest_path"]))
            if not qa_path.is_absolute():
                qa_path = project_root / qa_path
            if qa_path.is_file():
                try:
                    qa_data = load_json(qa_path)
                    errors.extend(validate_qa(qa_data, verify_files=True))
                    if qa_data.get("project_id") != data.get("project_id"):
                        errors.append("gate_evidence.gate_3.qa_manifest: project_id mismatch")
                except ValueError as exc:
                    errors.append(str(exc))
        if profile == "approved-youth-bright-profile":
            verify_path_hash(project_root, voice.get("formal_path"), voice.get("formal_sha256"), "voice.formal", errors, verify_files)
            verify_path_hash(project_root, voice.get("report_path"), voice.get("report_sha256"), "voice.report", errors, verify_files)
            require_true(voice, "sample_count_matches_master", "voice", errors)
            require_true(voice, "duration_matches_master", "voice", errors)
            if voice.get("input_sample_count") != sample_count or voice.get("output_sample_count") != sample_count:
                errors.append("voice: input/output sample counts must equal the locked master sample count")
            if not numeric(voice.get("input_duration_seconds")) or not numeric(voice.get("output_duration_seconds")):
                errors.append("voice: input/output durations must be numeric")
            elif abs(voice["input_duration_seconds"] - duration) > 0.001 or abs(voice["output_duration_seconds"] - duration) > 0.001:
                errors.append("voice: input/output durations must match the locked master duration")
            for key in ("integrated_lufs", "loudness_range_lu", "true_peak_dbtp"):
                if not numeric(voice.get(key)):
                    errors.append(f"voice.{key}: must be numeric")
            require_filled(voice, "processing_chain_version", "voice", errors)
        if bgm.get("required") is True:
            verify_path_hash(project_root, bgm.get("formal_path"), bgm.get("formal_sha256"), "bgm.formal", errors, verify_files)
            verify_path_hash(project_root, bgm.get("mix_report_path"), bgm.get("mix_report_sha256"), "bgm.mix_report", errors, verify_files)
            require_filled(bgm, "source_and_license", "bgm", errors)
            if bgm.get("license_status") not in {"approved", "user_owned", "generated_for_project"}:
                errors.append("bgm.license_status: must be approved, user_owned or generated_for_project")
            require_true(bgm, "provenance_recorded", "bgm", errors)

    publication = as_object(data.get("publication"), "publication", errors)
    publication_mode = publication.get("mode")
    if publication_mode not in {"not_started", "user_manual", "agent_operated"}:
        errors.append("publication.mode: must be not_started, user_manual or agent_operated")
    gate_4 = gates.get("gate_4_publication")
    if gate_4 in {"published", "tracking"}:
        if gate_3 != "approved":
            errors.append("gates.gate_4_publication: Gate 3 user approval must come first")
        require_true(publication, "user_confirmed_published", "publication", errors)
        require_filled(publication, "user_confirmation_quote", "publication", errors)
        require_filled(publication, "user_confirmation_at", "publication", errors)
        targets = as_list(publication.get("target_platforms"), "publication.target_platforms", errors)
        if not targets or not all(is_filled(item) for item in targets):
            errors.append("publication.target_platforms: declare the complete target platform set")
        normalized_targets = [normalize_text(item) for item in targets]
        if len(set(normalized_targets)) != len(normalized_targets):
            errors.append("publication.target_platforms: duplicate platform")
        records = as_list(publication.get("platform_records"), "publication.platform_records", errors)
        if not records:
            errors.append("publication.platform_records: published/tracking status needs platform evidence")
        record_platforms: list[str] = []
        for index, raw_record in enumerate(records):
            path = f"publication.platform_records[{index}]"
            record = as_object(raw_record, path, errors)
            platform = require_filled(record, "platform", path, errors)
            if isinstance(platform, str):
                record_platforms.append(normalize_text(platform))
            require_filled(record, "native_id", path, errors)
            require_filled(record, "published_at", path, errors)
            require_filled(record, "workbench_post_id", path, errors)
            if record.get("platform_status") != "published":
                errors.append(f"{path}.platform_status: must equal published")
            if not is_filled(record.get("source_url")) and not is_filled(record.get("source_url_note")):
                errors.append(f"{path}: provide a real source_url or an explicit source_url_note")
        if sorted(record_platforms) != sorted(normalized_targets):
            errors.append("publication.platform_records: platform set must exactly match target_platforms with no duplicates")
        if gate_4 == "tracking":
            nodes = as_list(publication.get("tracking_nodes"), "publication.tracking_nodes", errors)
            actual_nodes: set[tuple[str, str]] = set()
            for index, raw_node in enumerate(nodes):
                path = f"publication.tracking_nodes[{index}]"
                node = as_object(raw_node, path, errors)
                platform = require_filled(node, "platform", path, errors)
                horizon = require_filled(node, "horizon", path, errors)
                require_filled(node, "due_at", path, errors)
                require_filled(node, "status", path, errors)
                if isinstance(platform, str) and isinstance(horizon, str):
                    actual_nodes.add((normalize_text(platform), horizon))
            expected_nodes = {(platform, horizon) for platform in normalized_targets for horizon in REQUIRED_TRACKING_HORIZONS}
            if actual_nodes != expected_nodes:
                errors.append("publication.tracking_nodes: require exactly 24h, 72h and 7d for every target platform")
    if publication_mode == "agent_operated" and authorization.get("publication_authorized") is not True:
        errors.append("authorization.publication_authorized: must be true for agent-operated publication")

    delivery = as_object(data.get("delivery"), "delivery", errors)
    require_filled(delivery, "desktop_review_directory", "delivery", errors)
    require_true(delivery, "copy_not_move", "delivery", errors)
    require_true(delivery, "sha256_match_required", "delivery", errors)
    return errors


def validate_revision(data: dict[str, Any], verify_files: bool = False) -> list[str]:
    errors: list[str] = []
    project_root = project_root_from(data, "revision_lock", errors, verify_files)
    for key in ("project_id", "revision", "based_on_version", "rollback_version_path", "user_request", "approved_at"):
        require_filled(data, key, "revision_lock", errors)
    require_true(data, "rollback_verified_complete", "revision_lock", errors)
    require_true(data, "user_approval_confirmed", "revision_lock", errors)
    allowed = as_list(data.get("allowed_changes"), "revision_lock.allowed_changes", errors)
    forbidden = as_list(data.get("forbidden_changes"), "revision_lock.forbidden_changes", errors)
    if not allowed or not all(is_filled(value) for value in allowed):
        errors.append("revision_lock.allowed_changes: list the only allowed changes")
    if not forbidden or not all(is_filled(value) for value in forbidden):
        errors.append("revision_lock.forbidden_changes: list explicit locked areas")
    overlap = {normalize_text(value) for value in allowed} & {normalize_text(value) for value in forbidden}
    overlap.discard("")
    if overlap:
        errors.append("revision_lock: the same item cannot be both allowed and forbidden")
    fingerprints = as_list(data.get("locked_fingerprints"), "revision_lock.locked_fingerprints", errors)
    if not fingerprints:
        errors.append("revision_lock.locked_fingerprints: at least one locked fingerprint is required")
    fingerprint_roles: set[str] = set()
    for index, raw_item in enumerate(fingerprints):
        path = f"revision_lock.locked_fingerprints[{index}]"
        item = as_object(raw_item, path, errors)
        role = require_filled(item, "role", path, errors)
        if isinstance(role, str):
            if role in fingerprint_roles:
                errors.append(f"{path}.role: duplicate fingerprint role {role}")
            fingerprint_roles.add(role)
        sha = item.get("sha256")
        verify_path_hash(project_root, item.get("path"), sha, path, errors, verify_files)

    domains = as_list(data.get("lock_domains"), "revision_lock.lock_domains", errors)
    seen_domains: set[str] = set()
    change_allowed_domains: set[str] = set()
    for index, raw_domain in enumerate(domains):
        path = f"revision_lock.lock_domains[{index}]"
        domain = as_object(raw_domain, path, errors)
        name = require_filled(domain, "domain", path, errors)
        if isinstance(name, str):
            if name in seen_domains:
                errors.append(f"{path}.domain: duplicate {name}")
            seen_domains.add(name)
        applicable = domain.get("applicable") is True
        locked = domain.get("locked") is True
        change_allowed = domain.get("change_allowed") is True
        if isinstance(name, str) and applicable and change_allowed:
            change_allowed_domains.add(name)
        if applicable and locked == change_allowed:
            errors.append(f"{path}: applicable domain must be exactly one of locked or change_allowed")
        if not applicable:
            require_filled(domain, "not_applicable_reason", path, errors)
        roles = as_list(domain.get("fingerprint_roles"), f"{path}.fingerprint_roles", errors)
        invariants = as_list(domain.get("invariants"), f"{path}.invariants", errors)
        if applicable and locked:
            if not roles:
                errors.append(f"{path}.fingerprint_roles: locked domain needs fingerprints")
            missing_roles = {role for role in roles if isinstance(role, str)} - fingerprint_roles
            if missing_roles:
                errors.append(f"{path}.fingerprint_roles: missing fingerprint records {sorted(missing_roles)}")
            if not invariants:
                errors.append(f"{path}.invariants: locked domain needs explicit invariants")
        if name == "flow" and applicable and locked:
            missing = REQUIRED_FLOW_LOCK_INVARIANTS - {value for value in invariants if isinstance(value, str)}
            if missing:
                errors.append(f"{path}.invariants: missing Flow locks {sorted(missing)}")
    if seen_domains != REQUIRED_LOCK_DOMAINS:
        errors.append(f"revision_lock.lock_domains: require exactly {sorted(REQUIRED_LOCK_DOMAINS)}")

    if schema_at_least(data, 1, 1) and change_allowed_domains & {"components", "typography"}:
        visual = as_object(data.get("visual_change_contract"), "revision_lock.visual_change_contract", errors)
        flow_policy = as_object(visual.get("flow_policy"), "revision_lock.visual_change_contract.flow_policy", errors)
        require_true(flow_policy, "locked_unchanged", "revision_lock.visual_change_contract.flow_policy", errors)
        expected_flow_count = flow_policy.get("expected_clip_count")
        if not isinstance(expected_flow_count, int) or isinstance(expected_flow_count, bool) or expected_flow_count < 0:
            errors.append("revision_lock.visual_change_contract.flow_policy.expected_clip_count: must be non-negative")
        flow_invariants = as_list(
            flow_policy.get("invariants"),
            "revision_lock.visual_change_contract.flow_policy.invariants",
            errors,
        )
        required_visual_flow_invariants = {"frame_size", "crop_window", "speed", "action_order", "absolute_timing"}
        missing_visual_flow = required_visual_flow_invariants - {
            value for value in flow_invariants if isinstance(value, str)
        }
        if missing_visual_flow:
            errors.append(
                "revision_lock.visual_change_contract.flow_policy.invariants: "
                f"missing {sorted(missing_visual_flow)}"
            )

        if "components" in change_allowed_domains:
            local_scale = as_object(
                visual.get("local_component_scale_percent"),
                "revision_lock.visual_change_contract.local_component_scale_percent",
                errors,
            )
            require_exact_numeric_range(
                local_scale.get("target_range"),
                (8, 12),
                "revision_lock.visual_change_contract.local_component_scale_percent.target_range",
                errors,
            )
            if schema_at_least(data, 1, 2):
                require_exact_numeric_range(
                    local_scale.get("allowed_tuning_range"),
                    (4, 15),
                    "revision_lock.visual_change_contract.local_component_scale_percent.allowed_tuning_range",
                    errors,
                )
            for key in (
                "per_shot_records_required",
                "below_range_requires_reason",
                "outside_or_zero_requires_approved_reason",
                "center_concentration_required",
            ):
                require_true(
                    local_scale,
                    key,
                    "revision_lock.visual_change_contract.local_component_scale_percent",
                    errors,
                )

            full_scale = as_object(
                visual.get("full_illustration_inner_scale_percent"),
                "revision_lock.visual_change_contract.full_illustration_inner_scale_percent",
                errors,
            )
            require_exact_numeric_range(
                full_scale.get("target_range"),
                (4, 6),
                "revision_lock.visual_change_contract.full_illustration_inner_scale_percent.target_range",
                errors,
            )
            for key in ("per_shot_records_required", "outside_or_zero_requires_approved_reason", "stay_inside_original_frame"):
                require_true(
                    full_scale,
                    key,
                    "revision_lock.visual_change_contract.full_illustration_inner_scale_percent",
                    errors,
                )
            if full_scale.get("critical_crop_allowed") is not False:
                errors.append(
                    "revision_lock.visual_change_contract.full_illustration_inner_scale_percent.critical_crop_allowed: "
                    "must be false"
                )

            if schema_at_least(data, 1, 2):
                native_binding = as_object(
                    visual.get("native_container_text_binding"),
                    "revision_lock.visual_change_contract.native_container_text_binding",
                    errors,
                )
                for key in (
                    "required",
                    "local_compositor_required",
                    "parent_local_coordinates_required",
                    "clip_to_container_required",
                    "moves_with_parent_required",
                    "perspective_match_required",
                    "per_container_records_required",
                ):
                    require_true(
                        native_binding,
                        key,
                        "revision_lock.visual_change_contract.native_container_text_binding",
                        errors,
                    )
                if native_binding.get("floating_overlay_allowed") is not False:
                    errors.append(
                        "revision_lock.visual_change_contract.native_container_text_binding."
                        "floating_overlay_allowed: must be false"
                    )

                adaptive_fit = as_object(
                    visual.get("adaptive_composition_fit"),
                    "revision_lock.visual_change_contract.adaptive_composition_fit",
                    errors,
                )
                require_true(adaptive_fit, "required", "revision_lock.visual_change_contract.adaptive_composition_fit", errors)
                if adaptive_fit.get("fit_mode") != "contain":
                    errors.append(
                        "revision_lock.visual_change_contract.adaptive_composition_fit.fit_mode: must equal contain"
                    )
                require_exact_numeric_range(
                    adaptive_fit.get("target_scale_change_percent_range"),
                    (8, 12),
                    "revision_lock.visual_change_contract.adaptive_composition_fit.target_scale_change_percent_range",
                    errors,
                )
                require_exact_numeric_range(
                    adaptive_fit.get("allowed_tuning_percent_range"),
                    (4, 15),
                    "revision_lock.visual_change_contract.adaptive_composition_fit.allowed_tuning_percent_range",
                    errors,
                )
                hard_bounds = validate_pixel_bounds(
                    adaptive_fit.get("hard_safe_bounds_px"),
                    "revision_lock.visual_change_contract.adaptive_composition_fit.hard_safe_bounds_px",
                    errors,
                )
                preferred_bounds = validate_pixel_bounds(
                    adaptive_fit.get("preferred_stage_bounds_px"),
                    "revision_lock.visual_change_contract.adaptive_composition_fit.preferred_stage_bounds_px",
                    errors,
                )
                if hard_bounds and preferred_bounds and not (
                    hard_bounds["left"] <= preferred_bounds["left"]
                    and hard_bounds["top"] <= preferred_bounds["top"]
                    and hard_bounds["right"] >= preferred_bounds["right"]
                    and hard_bounds["bottom"] >= preferred_bounds["bottom"]
                ):
                    errors.append(
                        "revision_lock.visual_change_contract.adaptive_composition_fit: "
                        "preferred stage must stay inside hard safe bounds"
                    )
                require_exact_numeric_range(
                    adaptive_fit.get("preferred_primary_axis_fill_ratio_range"),
                    (0.72, 0.9),
                    "revision_lock.visual_change_contract.adaptive_composition_fit.preferred_primary_axis_fill_ratio_range",
                    errors,
                )
                for key, expected in (("maximum_width_fill_ratio", 0.9), ("maximum_height_fill_ratio", 0.92), ("maximum_center_offset_x_px", 90)):
                    if adaptive_fit.get(key) != expected:
                        errors.append(
                            f"revision_lock.visual_change_contract.adaptive_composition_fit.{key}: must equal {expected}"
                        )
                for key in ("per_shot_tuning_required", "safe_region_and_main_visual_protection_required"):
                    require_true(
                        adaptive_fit,
                        key,
                        "revision_lock.visual_change_contract.adaptive_composition_fit",
                        errors,
                    )

        if "typography" in change_allowed_domains:
            caption_move = as_object(
                visual.get("caption_centerward_move"),
                "revision_lock.visual_change_contract.caption_centerward_move",
                errors,
            )
            for key in (
                "required",
                "baseline_manifest_required",
                "per_caption_baseline_and_final_position_required",
                "per_shot_avoidance_required",
                "platform_safe_area_required",
                "zero_or_reverse_move_requires_approved_reason",
                "explanatory_typography_locked",
            ):
                require_true(caption_move, key, "revision_lock.visual_change_contract.caption_centerward_move", errors)
            minimum_increase = caption_move.get("minimum_font_increase_px")
            font_change_required = caption_move.get("font_size_change_required")
            if font_change_required is True and (not numeric(minimum_increase) or minimum_increase <= 0):
                errors.append(
                    "revision_lock.visual_change_contract.caption_centerward_move.minimum_font_increase_px: "
                    "must be greater than zero when font-size change is required"
                )
            elif font_change_required is False:
                if minimum_increase != 0:
                    errors.append(
                        "revision_lock.visual_change_contract.caption_centerward_move.minimum_font_increase_px: "
                        "must be zero when font-size change is outside the approved scope"
                    )
                require_filled(
                    caption_move,
                    "font_size_change_exception_reason",
                    "revision_lock.visual_change_contract.caption_centerward_move",
                    errors,
                )
            elif font_change_required is not True:
                errors.append(
                    "revision_lock.visual_change_contract.caption_centerward_move.font_size_change_required: "
                    "must be boolean"
                )
            if "explanatory_typography_manifest" not in fingerprint_roles:
                errors.append(
                    "revision_lock.locked_fingerprints: typography changes require an "
                    "explanatory_typography_manifest fingerprint"
                )

            contrast = as_object(
                visual.get("caption_contrast_strategy"),
                "revision_lock.visual_change_contract.caption_contrast_strategy",
                errors,
            )
            for key in ("foreground_style", "edge_or_backing_style", "keyword_style"):
                require_filled(contrast, key, "revision_lock.visual_change_contract.caption_contrast_strategy", errors)
            contrast_target = contrast.get("minimum_contrast_ratio_target")
            if not numeric(contrast_target) or contrast_target < 4.5:
                errors.append(
                    "revision_lock.visual_change_contract.caption_contrast_strategy.minimum_contrast_ratio_target: "
                    "must be at least 4.5"
                )
            require_true(
                contrast,
                "style_matches_editorial_animation",
                "revision_lock.visual_change_contract.caption_contrast_strategy",
                errors,
            )

        protection = as_object(
            visual.get("main_visual_protection"),
            "revision_lock.visual_change_contract.main_visual_protection",
            errors,
        )
        protected_roles = {
            value for value in as_list(
                protection.get("protected_roles"),
                "revision_lock.visual_change_contract.main_visual_protection.protected_roles",
                errors,
            ) if isinstance(value, str)
        }
        required_roles = {"people", "core_actions", "result_states", "required_explanatory_typography"}
        if not required_roles.issubset(protected_roles):
            errors.append(
                "revision_lock.visual_change_contract.main_visual_protection.protected_roles: "
                f"missing {sorted(required_roles - protected_roles)}"
            )
        if protection.get("overlap_allowed") is not False:
            errors.append("revision_lock.visual_change_contract.main_visual_protection.overlap_allowed: must be false")

    if verify_files and project_root is not None:
        rollback = Path(str(data.get("rollback_version_path", "")))
        if not rollback.is_absolute():
            rollback = project_root / rollback
        if not rollback.exists():
            errors.append(f"revision_lock.rollback_version_path: does not exist: {rollback}")
    checks = as_list(data.get("required_regression_checks"), "revision_lock.required_regression_checks", errors)
    required_checks = {
        "locked_fingerprint_mismatch_count_is_zero",
        "changed_continuous_ranges_reviewed",
        "full_encoded_master_watched",
    }
    if not required_checks.issubset({value for value in checks if isinstance(value, str)}):
        errors.append("revision_lock.required_regression_checks: missing mandatory regression checks")
    return errors


def validate_gate2_manifest(data: dict[str, Any], verify_files: bool = False) -> list[str]:
    errors: list[str] = []
    project_root = project_root_from(data, "gate2_manifest", errors, verify_files)
    require_filled(data, "project_id", "gate2_manifest", errors)
    if data.get("status") != "approved":
        errors.append("gate2_manifest.status: must equal approved to unlock production")
    shot_ids = as_list(data.get("all_shot_ids"), "gate2_manifest.all_shot_ids", errors)
    normalized_ids = [str(value) for value in shot_ids if is_filled(value)]
    if not normalized_ids or len(normalized_ids) != len(shot_ids):
        errors.append("gate2_manifest.all_shot_ids: every shot ID must be filled")
    if len(set(normalized_ids)) != len(normalized_ids):
        errors.append("gate2_manifest.all_shot_ids: duplicate shot ID")
    if schema_at_least(data, 2, 0):
        if "expected_shot_count" in data:
            errors.append("gate2_manifest.expected_shot_count: fixed target field is forbidden in schema 2.0")
        if data.get("actual_visual_unit_count") != len(normalized_ids):
            errors.append("gate2_manifest.actual_visual_unit_count: must equal the derived all_shot_ids count")
        if data.get("reviewed_visual_unit_count") != len(normalized_ids):
            errors.append("gate2_manifest.reviewed_visual_unit_count: every actual visual unit must be reviewed")
    else:
        if data.get("expected_shot_count") != len(normalized_ids):
            errors.append("gate2_manifest.expected_shot_count: must equal all_shot_ids count")
        if data.get("reviewed_shot_count") != len(normalized_ids):
            errors.append("gate2_manifest.reviewed_shot_count: every shot must be reviewed before approval")
    entries = as_list(data.get("shot_entries"), "gate2_manifest.shot_entries", errors)
    entry_ids: list[str] = []
    for index, raw_entry in enumerate(entries):
        path = f"gate2_manifest.shot_entries[{index}]"
        entry = as_object(raw_entry, path, errors)
        shot_id = require_filled(entry, "shot_id", path, errors)
        if isinstance(shot_id, str):
            entry_ids.append(shot_id)
        family = entry.get("shot_family")
        if family not in ALLOWED_FAMILIES:
            errors.append(f"{path}.shot_family: invalid family")
        for role, path_key, sha_key in (
            ("contract", "contract_path", "contract_sha256"),
            ("script_txt", "script_txt_path", "script_txt_sha256"),
            ("keyframe", "keyframe_path", "keyframe_sha256"),
        ):
            verify_path_hash(project_root, entry.get(path_key), entry.get(sha_key), f"{path}.{role}", errors, verify_files)
        if family == "independent_component_animation":
            require_true(entry, "multi_stage_keyframe_required", path, errors)
            require_true(entry, "multi_stage_keyframe_present", path, errors)
            require_true(entry, "independent_layer_plan_present", path, errors)
            verify_path_hash(
                project_root,
                entry.get("layer_plan_path"),
                entry.get("layer_plan_sha256"),
                f"{path}.layer_plan",
                errors,
                verify_files,
            )
            if schema_at_least(data, 1, 2):
                require_true(entry, "container_native_text_plan_present", path, errors)
                require_true(entry, "adaptive_composition_fit_plan_present", path, errors)
        if verify_files and project_root is not None and is_filled(entry.get("contract_path")):
            contract_path = Path(str(entry["contract_path"]))
            if not contract_path.is_absolute():
                contract_path = project_root / contract_path
            if contract_path.is_file():
                try:
                    contract = load_json(contract_path)
                    contract_errors = validate_shot_contract(
                        contract,
                        f"{path}.contract",
                        require_native_fit=schema_at_least(data, 1, 2),
                    )
                    errors.extend(contract_errors)
                    if contract.get("shot_id") != shot_id:
                        errors.append(f"{path}.contract: shot_id does not match manifest")
                    if contract.get("gate_2_status") != "approved":
                        errors.append(f"{path}.contract: every shot must be approved inside the whole-package Gate 2")
                except ValueError as exc:
                    errors.append(str(exc))
    if sorted(entry_ids) != sorted(normalized_ids):
        errors.append("gate2_manifest.shot_entries: must cover every all_shot_ids entry exactly once")
    artifacts = as_object(data.get("whole_film_artifacts"), "gate2_manifest.whole_film_artifacts", errors)
    required_gate2_artifacts = REQUIRED_GATE2_WHOLE_FILM_ARTIFACTS
    if schema_at_least(data, 1, 2):
        required_gate2_artifacts += GATE2_1_2_WHOLE_FILM_ARTIFACTS
    if schema_at_least(data, 2, 0):
        required_gate2_artifacts += GATE2_2_0_WHOLE_FILM_ARTIFACTS
    for key in required_gate2_artifacts:
        item = as_object(artifacts.get(key), f"gate2_manifest.whole_film_artifacts.{key}", errors)
        verify_path_hash(
            project_root,
            item.get("path"),
            item.get("sha256"),
            f"gate2_manifest.whole_film_artifacts.{key}",
            errors,
            verify_files,
        )
    approval = as_object(data.get("approval"), "gate2_manifest.approval", errors)
    require_true(approval, "whole_package_user_approved", "gate2_manifest.approval", errors)
    if schema_at_least(data, 2, 0):
        require_true(approval, "director_interpretation_user_approved", "gate2_manifest.approval", errors)
        require_true(approval, "visual_storyboard_user_approved", "gate2_manifest.approval", errors)
        require_true(approval, "full_voiced_animatic_user_approved", "gate2_manifest.approval", errors)
        if approval.get("brand_06_signoff") != "pass":
            errors.append("gate2_manifest.approval.brand_06_signoff: must equal pass")
        if approval.get("technical_07_signoff") != "pass":
            errors.append("gate2_manifest.approval.technical_07_signoff: must equal pass")
    require_filled(approval, "approved_by", "gate2_manifest.approval", errors)
    require_filled(approval, "user_approval_quote", "gate2_manifest.approval", errors)
    require_filled(approval, "approved_at", "gate2_manifest.approval", errors)
    return errors


def validate_caption_audit_record(
    record: dict[str, Any],
    path: str,
    frame_width: Any,
    frame_height: Any,
) -> list[str]:
    errors: list[str] = []
    require_filled(record, "cue_id", path, errors)
    require_filled(record, "shot_id", path, errors)
    baseline = record.get("baseline_font_px")
    final = record.get("final_font_px")
    required_increase = record.get("required_increase_px")
    exception = record.get("exception_approved") is True
    if not all(numeric(value) for value in (baseline, final, required_increase)):
        errors.append(f"{path}: baseline/final/required font values must be numeric")
    elif final < baseline + required_increase and not exception:
        errors.append(f"{path}: caption font did not meet the required increase")

    coordinate_keys = ("baseline_x_px", "baseline_y_px", "final_x_px", "final_y_px")
    coordinates = [record.get(key) for key in coordinate_keys]
    for key, value in zip(coordinate_keys, coordinates):
        if not numeric(value):
            errors.append(f"{path}.{key}: must be numeric")
    if numeric(frame_width) and numeric(frame_height) and all(numeric(value) for value in coordinates):
        baseline_x, baseline_y, final_x, final_y = coordinates
        for key, value, maximum in (
            ("baseline_x_px", baseline_x, frame_width),
            ("final_x_px", final_x, frame_width),
            ("baseline_y_px", baseline_y, frame_height),
            ("final_y_px", final_y, frame_height),
        ):
            if not 0 <= value <= maximum:
                errors.append(f"{path}.{key}: must stay inside the final encoded frame")
        center_x = frame_width / 2
        center_y = frame_height / 2
        baseline_distance = math.hypot(baseline_x - center_x, baseline_y - center_y)
        final_distance = math.hypot(final_x - center_x, final_y - center_y)
        calculated_centerward = baseline_distance - final_distance
        reported_centerward = record.get("centerward_offset_px")
        if not numeric(reported_centerward):
            errors.append(f"{path}.centerward_offset_px: must be numeric")
        elif abs(reported_centerward - calculated_centerward) > 0.5:
            errors.append(
                f"{path}.centerward_offset_px: must match the baseline/final coordinate calculation"
            )
        if calculated_centerward <= 0 and not exception:
            errors.append(f"{path}: zero or reverse centerward move needs an approved exception")
    elif not numeric(record.get("centerward_offset_px")):
        errors.append(f"{path}.centerward_offset_px: must be numeric")

    if exception:
        require_filled(record, "exception_reason", path, errors)
        require_filled(record, "exception_approved_at", path, errors)
    for key in (
        "single_line",
        "overflow_absent",
        "safe_area_clear",
        "main_visual_clear",
        "explanatory_typography_clear",
    ):
        require_true(record, key, path, errors)
    return errors


def validate_native_container_text_record(record: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    for key in ("container_id", "shot_id", "parent_layer_id"):
        require_filled(record, key, path, errors)
    if record.get("text_source") != "local_compositor":
        errors.append(f"{path}.text_source: must equal local_compositor")
    if record.get("coordinate_space") != "parent_local":
        errors.append(f"{path}.coordinate_space: must equal parent_local")
    validate_normalized_rect(record.get("text_region_normalized"), f"{path}.text_region_normalized", errors)
    padding = record.get("padding_percent")
    if not numeric(padding) or not 0 <= padding <= 20:
        errors.append(f"{path}.padding_percent: must be between 0 and 20")
    if record.get("perspective_mode") != "matched_parent":
        errors.append(f"{path}.perspective_mode: must equal matched_parent")
    minimum_font = record.get("minimum_font_px")
    if not numeric(minimum_font) or minimum_font < 32:
        errors.append(f"{path}.minimum_font_px: must be at least 32")
    for key in (
        "clip_to_container",
        "moves_with_parent",
        "text_inside_container",
        "overflow_absent",
        "perspective_matched",
        "floating_overlay_absent",
        "readable",
    ):
        require_true(record, key, path, errors)
    require_filled(record, "evidence_ref", path, errors)
    return errors


def validate_adaptive_fit_record(
    record: dict[str, Any],
    path: str,
    frame_width: Any,
    frame_height: Any,
    hard_safe_bounds: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    require_filled(record, "shot_id", path, errors)
    baseline = record.get("baseline_scale")
    final = record.get("final_scale")
    change = record.get("scale_change_percent")
    exception = record.get("exception_approved") is True
    if not all(numeric(value) for value in (baseline, final, change)) or baseline <= 0 or final <= 0:
        errors.append(f"{path}: baseline_scale, final_scale and scale_change_percent must be positive/numeric")
    else:
        calculated = (final / baseline - 1) * 100
        if abs(calculated - change) > 0.1:
            errors.append(f"{path}.scale_change_percent: must match baseline_scale and final_scale")
        if not 4 <= change <= 15 and not exception:
            errors.append(f"{path}: scale outside the 4-15 tuning range needs explicit approval")
        elif not 8 <= change <= 12 and not exception:
            errors.append(f"{path}: scale outside the 8-12 target range needs an approved per-shot reason")

    bbox = as_object(record.get("final_bbox_px"), f"{path}.final_bbox_px", errors)
    bbox_values = {key: bbox.get(key) for key in ("x", "y", "width", "height")}
    if not all(numeric(value) for value in bbox_values.values()):
        errors.append(f"{path}.final_bbox_px: x, y, width and height must be numeric")
    elif bbox_values["width"] <= 0 or bbox_values["height"] <= 0:
        errors.append(f"{path}.final_bbox_px: width and height must be greater than zero")
    else:
        right = bbox_values["x"] + bbox_values["width"]
        bottom = bbox_values["y"] + bbox_values["height"]
        if numeric(frame_width) and numeric(frame_height):
            if bbox_values["x"] < 0 or bbox_values["y"] < 0 or right > frame_width or bottom > frame_height:
                errors.append(f"{path}.final_bbox_px: must stay inside the encoded frame")
            reported_width_fill = record.get("width_fill_ratio")
            reported_height_fill = record.get("height_fill_ratio")
            calculated_width_fill = bbox_values["width"] / frame_width
            calculated_height_fill = bbox_values["height"] / frame_height
            if not numeric(reported_width_fill) or abs(reported_width_fill - calculated_width_fill) > 0.005:
                errors.append(f"{path}.width_fill_ratio: must match final_bbox_px/frame width")
            elif reported_width_fill > 0.9:
                errors.append(f"{path}.width_fill_ratio: must not exceed 0.9")
            if not numeric(reported_height_fill) or abs(reported_height_fill - calculated_height_fill) > 0.005:
                errors.append(f"{path}.height_fill_ratio: must match final_bbox_px/frame height")
            elif reported_height_fill > 0.92:
                errors.append(f"{path}.height_fill_ratio: must not exceed 0.92")
        if hard_safe_bounds and all(numeric(hard_safe_bounds.get(key)) for key in ("left", "top", "right", "bottom")):
            if (
                bbox_values["x"] < hard_safe_bounds["left"]
                or bbox_values["y"] < hard_safe_bounds["top"]
                or right > hard_safe_bounds["right"]
                or bottom > hard_safe_bounds["bottom"]
            ):
                errors.append(f"{path}.final_bbox_px: must stay inside the hard safe bounds")

    primary_fill = record.get("primary_axis_fill_ratio")
    if not numeric(primary_fill):
        errors.append(f"{path}.primary_axis_fill_ratio: must be numeric")
    elif not 0.72 <= primary_fill <= 0.9 and not exception:
        errors.append(f"{path}.primary_axis_fill_ratio: outside 0.72-0.9 needs explicit approval")
    center_offset = record.get("center_offset_x_px")
    if not numeric(center_offset):
        errors.append(f"{path}.center_offset_x_px: must be numeric")
    elif abs(center_offset) > 90 and not exception:
        errors.append(f"{path}.center_offset_x_px: over 90px needs explicit approval")
    for key in (
        "critical_crop_absent",
        "visual_drift_absent",
        "main_visual_clear",
        "comfortable_density",
    ):
        require_true(record, key, path, errors)
    if exception:
        require_filled(record, "exception_reason", path, errors)
        require_filled(record, "exception_approved_at", path, errors)
    require_filled(record, "evidence_ref", path, errors)
    return errors


def validate_qa(data: dict[str, Any], verify_files: bool = False) -> list[str]:
    errors: list[str] = []
    project_root = project_root_from(data, "qa", errors, verify_files)
    for key in ("project_id", "version", "master_path"):
        require_filled(data, key, "qa", errors)
    sha = data.get("master_sha256")
    if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
        errors.append("qa.master_sha256: must be a 64-character SHA-256")
    verify_path_hash(project_root, data.get("master_path"), sha, "qa.master", errors, verify_files)
    if data.get("status") != "pass":
        errors.append("qa.status: must equal pass")
    checks = as_object(data.get("checks"), "qa.checks", errors)
    if schema_at_least(data, 2, 0):
        required_qa_checks = REQUIRED_QA_CHECKS + tuple(sorted(QA_2_0_CHECKS))
    elif schema_at_least(data, 1, 2):
        required_qa_checks = REQUIRED_QA_CHECKS
    elif schema_at_least(data, 1, 1):
        required_qa_checks = tuple(key for key in REQUIRED_QA_CHECKS if key not in QA_1_2_CHECKS)
    else:
        required_qa_checks = tuple(
            key for key in REQUIRED_QA_CHECKS if key not in QA_1_1_CHECKS | QA_1_2_CHECKS
        )
    for key in required_qa_checks:
        if checks.get(key) is not True:
            errors.append(f"qa.checks.{key}: must be true")
    metrics = as_object(data.get("metrics"), "qa.metrics", errors)
    expected = as_object(data.get("expected_output"), "qa.expected_output", errors)
    zero_metrics = [
        "decode_error_count",
        "locked_fingerprint_mismatch_count",
        "desktop_hash_mismatch_count",
        "black_segment_count",
        "unexpected_silence_count",
    ]
    if schema_at_least(data, 1, 1):
        zero_metrics.extend((
            "asset_scale_violation_count",
            "caption_overflow_count",
            "caption_safe_area_violation_count",
            "caption_main_visual_overlap_count",
        ))
    if schema_at_least(data, 1, 2):
        zero_metrics.extend((
            "native_container_text_violation_count",
            "adaptive_composition_fit_violation_count",
        ))
    if schema_at_least(data, 2, 0):
        zero_metrics.extend((
            "exact_information_routed_to_pure_i2v_count",
            "official_source_missing_count",
            "sourced_chart_footer_missing_count",
            "i2v_duration_shortfall_without_continuation_count",
            "forced_slow_freeze_loop_or_static_flash_count",
            "previous_bgm_reuse_count",
            "official_evidence_not_design_integrated_count",
            "empty_background_text_only_count",
        ))
    for key in zero_metrics:
        if metrics.get(key) != 0:
            errors.append(f"qa.metrics.{key}: must equal 0")
    if not numeric(metrics.get("duration_seconds")) or metrics.get("duration_seconds", 0) <= 0:
        errors.append("qa.metrics.duration_seconds: must be greater than zero")
    if not isinstance(metrics.get("frame_count"), int) or metrics.get("frame_count", 0) <= 0:
        errors.append("qa.metrics.frame_count: must be a positive integer")
    for key in ("width", "height", "fps", "frame_count"):
        if metrics.get(key) != expected.get(key):
            errors.append(f"qa.metrics.{key}: must match expected_output.{key}")
    expected_duration = expected.get("duration_seconds")
    tolerance = expected.get("duration_tolerance_seconds")
    if not numeric(expected_duration) or expected_duration <= 0:
        errors.append("qa.expected_output.duration_seconds: must be greater than zero")
    if not numeric(tolerance) or tolerance < 0:
        errors.append("qa.expected_output.duration_tolerance_seconds: must be non-negative")
    if numeric(expected_duration) and numeric(tolerance) and numeric(metrics.get("duration_seconds")):
        if abs(metrics["duration_seconds"] - expected_duration) > tolerance:
            errors.append("qa.metrics.duration_seconds: outside approved duration tolerance")
    for metric_key, range_key in (("integrated_lufs", "integrated_lufs_range"), ("loudness_range_lu", "loudness_range_lu")):
        value = metrics.get(metric_key)
        bounds = expected.get(range_key)
        if not numeric(value):
            errors.append(f"qa.metrics.{metric_key}: must be numeric")
        elif not isinstance(bounds, list) or len(bounds) != 2 or not all(numeric(item) for item in bounds):
            errors.append(f"qa.expected_output.{range_key}: must be a numeric [min, max]")
        elif not bounds[0] <= value <= bounds[1]:
            errors.append(f"qa.metrics.{metric_key}: outside approved range")
    true_peak = metrics.get("true_peak_dbtp")
    true_peak_max = expected.get("true_peak_dbtp_max")
    if not numeric(true_peak) or not numeric(true_peak_max):
        errors.append("qa: true_peak_dbtp and true_peak_dbtp_max must be numeric")
    elif true_peak > true_peak_max:
        errors.append("qa.metrics.true_peak_dbtp: exceeds approved maximum")
    minimum_font_keys = ["minimum_information_label_font_px", "minimum_explanatory_font_px"]
    if schema_at_least(data, 1, 1):
        minimum_font_keys.append("minimum_caption_font_px")
    for key in minimum_font_keys:
        actual = metrics.get(key)
        minimum = expected.get(key)
        if not numeric(actual) or not numeric(minimum) or actual < minimum:
            errors.append(f"qa.metrics.{key}: must meet the approved mobile-readability minimum")
    if metrics.get("unreadable_corner_text_count") != 0:
        errors.append("qa.metrics.unreadable_corner_text_count: must equal 0")
    if schema_at_least(data, 1, 1):
        asset_audit = as_object(data.get("asset_class_scale_audit"), "qa.asset_class_scale_audit", errors)
        for key in (
            "flow_locked_unchanged",
            "local_component_per_shot_records_complete",
            "local_component_center_concentrated",
            "full_illustration_inside_original_frame",
            "scale_exception_records_complete",
        ):
            require_true(asset_audit, key, "qa.asset_class_scale_audit", errors)
        require_exact_numeric_range(
            asset_audit.get("local_component_target_scale_percent_range"),
            (8, 12),
            "qa.asset_class_scale_audit.local_component_target_scale_percent_range",
            errors,
        )
        require_exact_numeric_range(
            asset_audit.get("full_illustration_target_scale_percent_range"),
            (4, 6),
            "qa.asset_class_scale_audit.full_illustration_target_scale_percent_range",
            errors,
        )
        for key in (
            "flow_unauthorized_change_count",
            "clipping_event_count",
            "composition_break_count",
        ):
            if asset_audit.get(key) != 0:
                errors.append(f"qa.asset_class_scale_audit.{key}: must equal 0")
        for key in (
            "flow_expected_count",
            "flow_compared_count",
            "local_component_expected_shots",
            "local_component_shots_reviewed",
            "full_illustration_expected_shots",
            "full_illustration_shots_reviewed",
            "scale_exception_count",
        ):
            value = asset_audit.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"qa.asset_class_scale_audit.{key}: must be a non-negative integer")
        for expected_key, actual_key in (
            ("flow_expected_count", "flow_compared_count"),
            ("local_component_expected_shots", "local_component_shots_reviewed"),
            ("full_illustration_expected_shots", "full_illustration_shots_reviewed"),
        ):
            if asset_audit.get(expected_key) != asset_audit.get(actual_key):
                errors.append(f"qa.asset_class_scale_audit.{actual_key}: must equal {expected_key}")
        asset_manifest = load_verified_evidence_manifest(
            project_root,
            asset_audit.get("asset_record_manifest_path"),
            asset_audit.get("asset_record_manifest_sha256"),
            "qa.asset_class_scale_audit.asset_record_manifest",
            errors,
            verify_files,
        )
        if asset_manifest is not None:
            asset_records = as_list(asset_manifest.get("records"), "qa.asset_record_manifest.records", errors)
            expected_asset_records = sum(
                value if isinstance(value, int) and not isinstance(value, bool) else 0
                for key in ("flow_expected_count", "local_component_expected_shots", "full_illustration_expected_shots")
                for value in (asset_audit.get(key),)
            )
            if len(asset_records) != expected_asset_records:
                errors.append("qa.asset_record_manifest.records: count must equal all expected visual assets")
            seen_asset_shots: set[str] = set()
            for index, raw_record in enumerate(asset_records):
                path = f"qa.asset_record_manifest.records[{index}]"
                record = as_object(raw_record, path, errors)
                shot_id = require_filled(record, "shot_id", path, errors)
                family = require_filled(record, "family", path, errors)
                if isinstance(shot_id, str):
                    if shot_id in seen_asset_shots:
                        errors.append(f"{path}.shot_id: duplicate {shot_id}")
                    seen_asset_shots.add(shot_id)
                if family not in ALLOWED_FAMILIES:
                    errors.append(f"{path}.family: unsupported family {family!r}")
                scale_change = record.get("scale_change_percent")
                exception = record.get("exception_approved") is True
                if not numeric(scale_change):
                    errors.append(f"{path}.scale_change_percent: must be numeric")
                elif family == "silent_google_flow" and scale_change != 0:
                    errors.append(f"{path}.scale_change_percent: Flow must remain 0")
                elif family == "independent_component_animation" and not (8 <= scale_change <= 12) and not exception:
                    errors.append(f"{path}: local-component scale outside 8-12 needs an approved exception")
                elif family == "full_editorial_illustration" and not (4 <= scale_change <= 6) and not exception:
                    errors.append(f"{path}: full-illustration scale outside 4-6 needs an approved exception")
                if exception:
                    require_filled(record, "exception_reason", path, errors)
                    require_filled(record, "exception_approved_at", path, errors)

        if schema_at_least(data, 1, 2):
            native_audit = as_object(
                data.get("native_container_text_audit"),
                "qa.native_container_text_audit",
                errors,
            )
            for key in (
                "per_container_records_complete",
                "local_compositor_used",
                "parent_local_coordinates_used",
            ):
                require_true(native_audit, key, "qa.native_container_text_audit", errors)
            for expected_key, reviewed_key in ((
                "communicative_container_expected_count",
                "communicative_container_reviewed_count",
            ),):
                expected_count = native_audit.get(expected_key)
                reviewed_count = native_audit.get(reviewed_key)
                if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
                    errors.append(f"qa.native_container_text_audit.{expected_key}: must be non-negative")
                if not isinstance(reviewed_count, int) or isinstance(reviewed_count, bool) or reviewed_count < 0:
                    errors.append(f"qa.native_container_text_audit.{reviewed_key}: must be non-negative")
                if expected_count != reviewed_count:
                    errors.append(f"qa.native_container_text_audit.{reviewed_key}: must equal {expected_key}")
            for key in (
                "parent_binding_failure_count",
                "outside_container_count",
                "clipping_mask_failure_count",
                "perspective_mismatch_count",
                "text_overflow_count",
                "floating_overlay_count",
                "parent_motion_desync_count",
                "unreadable_count",
            ):
                if native_audit.get(key) != 0:
                    errors.append(f"qa.native_container_text_audit.{key}: must equal 0")
            native_manifest = load_verified_evidence_manifest(
                project_root,
                native_audit.get("records_manifest_path"),
                native_audit.get("records_manifest_sha256"),
                "qa.native_container_text_audit.records_manifest",
                errors,
                verify_files,
            )
            if native_manifest is not None:
                native_records = as_list(native_manifest.get("records"), "qa.native_container_text_manifest.records", errors)
                if len(native_records) != native_audit.get("communicative_container_expected_count"):
                    errors.append(
                        "qa.native_container_text_manifest.records: count must equal communicative_container_expected_count"
                    )
                seen_containers: set[str] = set()
                for index, raw_record in enumerate(native_records):
                    path = f"qa.native_container_text_manifest.records[{index}]"
                    record = as_object(raw_record, path, errors)
                    container_id = record.get("container_id")
                    if isinstance(container_id, str):
                        if container_id in seen_containers:
                            errors.append(f"{path}.container_id: duplicate {container_id}")
                        seen_containers.add(container_id)
                    errors.extend(validate_native_container_text_record(record, path))

            fit_audit = as_object(
                data.get("adaptive_composition_fit_audit"),
                "qa.adaptive_composition_fit_audit",
                errors,
            )
            require_true(fit_audit, "per_shot_records_complete", "qa.adaptive_composition_fit_audit", errors)
            require_true(fit_audit, "exception_records_complete", "qa.adaptive_composition_fit_audit", errors)
            if fit_audit.get("fit_mode") != "contain":
                errors.append("qa.adaptive_composition_fit_audit.fit_mode: must equal contain")
            require_exact_numeric_range(
                fit_audit.get("target_scale_change_percent_range"),
                (8, 12),
                "qa.adaptive_composition_fit_audit.target_scale_change_percent_range",
                errors,
            )
            require_exact_numeric_range(
                fit_audit.get("allowed_tuning_percent_range"),
                (4, 15),
                "qa.adaptive_composition_fit_audit.allowed_tuning_percent_range",
                errors,
            )
            hard_safe_bounds = validate_pixel_bounds(
                fit_audit.get("hard_safe_bounds_px"),
                "qa.adaptive_composition_fit_audit.hard_safe_bounds_px",
                errors,
            )
            preferred_stage_bounds = validate_pixel_bounds(
                fit_audit.get("preferred_stage_bounds_px"),
                "qa.adaptive_composition_fit_audit.preferred_stage_bounds_px",
                errors,
            )
            if hard_safe_bounds and preferred_stage_bounds and not (
                hard_safe_bounds["left"] <= preferred_stage_bounds["left"]
                and hard_safe_bounds["top"] <= preferred_stage_bounds["top"]
                and hard_safe_bounds["right"] >= preferred_stage_bounds["right"]
                and hard_safe_bounds["bottom"] >= preferred_stage_bounds["bottom"]
            ):
                errors.append(
                    "qa.adaptive_composition_fit_audit: preferred stage must stay inside hard safe bounds"
                )
            for expected_key, reviewed_key in (("local_component_expected_shots", "local_component_shots_reviewed"),):
                expected_count = fit_audit.get(expected_key)
                reviewed_count = fit_audit.get(reviewed_key)
                if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 0:
                    errors.append(f"qa.adaptive_composition_fit_audit.{expected_key}: must be non-negative")
                if not isinstance(reviewed_count, int) or isinstance(reviewed_count, bool) or reviewed_count < 0:
                    errors.append(f"qa.adaptive_composition_fit_audit.{reviewed_key}: must be non-negative")
                if expected_count != reviewed_count:
                    errors.append(f"qa.adaptive_composition_fit_audit.{reviewed_key}: must equal {expected_key}")
            for key in (
                "safe_bounds_violation_count",
                "critical_crop_count",
                "visual_drift_count",
                "main_visual_overlap_count",
                "uncomfortable_density_count",
            ):
                if fit_audit.get(key) != 0:
                    errors.append(f"qa.adaptive_composition_fit_audit.{key}: must equal 0")
            underfilled = fit_audit.get("underfilled_primary_visual_count")
            if not isinstance(underfilled, int) or isinstance(underfilled, bool) or underfilled < 0:
                errors.append(
                    "qa.adaptive_composition_fit_audit.underfilled_primary_visual_count: must be non-negative"
                )
            fit_manifest = load_verified_evidence_manifest(
                project_root,
                fit_audit.get("records_manifest_path"),
                fit_audit.get("records_manifest_sha256"),
                "qa.adaptive_composition_fit_audit.records_manifest",
                errors,
                verify_files,
            )
            if fit_manifest is not None:
                fit_records = as_list(fit_manifest.get("records"), "qa.adaptive_composition_fit_manifest.records", errors)
                if len(fit_records) != fit_audit.get("local_component_expected_shots"):
                    errors.append(
                        "qa.adaptive_composition_fit_manifest.records: count must equal local_component_expected_shots"
                    )
                seen_fit_shots: set[str] = set()
                underfilled_records = 0
                for index, raw_record in enumerate(fit_records):
                    path = f"qa.adaptive_composition_fit_manifest.records[{index}]"
                    record = as_object(raw_record, path, errors)
                    shot_id = record.get("shot_id")
                    if isinstance(shot_id, str):
                        if shot_id in seen_fit_shots:
                            errors.append(f"{path}.shot_id: duplicate {shot_id}")
                        seen_fit_shots.add(shot_id)
                    if numeric(record.get("primary_axis_fill_ratio")) and not 0.72 <= record["primary_axis_fill_ratio"] <= 0.9:
                        underfilled_records += 1
                    errors.extend(
                        validate_adaptive_fit_record(
                            record,
                            path,
                            expected.get("width"),
                            expected.get("height"),
                            hard_safe_bounds,
                        )
                    )
                if underfilled_records != underfilled:
                    errors.append(
                        "qa.adaptive_composition_fit_audit.underfilled_primary_visual_count: "
                        "must match the evidence records"
                    )

        caption_audit = as_object(
            data.get("caption_visual_hierarchy_audit"),
            "qa.caption_visual_hierarchy_audit",
            errors,
        )
        if caption_audit.get("minimum_rendered_font_px") != metrics.get("minimum_caption_font_px"):
            errors.append(
                "qa.caption_visual_hierarchy_audit.minimum_rendered_font_px: "
                "must match qa.metrics.minimum_caption_font_px"
            )
        for key in (
            "per_caption_baseline_records_complete",
            "single_line_default",
            "centerward_move_applied",
            "exception_records_complete",
            "style_matches_editorial_animation",
            "main_visual_protection_records_complete",
        ):
            require_true(caption_audit, key, "qa.caption_visual_hierarchy_audit", errors)
        baseline_font = caption_audit.get("baseline_min_rendered_font_px")
        final_font = caption_audit.get("minimum_rendered_font_px")
        font_increase = caption_audit.get("minimum_font_increase_px_observed")
        if not all(numeric(value) for value in (baseline_font, final_font, font_increase)):
            errors.append("qa.caption_visual_hierarchy_audit: baseline/final font sizes and increase must be numeric")
        elif final_font - baseline_font != font_increase:
            errors.append(
                "qa.caption_visual_hierarchy_audit.minimum_font_increase_px_observed: "
                "must equal final minus baseline"
            )
        elif font_increase <= 0:
            if caption_audit.get("font_size_increase_exception_approved") is not True:
                errors.append(
                    "qa.caption_visual_hierarchy_audit.font_size_increase_exception_approved: "
                    "must be true when the final minimum font did not increase"
                )
            require_filled(
                caption_audit,
                "font_size_increase_exception_reason",
                "qa.caption_visual_hierarchy_audit",
                errors,
            )
        offsets = caption_audit.get("centerward_offset_range_px")
        if not isinstance(offsets, list) or len(offsets) != 2 or not all(numeric(item) for item in offsets):
            errors.append("qa.caption_visual_hierarchy_audit.centerward_offset_range_px: must be numeric [min, max]")
        elif offsets[1] <= 0:
            errors.append("qa.caption_visual_hierarchy_audit.centerward_offset_range_px: must include a centerward move")
        require_filled(caption_audit, "contrast_strategy", "qa.caption_visual_hierarchy_audit", errors)
        measured_contrast = caption_audit.get("contrast_ratio_measured")
        observed_contrast = caption_audit.get("minimum_contrast_ratio_observed")
        dual_edge = caption_audit.get("dual_edge_or_backing_strategy") is True
        samples = caption_audit.get("complex_background_samples_reviewed")
        if measured_contrast is True:
            if not numeric(observed_contrast) or observed_contrast < 4.5:
                errors.append(
                    "qa.caption_visual_hierarchy_audit.minimum_contrast_ratio_observed: "
                    "must be at least 4.5 when measured"
                )
        elif measured_contrast is False:
            if observed_contrast is not None:
                errors.append(
                    "qa.caption_visual_hierarchy_audit.minimum_contrast_ratio_observed: "
                    "must be null when contrast is not reliably measured"
                )
            if not dual_edge:
                errors.append(
                    "qa.caption_visual_hierarchy_audit.dual_edge_or_backing_strategy: "
                    "must be true when contrast is not measured"
                )
        else:
            errors.append("qa.caption_visual_hierarchy_audit.contrast_ratio_measured: must be boolean")
        if not isinstance(samples, int) or isinstance(samples, bool) or samples <= 0:
            errors.append("qa.caption_visual_hierarchy_audit.complex_background_samples_reviewed: must be positive")
        protected_regions = caption_audit.get("protected_regions_reviewed")
        if not isinstance(protected_regions, int) or isinstance(protected_regions, bool) or protected_regions <= 0:
            errors.append("qa.caption_visual_hierarchy_audit.protected_regions_reviewed: must be positive")
        for key in ("zero_or_reverse_move_exception_count",):
            value = caption_audit.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"qa.caption_visual_hierarchy_audit.{key}: must be a non-negative integer")
        for expected_key, actual_key in (
            ("caption_expected_count", "caption_reviewed_count"),
            ("protected_shots_expected", "protected_shots_reviewed"),
            ("protected_regions_expected", "protected_regions_reviewed"),
        ):
            expected_value = caption_audit.get(expected_key)
            actual_value = caption_audit.get(actual_key)
            if not isinstance(expected_value, int) or isinstance(expected_value, bool) or expected_value < 0:
                errors.append(f"qa.caption_visual_hierarchy_audit.{expected_key}: must be non-negative")
            if not isinstance(actual_value, int) or isinstance(actual_value, bool) or actual_value < 0:
                errors.append(f"qa.caption_visual_hierarchy_audit.{actual_key}: must be non-negative")
            if expected_value != actual_value:
                errors.append(f"qa.caption_visual_hierarchy_audit.{actual_key}: must equal {expected_key}")

        caption_manifest = load_verified_evidence_manifest(
            project_root,
            caption_audit.get("caption_audit_manifest_path"),
            caption_audit.get("caption_audit_manifest_sha256"),
            "qa.caption_visual_hierarchy_audit.caption_audit_manifest",
            errors,
            verify_files,
        )
        if caption_manifest is not None:
            caption_records = as_list(caption_manifest.get("records"), "qa.caption_audit_manifest.records", errors)
            if len(caption_records) != caption_audit.get("caption_expected_count"):
                errors.append("qa.caption_audit_manifest.records: count must equal caption_expected_count")
            seen_cues: set[str] = set()
            for index, raw_record in enumerate(caption_records):
                path = f"qa.caption_audit_manifest.records[{index}]"
                record = as_object(raw_record, path, errors)
                cue_id = record.get("cue_id")
                if isinstance(cue_id, str):
                    if cue_id in seen_cues:
                        errors.append(f"{path}.cue_id: duplicate {cue_id}")
                    seen_cues.add(cue_id)
                errors.extend(
                    validate_caption_audit_record(
                        record,
                        path,
                        expected.get("width"),
                        expected.get("height"),
                    )
                )

        protection_manifest = load_verified_evidence_manifest(
            project_root,
            caption_audit.get("main_visual_protection_manifest_path"),
            caption_audit.get("main_visual_protection_manifest_sha256"),
            "qa.caption_visual_hierarchy_audit.main_visual_protection_manifest",
            errors,
            verify_files,
        )
        if protection_manifest is not None:
            protection_records = as_list(
                protection_manifest.get("records"),
                "qa.main_visual_protection_manifest.records",
                errors,
            )
            if len(protection_records) != caption_audit.get("protected_shots_expected"):
                errors.append("qa.main_visual_protection_manifest.records: count must equal protected_shots_expected")
            seen_protected_shots: set[str] = set()
            total_regions = 0
            for index, raw_record in enumerate(protection_records):
                path = f"qa.main_visual_protection_manifest.records[{index}]"
                record = as_object(raw_record, path, errors)
                shot_id = require_filled(record, "shot_id", path, errors)
                if isinstance(shot_id, str):
                    if shot_id in seen_protected_shots:
                        errors.append(f"{path}.shot_id: duplicate {shot_id}")
                    seen_protected_shots.add(shot_id)
                regions = as_list(record.get("protected_regions"), f"{path}.protected_regions", errors)
                if not regions:
                    errors.append(f"{path}.protected_regions: at least one region is required")
                total_regions += len(regions)
                require_filled(record, "evidence_ref", path, errors)
                require_true(record, "caption_clear", path, errors)
            if total_regions != caption_audit.get("protected_regions_expected"):
                errors.append("qa.main_visual_protection_manifest: region count must equal protected_regions_expected")
        for key in (
            "overflow_count",
            "safe_area_violation_count",
            "main_visual_overlap_count",
            "explanatory_typography_overlap_count",
        ):
            if caption_audit.get(key) != 0:
                errors.append(f"qa.caption_visual_hierarchy_audit.{key}: must equal 0")
    full_watch = as_object(data.get("full_watch"), "qa.full_watch", errors)
    require_filled(full_watch, "watched_by", "qa.full_watch", errors)
    require_filled(full_watch, "watched_at", "qa.full_watch", errors)
    watch_sha = full_watch.get("file_sha256")
    if not isinstance(watch_sha, str) or not SHA256_RE.fullmatch(watch_sha):
        errors.append("qa.full_watch.file_sha256: must be a 64-character SHA-256")
    if watch_sha != sha:
        errors.append("qa.full_watch.file_sha256: must match qa.master_sha256")
    if full_watch.get("release_blocking_findings") != 0:
        errors.append("qa.full_watch.release_blocking_findings: must equal 0")
    delivery = as_object(data.get("desktop_delivery"), "qa.desktop_delivery", errors)
    require_filled(delivery, "directory", "qa.desktop_delivery", errors)
    require_true(delivery, "copy_not_move", "qa.desktop_delivery", errors)
    if delivery.get("hash_mismatch_count") != 0:
        errors.append("qa.desktop_delivery.hash_mismatch_count: must equal 0")
    desktop_sha = delivery.get("master_copy_sha256")
    if desktop_sha != sha:
        errors.append("qa.desktop_delivery.master_copy_sha256: must match qa.master_sha256")
    verify_path_hash(
        project_root,
        delivery.get("master_copy_path"),
        desktop_sha,
        "qa.desktop_delivery.master_copy",
        errors,
        verify_files,
    )
    return errors


def self_test() -> int:
    sha = "a" * 64
    project = {
        "schema_version": "1.2",
        "pipeline": "editorial-magazine-explainer",
        "project_id": "self-test",
        "project_root": "C:/self-test",
        "title": "self test",
        "authorization": {"execution_confirmed": True, "publication_authorized": False},
        "sources": {
            "input_mode": "recording_plus_approved_copy",
            "original_audio": "in.wav",
            "approved_copy": "copy.md",
            "originals_preserved": True,
        },
        "master_clock": {
            "audio_path": "master.wav",
            "duration_seconds": 3,
            "sample_count": 144000,
            "sha256": sha,
            "locked": True,
            "time_stretch_allowed": False,
        },
        "captions": {
            "srt_path": "captions.srt",
            "count": 1,
            "last_sentence_verified": True,
            "locked": True,
            "sha256": sha,
            "single_line_default": True,
            "automatic_wrap_allowed": False,
            "longest_caption_boundary_test_required": True,
        },
        "voice": {
            "profile": "approved-youth-bright-profile",
            "duration_and_sample_count_must_match_master": True,
            "report_required": True,
        },
        "bgm": {
            "required": True,
            "user_opt_out": False,
            "no_lyrics": True,
            "speech_first": True,
            "fade_in_out": True,
            "sidechain_ducking": True,
            "provenance_required": True,
        },
        "gates": {
            "gate_0": "approved",
            "gate_1": "in_progress",
            "gate_2": "not_started",
            "gate_2_5_flow_handoff": "not_started",
            "gate_3": "not_started",
            "gate_4_publication": "not_started",
        },
        "gate_evidence": {
            "gate_1": {"internal_consolidation_complete": False, "completed_at": ""},
            "gate_2": {},
            "gate_3": {},
        },
        "local_production_started": False,
        "final_composition_started": False,
        "shots": [
            {
                "schema_version": "1.2",
                "shot_id": "S01",
                "start_seconds": 0,
                "end_seconds": 3,
                "spoken_text": "学历高一点总没坏处吧",
                "semantic_proposition": "没坏处不等于有必要",
                "subject": "考研选择",
                "action": "接受审问",
                "acted_on_object": "目的",
                "result": "需要具体理由",
                "viewer_takeaway": "先说清目的",
                "shot_family": "independent_component_animation",
                "family_reason": "需要演示判断关系",
                "stable_primary_composition_seconds": 3,
                "sub_1_5_second_exception": "",
                "cues": {"scene_start": 0, "action_cue": 0.8, "text_cue": 0.9},
                "layers": [
                    {
                        "layer_id": "L1",
                        "role": "semantic_actor",
                        "core_semantic_actor": True,
                        "asset_source": "generated_component",
                        "independently_addressable": True,
                        "lifecycle": {key: key for key in LIFECYCLE_KEYS},
                    }
                ],
                "stages": [
                    {
                        "stage_id": "P1",
                        "core_semantic_action": True,
                        "caption_text": "学历高一点总没坏处吧",
                        "explanation_required": True,
                        "explanation_phrase": "没坏处不等于有必要",
                        "explanation_role": "judgment",
                        "explanation_form": "focus_ring",
                        "adds_information_beyond_caption": True,
                        "spoken_keyword_cue": 0.9,
                        "action_cue": 0.8,
                        "text_cue": 0.9,
                        "recognizable_hold_seconds": 0.8,
                    }
                ],
                "semantic_containers": [
                    {
                        "container_id": "C1",
                        "kind": "speech_bubble",
                        "communicative": True,
                        "text_source": "local_compositor",
                        "parent_layer_id": "L1",
                        "coordinate_space": "parent_local",
                        "text_region_normalized": {"x": 0.12, "y": 0.18, "width": 0.76, "height": 0.48},
                        "padding_percent": 6,
                        "perspective_mode": "matched_parent",
                        "clip_to_container": True,
                        "moves_with_parent": True,
                        "visual_hierarchy_role": "primary",
                        "minimum_font_px": 32,
                        "text": "为什么考研？",
                        "decorative_reason": "",
                    }
                ],
                "adaptive_composition_fit": {
                    "required": True,
                    "fit_mode": "contain",
                    "approved_baseline_scale": 1.0,
                    "target_scale_change_percent_range": [8, 12],
                    "allowed_tuning_percent_range": [4, 15],
                    "hard_safe_bounds_px": {"left": 72, "top": 300, "right": 1008, "bottom": 1290},
                    "preferred_stage_bounds_px": {"left": 96, "top": 380, "right": 984, "bottom": 1280},
                    "preferred_primary_axis_fill_ratio_range": [0.72, 0.9],
                    "maximum_width_fill_ratio": 0.9,
                    "maximum_height_fill_ratio": 0.92,
                    "maximum_center_offset_x_px": 90,
                    "per_shot_tuning_required": True,
                    "dense_shot_exception_reason": "",
                },
                "previous_primary_exit_defined": True,
                "caption_layout": {
                    "approved_text": "学历高一点总没坏处吧",
                    "single_line_required": True,
                    "approved_two_line_exception": "",
                    "final_resolution_boundary_test_required": True,
                },
                "transition_in": "paper reveal",
                "transition_out": "semantic handoff",
                "required_assets": ["L1"],
                "prohibited_shortcuts": [
                    "whole_image_motion_as_semantic_animation",
                    "generated_readable_chinese",
                    "empty_communicative_container",
                    "detached_overlay_text_for_semantic_container",
                    "uniform_global_scale_without_per_shot_fit",
                    "production_markers_in_final_frame",
                ],
                "gate_2_status": "waiting_user_review",
            }
        ],
        "flow": {
            "handoff_created": False,
            "return_received": False,
            "source_audio_must_be_removed": True,
            "shots": [],
        },
        "publication": {
            "mode": "not_started",
            "user_confirmed_published": False,
            "target_platforms": [],
            "platform_records": [],
            "tracking_nodes": [],
        },
        "delivery": {
            "desktop_review_directory": "C:/review",
            "copy_not_move": True,
            "sha256_match_required": True,
        },
    }
    revision = {
        "schema_version": "1.2",
        "project_id": "self-test",
        "project_root": "C:/self-test",
        "revision": "v2",
        "based_on_version": "v1",
        "rollback_version_path": "formal-v1",
        "rollback_verified_complete": True,
        "user_request": "only enlarge local components",
        "approved_at": "2026-08-10",
        "user_approval_confirmed": True,
        "allowed_changes": ["local component scale"],
        "forbidden_changes": ["Flow", "audio", "captions"],
        "lock_domains": [
            {"domain": "audio", "applicable": True, "locked": True, "change_allowed": False, "fingerprint_roles": ["narration_master"], "invariants": ["sample_count", "duration", "sha256"]},
            {"domain": "captions", "applicable": True, "locked": True, "change_allowed": False, "fingerprint_roles": ["caption_source"], "invariants": ["text", "timing", "sha256"]},
            {"domain": "timeline", "applicable": True, "locked": True, "change_allowed": False, "fingerprint_roles": ["timeline_manifest"], "invariants": ["scene_boundaries", "action_cues", "text_cues"]},
            {"domain": "flow", "applicable": True, "locked": True, "change_allowed": False, "fingerprint_roles": ["flow_sources_manifest", "flow_placement_manifest"], "invariants": sorted(REQUIRED_FLOW_LOCK_INVARIANTS)},
            {"domain": "bgm", "applicable": True, "locked": True, "change_allowed": False, "fingerprint_roles": ["bgm_master"], "invariants": ["source", "mix"]},
            {"domain": "components", "applicable": True, "locked": False, "change_allowed": True, "fingerprint_roles": [], "invariants": ["local_scale_only"]},
            {"domain": "typography", "applicable": True, "locked": False, "change_allowed": True, "fingerprint_roles": [], "invariants": ["caption_render_only", "explanatory_typography_locked"]},
        ],
        "visual_change_contract": {
            "flow_policy": {
                "locked_unchanged": True,
                "expected_clip_count": 0,
                "invariants": ["frame_size", "crop_window", "speed", "action_order", "absolute_timing"],
            },
            "local_component_scale_percent": {
                "target_range": [8, 12],
                "allowed_tuning_range": [4, 15],
                "per_shot_records_required": True,
                "below_range_requires_reason": True,
                "outside_or_zero_requires_approved_reason": True,
                "center_concentration_required": True,
            },
            "native_container_text_binding": {
                "required": True,
                "local_compositor_required": True,
                "parent_local_coordinates_required": True,
                "clip_to_container_required": True,
                "moves_with_parent_required": True,
                "perspective_match_required": True,
                "floating_overlay_allowed": False,
                "per_container_records_required": True,
            },
            "adaptive_composition_fit": {
                "required": True,
                "fit_mode": "contain",
                "target_scale_change_percent_range": [8, 12],
                "allowed_tuning_percent_range": [4, 15],
                "hard_safe_bounds_px": {"left": 72, "top": 300, "right": 1008, "bottom": 1290},
                "preferred_stage_bounds_px": {"left": 96, "top": 380, "right": 984, "bottom": 1280},
                "preferred_primary_axis_fill_ratio_range": [0.72, 0.9],
                "maximum_width_fill_ratio": 0.9,
                "maximum_height_fill_ratio": 0.92,
                "maximum_center_offset_x_px": 90,
                "per_shot_tuning_required": True,
                "safe_region_and_main_visual_protection_required": True,
            },
            "full_illustration_inner_scale_percent": {
                "target_range": [4, 6],
                "per_shot_records_required": True,
                "outside_or_zero_requires_approved_reason": True,
                "stay_inside_original_frame": True,
                "critical_crop_allowed": False,
            },
            "caption_centerward_move": {
                "required": True,
                "baseline_manifest_required": True,
                "font_size_change_required": True,
                "minimum_font_increase_px": 1,
                "font_size_change_exception_reason": "",
                "per_caption_baseline_and_final_position_required": True,
                "per_shot_avoidance_required": True,
                "platform_safe_area_required": True,
                "zero_or_reverse_move_requires_approved_reason": True,
                "explanatory_typography_locked": True,
            },
            "caption_contrast_strategy": {
                "foreground_style": "deep navy fill",
                "edge_or_backing_style": "warm white stroke and paper shadow",
                "keyword_style": "mustard and brick red",
                "minimum_contrast_ratio_target": 4.5,
                "style_matches_editorial_animation": True,
            },
            "main_visual_protection": {
                "protected_roles": ["people", "core_actions", "result_states", "required_explanatory_typography"],
                "overlap_allowed": False,
            },
        },
        "locked_fingerprints": [
            {"role": role, "path": f"{role}.bin", "sha256": sha}
            for role in (
                "narration_master",
                "caption_source",
                "timeline_manifest",
                "flow_sources_manifest",
                "flow_placement_manifest",
                "bgm_master",
                "typography_manifest",
                "explanatory_typography_manifest",
            )
        ],
        "required_regression_checks": [
            "locked_fingerprint_mismatch_count_is_zero",
            "changed_continuous_ranges_reviewed",
            "full_encoded_master_watched",
        ],
    }
    gate2 = {
        "schema_version": "1.2",
        "project_id": "self-test",
        "project_root": "C:/self-test",
        "status": "approved",
        "expected_shot_count": 1,
        "reviewed_shot_count": 1,
        "all_shot_ids": ["S01"],
        "shot_entries": [
            {
                "shot_id": "S01",
                "shot_family": "independent_component_animation",
                "contract_path": "S01.json",
                "contract_sha256": sha,
                "script_txt_path": "S01.txt",
                "script_txt_sha256": sha,
                "keyframe_path": "S01.png",
                "keyframe_sha256": sha,
                "multi_stage_keyframe_required": True,
                "multi_stage_keyframe_present": True,
                "independent_layer_plan_present": True,
                "layer_plan_path": "S01-layers.json",
                "layer_plan_sha256": sha,
                "container_native_text_plan_present": True,
                "adaptive_composition_fit_plan_present": True,
            }
        ],
        "whole_film_artifacts": {
            key: {"path": f"{key}.json", "sha256": sha}
            for key in REQUIRED_GATE2_WHOLE_FILM_ARTIFACTS + GATE2_1_2_WHOLE_FILM_ARTIFACTS
        },
        "approval": {
            "whole_package_user_approved": True,
            "approved_by": "品牌",
            "user_approval_quote": "整套通过",
            "approved_at": "2026-08-10",
        },
    }
    qa_checks = {key: True for key in REQUIRED_QA_CHECKS}
    qa = {
        "schema_version": "1.2",
        "project_id": "self-test",
        "project_root": "C:/self-test",
        "version": "v2",
        "master_path": "final.mp4",
        "master_sha256": sha,
        "status": "pass",
        "expected_output": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "duration_seconds": 3,
            "duration_tolerance_seconds": 0.1,
            "frame_count": 90,
            "integrated_lufs_range": [-18, -14],
            "loudness_range_lu": [0.5, 8],
            "true_peak_dbtp_max": -1,
            "minimum_information_label_font_px": 32,
            "minimum_explanatory_font_px": 46,
            "minimum_caption_font_px": 49,
        },
        "checks": qa_checks,
        "metrics": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "frame_count": 90,
            "duration_seconds": 3,
            "integrated_lufs": -16,
            "loudness_range_lu": 2,
            "true_peak_dbtp": -2.8,
            "decode_error_count": 0,
            "black_segment_count": 0,
            "unexpected_silence_count": 0,
            "locked_fingerprint_mismatch_count": 0,
            "desktop_hash_mismatch_count": 0,
            "minimum_information_label_font_px": 32,
            "minimum_explanatory_font_px": 46,
            "minimum_caption_font_px": 49,
            "unreadable_corner_text_count": 0,
            "asset_scale_violation_count": 0,
            "caption_overflow_count": 0,
            "caption_safe_area_violation_count": 0,
            "caption_main_visual_overlap_count": 0,
            "native_container_text_violation_count": 0,
            "adaptive_composition_fit_violation_count": 0,
        },
        "asset_class_scale_audit": {
            "flow_locked_unchanged": True,
            "flow_expected_count": 0,
            "flow_compared_count": 0,
            "flow_unauthorized_change_count": 0,
            "local_component_target_scale_percent_range": [8, 12],
            "local_component_expected_shots": 1,
            "local_component_shots_reviewed": 1,
            "local_component_per_shot_records_complete": True,
            "local_component_center_concentrated": True,
            "full_illustration_target_scale_percent_range": [4, 6],
            "full_illustration_expected_shots": 0,
            "full_illustration_shots_reviewed": 0,
            "full_illustration_inside_original_frame": True,
            "clipping_event_count": 0,
            "composition_break_count": 0,
            "scale_exception_count": 0,
            "scale_exception_records_complete": True,
            "asset_record_manifest_path": "asset-records.json",
            "asset_record_manifest_sha256": sha,
        },
        "native_container_text_audit": {
            "communicative_container_expected_count": 1,
            "communicative_container_reviewed_count": 1,
            "per_container_records_complete": True,
            "local_compositor_used": True,
            "parent_local_coordinates_used": True,
            "parent_binding_failure_count": 0,
            "outside_container_count": 0,
            "clipping_mask_failure_count": 0,
            "perspective_mismatch_count": 0,
            "text_overflow_count": 0,
            "floating_overlay_count": 0,
            "parent_motion_desync_count": 0,
            "unreadable_count": 0,
            "records_manifest_path": "native-container-text.json",
            "records_manifest_sha256": sha,
        },
        "adaptive_composition_fit_audit": {
            "local_component_expected_shots": 1,
            "local_component_shots_reviewed": 1,
            "per_shot_records_complete": True,
            "fit_mode": "contain",
            "target_scale_change_percent_range": [8, 12],
            "allowed_tuning_percent_range": [4, 15],
            "hard_safe_bounds_px": {"left": 72, "top": 300, "right": 1008, "bottom": 1290},
            "preferred_stage_bounds_px": {"left": 96, "top": 380, "right": 984, "bottom": 1280},
            "safe_bounds_violation_count": 0,
            "critical_crop_count": 0,
            "visual_drift_count": 0,
            "main_visual_overlap_count": 0,
            "uncomfortable_density_count": 0,
            "underfilled_primary_visual_count": 0,
            "exception_records_complete": True,
            "records_manifest_path": "adaptive-fit.json",
            "records_manifest_sha256": sha,
        },
        "caption_visual_hierarchy_audit": {
            "baseline_min_rendered_font_px": 48,
            "minimum_rendered_font_px": 49,
            "minimum_font_increase_px_observed": 1,
            "font_size_increase_exception_approved": False,
            "font_size_increase_exception_reason": "",
            "per_caption_baseline_records_complete": True,
            "single_line_default": True,
            "centerward_move_applied": True,
            "centerward_offset_range_px": [40, 70],
            "zero_or_reverse_move_exception_count": 0,
            "exception_records_complete": True,
            "contrast_strategy": "deep navy with warm white stroke and paper shadow",
            "contrast_ratio_measured": True,
            "minimum_contrast_ratio_observed": 4.8,
            "dual_edge_or_backing_strategy": True,
            "style_matches_editorial_animation": True,
            "complex_background_samples_reviewed": 8,
            "main_visual_protection_records_complete": True,
            "caption_expected_count": 1,
            "caption_reviewed_count": 1,
            "protected_shots_expected": 1,
            "protected_shots_reviewed": 1,
            "protected_regions_expected": 4,
            "protected_regions_reviewed": 4,
            "caption_audit_manifest_path": "caption-audit.json",
            "caption_audit_manifest_sha256": sha,
            "main_visual_protection_manifest_path": "protection-audit.json",
            "main_visual_protection_manifest_sha256": sha,
            "overflow_count": 0,
            "safe_area_violation_count": 0,
            "main_visual_overlap_count": 0,
            "explanatory_typography_overlap_count": 0,
        },
        "full_watch": {
            "watched_by": "tester",
            "watched_at": "2026-08-10",
            "file_sha256": sha,
            "release_blocking_findings": 0,
        },
        "desktop_delivery": {
            "directory": "C:/review",
            "master_copy_path": "copy.mp4",
            "master_copy_sha256": sha,
            "copy_not_move": True,
            "hash_mismatch_count": 0,
        },
    }
    caption_record = {
        "cue_id": "C001",
        "shot_id": "S01",
        "baseline_font_px": 48,
        "final_font_px": 49,
        "required_increase_px": 1,
        "baseline_x_px": 540,
        "baseline_y_px": 1500,
        "final_x_px": 540,
        "final_y_px": 1430,
        "centerward_offset_px": 70,
        "exception_approved": False,
        "single_line": True,
        "overflow_absent": True,
        "safe_area_clear": True,
        "main_visual_clear": True,
        "explanatory_typography_clear": True,
    }
    native_container_record = {
        "container_id": "C1",
        "shot_id": "S01",
        "parent_layer_id": "L1",
        "text_source": "local_compositor",
        "coordinate_space": "parent_local",
        "text_region_normalized": {"x": 0.12, "y": 0.18, "width": 0.76, "height": 0.48},
        "padding_percent": 6,
        "perspective_mode": "matched_parent",
        "minimum_font_px": 32,
        "clip_to_container": True,
        "moves_with_parent": True,
        "text_inside_container": True,
        "overflow_absent": True,
        "perspective_matched": True,
        "floating_overlay_absent": True,
        "readable": True,
        "evidence_ref": "S01-native-text.png",
    }
    adaptive_fit_record = {
        "shot_id": "S01",
        "baseline_scale": 1.0,
        "final_scale": 1.1,
        "scale_change_percent": 10,
        "final_bbox_px": {"x": 180, "y": 400, "width": 720, "height": 800},
        "width_fill_ratio": 720 / 1080,
        "height_fill_ratio": 800 / 1920,
        "primary_axis_fill_ratio": 0.8,
        "center_offset_x_px": 0,
        "critical_crop_absent": True,
        "visual_drift_absent": True,
        "main_visual_clear": True,
        "comfortable_density": True,
        "exception_approved": False,
        "evidence_ref": "S01-fit.png",
    }
    failures = (
        validate_project(project)
        + validate_shot_contract(project["shots"][0])
        + validate_gate2_manifest(gate2)
        + validate_revision(revision)
        + validate_qa(qa)
        + cross_validate_contracts(
            {"project": project, "revision": revision, "qa": qa},
            verify_files=False,
        )
        + validate_caption_audit_record(caption_record, "self_test.caption_record", 1080, 1920)
        + validate_native_container_text_record(native_container_record, "self_test.native_container_record")
        + validate_adaptive_fit_record(
            adaptive_fit_record,
            "self_test.adaptive_fit_record",
            1080,
            1920,
            {"left": 72, "top": 300, "right": 1008, "bottom": 1290},
        )
    )
    if failures:
        for failure in failures:
            print(f"SELF-TEST FAIL: {failure}", file=sys.stderr)
        return 1
    legacy_1_1_qa = json.loads(json.dumps(qa))
    legacy_1_1_qa["schema_version"] = "1.1"
    for key in QA_1_2_CHECKS:
        legacy_1_1_qa["checks"].pop(key, None)
    for key in ("native_container_text_violation_count", "adaptive_composition_fit_violation_count"):
        legacy_1_1_qa["metrics"].pop(key, None)
    legacy_1_1_qa.pop("native_container_text_audit", None)
    legacy_1_1_qa.pop("adaptive_composition_fit_audit", None)
    legacy_1_1_failures = validate_qa(legacy_1_1_qa)
    if legacy_1_1_failures:
        for failure in legacy_1_1_failures:
            print(f"SELF-TEST FAIL: v1.1 QA compatibility regression: {failure}", file=sys.stderr)
        return 1
    legacy_qa = json.loads(json.dumps(legacy_1_1_qa))
    legacy_qa["schema_version"] = "1.0"
    for key in QA_1_1_CHECKS | QA_1_2_CHECKS:
        legacy_qa["checks"].pop(key, None)
    for key in (
        "asset_scale_violation_count",
        "caption_overflow_count",
        "caption_safe_area_violation_count",
        "caption_main_visual_overlap_count",
        "minimum_caption_font_px",
    ):
        legacy_qa["metrics"].pop(key, None)
    legacy_qa["expected_output"].pop("minimum_caption_font_px", None)
    legacy_qa.pop("asset_class_scale_audit", None)
    legacy_qa.pop("caption_visual_hierarchy_audit", None)
    legacy_failures = validate_qa(legacy_qa)
    if legacy_failures:
        for failure in legacy_failures:
            print(f"SELF-TEST FAIL: v1.0 QA compatibility regression: {failure}", file=sys.stderr)
        return 1
    legacy_project = json.loads(json.dumps(project))
    legacy_project["schema_version"] = "1.1"
    legacy_shot = legacy_project["shots"][0]
    legacy_shot["schema_version"] = "1.1"
    legacy_shot.pop("adaptive_composition_fit", None)
    for key in (
        "text_source",
        "parent_layer_id",
        "coordinate_space",
        "text_region_normalized",
        "padding_percent",
        "perspective_mode",
        "clip_to_container",
        "moves_with_parent",
        "visual_hierarchy_role",
        "minimum_font_px",
    ):
        legacy_shot["semantic_containers"][0].pop(key, None)
    legacy_shot["prohibited_shortcuts"] = [
        value
        for value in legacy_shot["prohibited_shortcuts"]
        if value not in {
            "detached_overlay_text_for_semantic_container",
            "uniform_global_scale_without_per_shot_fit",
        }
    ]
    legacy_project_failures = validate_project(legacy_project)
    if legacy_project_failures:
        for failure in legacy_project_failures:
            print(f"SELF-TEST FAIL: v1.1 project compatibility regression: {failure}", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["gates"]["gate_2"] = "waiting_user_review"
    invalid["local_production_started"] = True
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject production before Gate 2 approval", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    del invalid["gates"]["gate_3"]
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject a missing Gate key", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["shots"][0]["semantic_containers"][0]["text"] = ""
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject an empty communicative container", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    del invalid["shots"][0]["semantic_containers"][0]["parent_layer_id"]
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject detached semantic-container text", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["shots"][0]["adaptive_composition_fit"]["allowed_tuning_percent_range"] = [0, 99]
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject a fake adaptive-fit range", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["shots"][0]["stages"][0]["explanation_phrase"] = invalid["shots"][0]["stages"][0]["caption_text"]
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject caption-duplicating explanation", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["shots"][0]["stages"][0]["core_semantic_action"] = False
    invalid["shots"][0]["stages"][0]["explanation_required"] = False
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not require a core component stage", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["shots"][0]["cues"]["action_cue"] = 9
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject an out-of-range cue", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["flow"]["handoff_created"] = True
    invalid["flow"]["all_flow_shots_gate_2_approved"] = True
    invalid["flow"]["shots"] = [
        {
            "shot_id": "S02",
            "no_text_reference": True,
            "production_prompt_complete": True,
            "spoken_text": "Flow test",
            "return_path": "return/S02.mp4",
        }
    ]
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject Flow handoff before Gate 2 approval", file=sys.stderr)
        return 1
    invalid_revision = json.loads(json.dumps(revision))
    invalid_revision["forbidden_changes"].append(invalid_revision["allowed_changes"][0])
    if not validate_revision(invalid_revision):
        print("SELF-TEST FAIL: validator did not reject overlapping revision rules", file=sys.stderr)
        return 1
    invalid_revision = json.loads(json.dumps(revision))
    invalid_revision["locked_fingerprints"] = [
        item for item in invalid_revision["locked_fingerprints"] if item["role"] != "flow_placement_manifest"
    ]
    if not validate_revision(invalid_revision):
        print("SELF-TEST FAIL: validator did not reject an incomplete Flow lock", file=sys.stderr)
        return 1
    invalid_revision = json.loads(json.dumps(revision))
    del invalid_revision["visual_change_contract"]
    if not validate_revision(invalid_revision):
        print("SELF-TEST FAIL: validator did not require a visual change contract", file=sys.stderr)
        return 1
    invalid_revision = json.loads(json.dumps(revision))
    invalid_revision["locked_fingerprints"] = [
        item
        for item in invalid_revision["locked_fingerprints"]
        if item["role"] != "explanatory_typography_manifest"
    ]
    if not validate_revision(invalid_revision):
        print("SELF-TEST FAIL: validator did not require an explanatory-typography fingerprint", file=sys.stderr)
        return 1
    invalid_gate2 = json.loads(json.dumps(gate2))
    invalid_gate2["shot_entries"] = []
    if not validate_gate2_manifest(invalid_gate2):
        print("SELF-TEST FAIL: validator did not reject Gate 2 missing a shot", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["checks"]["full_encoded_master_watched"] = False
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject incomplete Gate 3 QA", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["metrics"]["width"] = 720
    invalid_qa["metrics"]["black_segment_count"] = 1
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject bad output specs/black frames", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["caption_visual_hierarchy_audit"]["main_visual_overlap_count"] = 1
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject caption overlap with the main visual", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["asset_class_scale_audit"]["local_component_target_scale_percent_range"] = [4, 6]
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject the wrong local-component scale contract", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["asset_class_scale_audit"]["flow_compared_count"] = 1
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not require every Flow clip to be compared", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["asset_class_scale_audit"]["local_component_expected_shots"] = 0
    invalid_qa["asset_class_scale_audit"]["local_component_shots_reviewed"] = 0
    if not cross_validate_contracts(
        {"project": project, "revision": revision, "qa": invalid_qa},
        verify_files=False,
    ):
        print("SELF-TEST FAIL: cross-contract validation accepted a fake 0/0 family pass", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["caption_visual_hierarchy_audit"]["minimum_rendered_font_px"] = 48
    invalid_qa["caption_visual_hierarchy_audit"]["minimum_font_increase_px_observed"] = 0
    invalid_qa["caption_visual_hierarchy_audit"]["font_size_increase_exception_approved"] = False
    invalid_qa["metrics"]["minimum_caption_font_px"] = 48
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject a non-increased caption font without approval", file=sys.stderr)
        return 1
    invalid_qa = json.loads(json.dumps(qa))
    invalid_qa["caption_visual_hierarchy_audit"]["minimum_contrast_ratio_observed"] = 4.4
    if not validate_qa(invalid_qa):
        print("SELF-TEST FAIL: validator did not reject measured caption contrast below 4.5", file=sys.stderr)
        return 1
    for missing_key in ("baseline_x_px", "final_y_px"):
        invalid_caption_record = json.loads(json.dumps(caption_record))
        del invalid_caption_record[missing_key]
        if not validate_caption_audit_record(invalid_caption_record, "self_test.caption_record", 1080, 1920):
            print(f"SELF-TEST FAIL: caption audit accepted missing {missing_key}", file=sys.stderr)
            return 1
    invalid_caption_record = json.loads(json.dumps(caption_record))
    invalid_caption_record["baseline_x_px"] = "540"
    if not validate_caption_audit_record(invalid_caption_record, "self_test.caption_record", 1080, 1920):
        print("SELF-TEST FAIL: caption audit accepted a non-numeric baseline coordinate", file=sys.stderr)
        return 1
    invalid_caption_record = json.loads(json.dumps(caption_record))
    invalid_caption_record["final_y_px"] = 1570
    invalid_caption_record["centerward_offset_px"] = 70
    if not validate_caption_audit_record(invalid_caption_record, "self_test.caption_record", 1080, 1920):
        print("SELF-TEST FAIL: caption audit trusted a claimed positive move over reverse coordinates", file=sys.stderr)
        return 1
    invalid_native_record = json.loads(json.dumps(native_container_record))
    invalid_native_record["floating_overlay_absent"] = False
    if not validate_native_container_text_record(invalid_native_record, "self_test.native_container_record"):
        print("SELF-TEST FAIL: native-container audit accepted floating overlay text", file=sys.stderr)
        return 1
    invalid_fit_record = json.loads(json.dumps(adaptive_fit_record))
    invalid_fit_record["final_bbox_px"]["x"] = 50
    if not validate_adaptive_fit_record(
        invalid_fit_record,
        "self_test.adaptive_fit_record",
        1080,
        1920,
        {"left": 72, "top": 300, "right": 1008, "bottom": 1290},
    ):
        print("SELF-TEST FAIL: adaptive-fit audit accepted a safe-bounds violation", file=sys.stderr)
        return 1
    invalid = json.loads(json.dumps(project))
    invalid["gates"]["gate_1"] = "approved"
    invalid["gate_evidence"]["gate_1"] = {"internal_consolidation_complete": True, "completed_at": "2026-08-10"}
    invalid["gates"]["gate_2"] = "approved"
    invalid["gate_evidence"]["gate_2"] = {
        "manifest_path": "gate2.json",
        "manifest_sha256": sha,
        "all_shots_included": True,
        "whole_package_user_approved": True,
        "approved_by": "品牌",
        "user_approval_quote": "整套通过",
        "approved_at": "2026-08-10",
    }
    invalid["local_production_started"] = True
    invalid["final_composition_started"] = True
    invalid["gates"]["gate_3"] = "approved"
    invalid["gate_evidence"]["gate_3"] = {
        "qa_manifest_path": "qa.json",
        "qa_manifest_sha256": sha,
        "user_approved_master": True,
        "approved_by": "品牌",
        "user_approval_quote": "通过",
        "approved_at": "2026-08-10",
    }
    invalid["voice"].update(
        {
            "formal_path": "voice.wav",
            "formal_sha256": sha,
            "report_path": "voice.md",
            "report_sha256": sha,
            "sample_count_matches_master": True,
            "duration_matches_master": True,
            "input_sample_count": 144000,
            "output_sample_count": 144000,
            "input_duration_seconds": 3,
            "output_duration_seconds": 3,
            "integrated_lufs": -16,
            "loudness_range_lu": 2,
            "true_peak_dbtp": -2.8,
            "processing_chain_version": "approved-brand-voice-profile",
        }
    )
    invalid["bgm"].update(
        {
            "formal_path": "bgm.mp3",
            "formal_sha256": sha,
            "mix_report_path": "mix.md",
            "mix_report_sha256": sha,
            "source_and_license": "licensed",
            "license_status": "approved",
            "provenance_recorded": True,
        }
    )
    invalid["gates"]["gate_4_publication"] = "tracking"
    invalid["publication"] = {
        "mode": "user_manual",
        "user_confirmed_published": True,
        "user_confirmation_quote": "全部发布了",
        "user_confirmation_at": "2026-08-10",
        "target_platforms": ["douyin", "xiaohongshu", "wechat"],
        "platform_records": [
            {
                "platform": "douyin",
                "native_id": "1",
                "published_at": "2026-08-10",
                "workbench_post_id": "post-1",
                "platform_status": "published",
                "source_url": "https://example.com/1",
            }
        ],
        "tracking_nodes": [],
    }
    if not validate_project(invalid):
        print("SELF-TEST FAIL: validator did not reject incomplete multi-platform publication/tracking", file=sys.stderr)
        return 1
    print("SELF-TEST PASS")
    return 0


def cross_validate_contracts(
    loaded: dict[str, dict[str, Any]],
    verify_files: bool,
) -> list[str]:
    errors: list[str] = []
    qa = loaded.get("qa")
    if qa is None or not schema_at_least(qa, 1, 1) or qa.get("status") != "pass":
        return errors
    project = loaded.get("project")
    revision = loaded.get("revision")
    if project is None:
        errors.append("cross-contract: schema 1.1 passing QA requires the project contract")
        return errors
    if revision is None:
        errors.append("cross-contract: schema 1.1 passing QA requires the revision lock")
        return errors

    project_shots = [shot for shot in project.get("shots", []) if isinstance(shot, dict)]
    project_ids_by_family = {
        family: {str(shot.get("shot_id")) for shot in project_shots if shot.get("shot_family") == family}
        for family in ALLOWED_FAMILIES
    }
    asset_audit = qa.get("asset_class_scale_audit", {})
    expected_by_family = {
        "silent_google_flow": asset_audit.get("flow_expected_count"),
        "independent_component_animation": asset_audit.get("local_component_expected_shots"),
        "full_editorial_illustration": asset_audit.get("full_illustration_expected_shots"),
    }
    for family, expected in expected_by_family.items():
        actual = len(project_ids_by_family[family])
        if expected != actual:
            errors.append(f"cross-contract: QA expected {family} count {expected!r}, project has {actual}")

    revision_flow_expected = (
        revision.get("visual_change_contract", {})
        .get("flow_policy", {})
        .get("expected_clip_count")
    )
    actual_flow_count = len(project_ids_by_family["silent_google_flow"])
    if revision_flow_expected != actual_flow_count:
        errors.append(
            "cross-contract: revision Flow expected count must equal the project silent_google_flow count"
        )
    if asset_audit.get("flow_expected_count") != revision_flow_expected:
        errors.append("cross-contract: QA and revision Flow expected counts must match")

    caption_audit = qa.get("caption_visual_hierarchy_audit", {})
    project_caption_count = project.get("captions", {}).get("count")
    if caption_audit.get("caption_expected_count") != project_caption_count:
        errors.append("cross-contract: QA caption_expected_count must equal project captions.count")

    if schema_at_least(qa, 1, 2):
        communicative_container_ids = {
            str(container.get("container_id"))
            for shot in project_shots
            for container in shot.get("semantic_containers", [])
            if isinstance(container, dict)
            and container.get("communicative") is True
            and is_filled(container.get("container_id"))
        }
        native_audit = qa.get("native_container_text_audit", {})
        if native_audit.get("communicative_container_expected_count") != len(communicative_container_ids):
            errors.append(
                "cross-contract: QA communicative-container count must equal the project contract"
            )
        fit_audit = qa.get("adaptive_composition_fit_audit", {})
        if fit_audit.get("local_component_expected_shots") != len(
            project_ids_by_family["independent_component_animation"]
        ):
            errors.append(
                "cross-contract: QA adaptive-fit shot count must equal project independent-component shots"
            )
        if not schema_at_least(revision, 1, 2):
            errors.append("cross-contract: schema 1.2 passing QA requires a schema 1.2 revision lock")

    if not verify_files:
        return errors
    project_root = project_root_from(qa, "qa", errors, verify_files=True)
    asset_manifest = load_verified_evidence_manifest(
        project_root,
        asset_audit.get("asset_record_manifest_path"),
        asset_audit.get("asset_record_manifest_sha256"),
        "cross-contract.asset_record_manifest",
        errors,
        True,
    )
    if asset_manifest is not None:
        records_by_family = {family: set() for family in ALLOWED_FAMILIES}
        for record in asset_manifest.get("records", []):
            if isinstance(record, dict) and record.get("family") in records_by_family and is_filled(record.get("shot_id")):
                records_by_family[record["family"]].add(str(record["shot_id"]))
        for family in ALLOWED_FAMILIES:
            if records_by_family[family] != project_ids_by_family[family]:
                errors.append(f"cross-contract: asset manifest {family} shot set must equal project shot set")

    caption_manifest = load_verified_evidence_manifest(
        project_root,
        caption_audit.get("caption_audit_manifest_path"),
        caption_audit.get("caption_audit_manifest_sha256"),
        "cross-contract.caption_audit_manifest",
        errors,
        True,
    )
    if caption_manifest is not None:
        caption_records = [record for record in caption_manifest.get("records", []) if isinstance(record, dict)]
        if len(caption_records) != project_caption_count:
            errors.append("cross-contract: caption audit record count must equal project captions.count")
        project_shot_ids = {str(shot.get("shot_id")) for shot in project_shots}
        if any(str(record.get("shot_id")) not in project_shot_ids for record in caption_records):
            errors.append("cross-contract: every caption audit record must map to a project shot")

    protection_manifest = load_verified_evidence_manifest(
        project_root,
        caption_audit.get("main_visual_protection_manifest_path"),
        caption_audit.get("main_visual_protection_manifest_sha256"),
        "cross-contract.main_visual_protection_manifest",
        errors,
        True,
    )
    if protection_manifest is not None:
        protected_ids = {
            str(record.get("shot_id"))
            for record in protection_manifest.get("records", [])
            if isinstance(record, dict) and is_filled(record.get("shot_id"))
        }
        caption_shot_ids = {
            str(record.get("shot_id"))
            for record in (caption_manifest or {}).get("records", [])
            if isinstance(record, dict) and is_filled(record.get("shot_id"))
        }
        if protected_ids != caption_shot_ids:
            errors.append(
                "cross-contract: protection manifest must cover every shot referenced by caption audit records"
            )
    if schema_at_least(qa, 1, 2):
        native_audit = qa.get("native_container_text_audit", {})
        native_manifest = load_verified_evidence_manifest(
            project_root,
            native_audit.get("records_manifest_path"),
            native_audit.get("records_manifest_sha256"),
            "cross-contract.native_container_text_manifest",
            errors,
            True,
        )
        if native_manifest is not None:
            native_ids = {
                str(record.get("container_id"))
                for record in native_manifest.get("records", [])
                if isinstance(record, dict) and is_filled(record.get("container_id"))
            }
            if native_ids != communicative_container_ids:
                errors.append(
                    "cross-contract: native-container-text manifest must cover every communicative container"
                )
        fit_audit = qa.get("adaptive_composition_fit_audit", {})
        fit_manifest = load_verified_evidence_manifest(
            project_root,
            fit_audit.get("records_manifest_path"),
            fit_audit.get("records_manifest_sha256"),
            "cross-contract.adaptive_composition_fit_manifest",
            errors,
            True,
        )
        if fit_manifest is not None:
            fit_ids = {
                str(record.get("shot_id"))
                for record in fit_manifest.get("records", [])
                if isinstance(record, dict) and is_filled(record.get("shot_id"))
            }
            if fit_ids != project_ids_by_family["independent_component_animation"]:
                errors.append(
                    "cross-contract: adaptive-fit manifest must cover every independent-component shot"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-contract", type=Path)
    parser.add_argument("--shot-contract", type=Path)
    parser.add_argument("--gate2-manifest", type=Path)
    parser.add_argument("--revision-lock", type=Path)
    parser.add_argument("--qa-manifest", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--skip-file-verification",
        action="store_true",
        help="schema-only drafting mode; never use this to unlock a production Gate",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not any((args.project_contract, args.shot_contract, args.gate2_manifest, args.revision_lock, args.qa_manifest)):
        parser.error("provide at least one contract path or use --self-test")

    failures: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}
    verify_files = not args.skip_file_verification
    try:
        if args.project_contract:
            loaded["project"] = load_json(args.project_contract)
            failures.extend(validate_project(loaded["project"], verify_files=verify_files))
        if args.shot_contract:
            loaded["shot"] = load_json(args.shot_contract)
            failures.extend(validate_shot_contract(loaded["shot"]))
        if args.gate2_manifest:
            loaded["gate2"] = load_json(args.gate2_manifest)
            failures.extend(validate_gate2_manifest(loaded["gate2"], verify_files=verify_files))
        if args.revision_lock:
            loaded["revision"] = load_json(args.revision_lock)
            failures.extend(validate_revision(loaded["revision"], verify_files=verify_files))
        if args.qa_manifest:
            loaded["qa"] = load_json(args.qa_manifest)
            failures.extend(validate_qa(loaded["qa"], verify_files=verify_files))
        if args.skip_file_verification:
            if "gate2" in loaded and loaded["gate2"].get("status") == "approved":
                failures.append("draft mode: an approved Gate 2 manifest requires real file/hash verification")
            if "revision" in loaded:
                failures.append("draft mode: a revision lock cannot unlock work without real file/hash verification")
            if "qa" in loaded and loaded["qa"].get("status") == "pass":
                failures.append("draft mode: a passing Gate 3 QA manifest requires real file/hash verification")
            if "project" in loaded and (
                loaded["project"].get("gates", {}).get("gate_2") == "approved"
                or loaded["project"].get("gates", {}).get("gate_3") == "approved"
            ):
                failures.append("draft mode: approved project Gates require real file/hash verification")
        project_ids = {
            value.get("project_id")
            for key, value in loaded.items()
            if key != "shot" and is_filled(value.get("project_id"))
        }
        if len(project_ids) > 1:
            failures.append("cross-contract: project_id mismatch")
        if "revision" in loaded and "qa" in loaded and loaded["revision"].get("revision") != loaded["qa"].get("version"):
            failures.append("cross-contract: revision version must match QA version")
        failures.extend(cross_validate_contracts(loaded, verify_files=verify_files))
    except ValueError as exc:
        failures.append(str(exc))

    if args.json:
        print(json.dumps({"status": "fail" if failures else "pass", "errors": failures}, ensure_ascii=False, indent=2))
    elif failures:
        print(f"FAIL: {len(failures)} contract violation(s)", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    else:
        print("PASS: editorial-magazine project contracts are internally consistent")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
