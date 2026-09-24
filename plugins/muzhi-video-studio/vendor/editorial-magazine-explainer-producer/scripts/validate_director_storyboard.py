#!/usr/bin/env python3
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


VISUAL_ROUTES = {
    "image_to_video",
    "native_mg",
    "official_evidence",
    "sourced_chart",
    "vox_layered_broll",
    "real_media",
    "hybrid",
}

CONTENT_FUNCTIONS = {
    "hook",
    "answer",
    "evidence",
    "data",
    "example",
    "humor",
    "method",
    "turn",
    "transition",
    "cta",
}
FORBIDDEN_QUOTA_KEYS = {
    "expected_shot_count",
    "target_shot_count",
    "minimum_shot_count",
    "maximum_shot_count",
    "shot_quota",
    "fill_shot_count",
    "target_chapter_count",
    "chapter_quota",
    "fixed_shot_count",
    "fixed_chapter_count",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require(condition: bool, code: str, errors: list[str]) -> None:
    if not condition:
        errors.append(code)


def filled(value: object) -> bool:
    text = str(value or "").strip()
    return bool(text) and "__FILL" not in text


def resolved_path(value: object, base: Path) -> Path | None:
    if not filled(value):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base / path


def validate_file(path_value: object, digest_value: object, base: Path, scope: str, errors: list[str]) -> None:
    path = resolved_path(path_value, base)
    digest = str(digest_value or "").strip().upper()
    require(path is not None, f"{scope}:path_missing", errors)
    require(len(digest) == 64, f"{scope}:sha256_missing", errors)
    if path is None:
        return
    require(path.is_file(), f"{scope}:file_missing", errors)
    if path.is_file() and len(digest) == 64:
        require(sha256(path) == digest, f"{scope}:hash_mismatch", errors)


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def probe_media(path: Path) -> tuple[float, set[str]]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    stream_types = {str(stream.get("codec_type")) for stream in data.get("streams", [])}
    return duration, stream_types


def parse_srt_timestamp(value: str) -> float:
    hours, minutes, rest = value.strip().replace(".", ",").split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(path: Path) -> dict[str, tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8-sig")
    cues: dict[str, tuple[float, float, str]] = {}
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        raw_id = lines[0]
        start_text, end_text = [part.strip() for part in lines[1].split("-->", 1)]
        start = parse_srt_timestamp(start_text)
        end = parse_srt_timestamp(end_text)
        cue_id = f"C{int(raw_id):02d}" if raw_id.isdigit() else raw_id
        cues[cue_id] = (start, end, " ".join(lines[2:]))
    return cues


def trusted_bgm_registry_from_local_config(contract: dict | None = None) -> Path | None:
    config = Path(__file__).resolve().parents[1] / "config" / "local.json"
    data: dict = {}
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            data = {}
    value = str(data.get("bgm_registry_path", "")).strip()
    if value:
        if contract is not None and str(data.get("mode", "")) == "workspace":
            workspace = str(data.get("workspace_root", "")).strip()
            project = str(contract.get("project_root", "")).strip()
            if workspace and project:
                try:
                    project_path = Path(project).resolve()
                    workspace_path = Path(workspace).resolve()
                    if project_path != workspace_path and workspace_path not in project_path.parents:
                        return None
                except OSError:
                    return None
        return Path(value).resolve()
    if contract is not None:
        project = str(contract.get("project_root", "")).strip()
        if project:
            try:
                cursor = Path(project).resolve()
                for candidate in (cursor, *cursor.parents):
                    if candidate.name == "<WORKSPACE_ROOT>":
                        registry = candidate / "assets" / "教培动画素材库" / "03-音频" / "bgm-registry.json"
                        if registry.is_file():
                            return registry.resolve()
            except OSError:
                return None
    return None


def validate_visual_file(path: Path, scope: str, errors: list[str]) -> None:
    if not path.is_file():
        return
    suffix = path.suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm"}
    require(suffix in allowed, f"{scope}:unsupported_visual_evidence_type", errors)
    if suffix == ".png":
        require(path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{scope}:invalid_png", errors)
    elif suffix in {".jpg", ".jpeg"}:
        require(path.read_bytes()[:2] == b"\xff\xd8", f"{scope}:invalid_jpeg", errors)
    elif suffix == ".webp":
        header = path.read_bytes()[:12]
        require(header[:4] == b"RIFF" and header[8:12] == b"WEBP", f"{scope}:invalid_webp", errors)
    elif suffix in {".mp4", ".mov", ".mkv", ".webm"}:
        try:
            _, streams = probe_media(path)
            require("video" in streams, f"{scope}:video_stream_missing", errors)
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            errors.append(f"{scope}:visual_media_probe_failed")


def audio_features(path: Path, sample_rate: int = 4000) -> list[tuple[float, ...]]:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1"],
        check=True,
        capture_output=True,
    )
    samples = array("h")
    samples.frombytes(result.stdout)
    block_size = sample_rate
    features: list[tuple[float, ...]] = []
    for offset in range(0, len(samples) - block_size + 1, block_size):
        block = samples[offset:offset + block_size]
        rms = math.sqrt(sum(float(value) * value for value in block) / max(1, len(block)))
        if rms < 8:
            features.append((0.0, 0.0, 0.0, 0.0, 0.0))
            continue
        zcr = sum(1 for index in range(1, len(block)) if (block[index] >= 0) != (block[index - 1] >= 0)) / len(block)
        diffs = []
        for lag in (1, 4, 16, 64):
            value = sum(abs(int(block[index]) - int(block[index - lag])) for index in range(lag, len(block)))
            diffs.append(value / max(1, len(block) - lag) / rms)
        features.append(tuple([zcr, *diffs]))
    return features


def narration_similarity(master: Path, mixed_video: Path) -> float:
    first = audio_features(master)
    second = audio_features(mixed_video)
    count = min(len(first), len(second))
    if count == 0:
        return 0.0
    distances = []
    for left, right in zip(first[:count], second[:count]):
        component_distances = [abs(a - b) / (abs(a) + abs(b) + 0.05) for a, b in zip(left, right)]
        distances.append(sum(component_distances) / len(component_distances))
    return max(0.0, 1.0 - sum(distances) / len(distances))


def reject_quota_fields(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_QUOTA_KEYS and child is not None:
                errors.append(f"{path}:{key}_forbidden")
            reject_quota_fields(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_quota_fields(child, f"{path}[{index}]", errors)


def validate_evidence(items: object, segment_id: str, base: Path, errors: list[str]) -> None:
    require(isinstance(items, list) and len(items) > 0, f"segment:{segment_id}:evidence_missing", errors)
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
        prefix = f"segment:{segment_id}:evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}:not_object")
            continue
        locator = str(item.get("path_or_url", "")).strip()
        require(filled(locator), f"{prefix}:locator_missing", errors)
        require(filled(item.get("publisher")), f"{prefix}:publisher_missing", errors)
        require(filled(item.get("source_id")), f"{prefix}:source_id_missing", errors)
        require(filled(item.get("source_title")), f"{prefix}:source_title_missing", errors)
        require(filled(item.get("year_or_date")), f"{prefix}:date_missing", errors)
        require(filled(item.get("retrieved_at")), f"{prefix}:retrieved_at_missing", errors)
        require(filled(item.get("supports")), f"{prefix}:supports_missing", errors)
        require(item.get("verified") is True, f"{prefix}:not_verified", errors)
        require(filled(item.get("source_footer_text")), f"{prefix}:source_footer_missing", errors)
        require(item.get("integrated_with_design_carrier") is True,
                f"{prefix}:not_integrated_with_design_carrier", errors)
        require(item.get("raw_browser_chrome_visible") is False,
                f"{prefix}:raw_browser_chrome_visible", errors)
        snapshot = resolved_path(item.get("local_snapshot_path"), base)
        snapshot_digest = str(item.get("local_snapshot_sha256", "")).strip().upper()
        require(snapshot is not None, f"{prefix}:local_snapshot_missing", errors)
        require(len(snapshot_digest) == 64, f"{prefix}:local_snapshot_sha256_missing", errors)
        if snapshot is not None:
            require(snapshot.is_file(), f"{prefix}:local_snapshot_file_missing", errors)
            if snapshot.is_file() and len(snapshot_digest) == 64:
                require(sha256(snapshot) == snapshot_digest, f"{prefix}:local_snapshot_hash_mismatch", errors)
            validate_visual_file(snapshot, f"{prefix}:local_snapshot", errors)
        if locator and not is_url(locator):
            digest = str(item.get("sha256", "")).strip().upper()
            require(len(digest) == 64, f"{prefix}:local_sha256_missing", errors)
            path = Path(locator)
            if not path.is_absolute():
                path = base / path
            require(path.is_file(), f"{prefix}:local_file_missing", errors)
            if path.is_file() and len(digest) == 64:
                require(sha256(path) == digest, f"{prefix}:local_hash_mismatch", errors)


def validate_segment(segment: dict, max_i2v: float, base: Path, errors: list[str]) -> None:
    segment_id = str(segment.get("id", "unknown"))
    prefix = f"segment:{segment_id}"
    for field in ("spoken_text", "audience_question", "audience_takeaway", "route_reason", "entry", "settle", "explain", "exit", "transition_to_next"):
        require(filled(segment.get(field)), f"{prefix}:{field}_missing", errors)
    require(filled(segment.get("semantic_event_id")), f"{prefix}:semantic_event_id_missing", errors)
    cue_ids = segment.get("srt_cue_ids")
    require(isinstance(cue_ids, list) and any(filled(item) for item in cue_ids or []),
            f"{prefix}:srt_cue_ids_missing", errors)

    start = segment.get("start_seconds")
    end = segment.get("end_seconds")
    require(isinstance(start, (int, float)), f"{prefix}:start_missing", errors)
    require(isinstance(end, (int, float)), f"{prefix}:end_missing", errors)
    duration = 0.0
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        duration = float(end) - float(start)
        require(duration > 0, f"{prefix}:duration_invalid", errors)

    content_function = segment.get("content_function")
    route = segment.get("visual_route")
    require(content_function in CONTENT_FUNCTIONS, f"{prefix}:content_function_invalid", errors)
    require(route in VISUAL_ROUTES, f"{prefix}:visual_route_invalid", errors)

    beats = segment.get("animation_beats")
    require(isinstance(beats, list) and any(filled(item) for item in beats or []), f"{prefix}:animation_beats_missing", errors)

    exact_text = segment.get("requires_exact_text") is True
    exact_data = segment.get("requires_exact_data") is True
    screen_text = segment.get("screen_text")
    if route == "image_to_video":
        require(not isinstance(screen_text, list) or not any(filled(item.get("text")) for item in screen_text if isinstance(item, dict)),
                f"{prefix}:readable_screen_text_in_pure_i2v", errors)
        require(content_function not in {"data", "evidence"},
                f"{prefix}:data_or_evidence_disguised_as_i2v", errors)
    if exact_text or exact_data:
        require(route != "image_to_video", f"{prefix}:exact_information_routed_to_i2v", errors)
        validate_evidence(segment.get("evidence"), segment_id, base, errors)
        require(float(segment.get("readable_hold_seconds", 0)) >= 0.8, f"{prefix}:readable_hold_too_short", errors)

    if route in {"official_evidence", "sourced_chart"}:
        validate_evidence(segment.get("evidence"), segment_id, base, errors)

    chart = segment.get("chart_plan", {})
    if route == "sourced_chart" or chart.get("self_drawn") is True:
        require(chart.get("self_drawn") is True, f"{prefix}:sourced_chart_not_self_drawn", errors)
        require(chart.get("source_footer_required") is True, f"{prefix}:chart_source_footer_not_required", errors)
        require(filled(chart.get("source_footer_text")), f"{prefix}:chart_source_footer_missing", errors)
        validate_evidence(segment.get("evidence"), segment_id, base, errors)
        source_ids = chart.get("source_ids")
        evidence_ids = {
            str(item.get("source_id"))
            for item in segment.get("evidence", [])
            if isinstance(item, dict) and filled(item.get("source_id"))
        }
        require(isinstance(source_ids, list) and len(source_ids) > 0,
                f"{prefix}:chart_source_ids_missing", errors)
        if isinstance(source_ids, list):
            require(set(map(str, source_ids)) == evidence_ids,
                    f"{prefix}:chart_source_ids_do_not_match_evidence", errors)

    i2v = segment.get("i2v_plan", {})
    if route in {"image_to_video", "hybrid"} or i2v.get("used") is True:
        require(i2v.get("used") is True, f"{prefix}:i2v_plan_missing", errors)
        require(filled(i2v.get("provider")), f"{prefix}:i2v_provider_missing", errors)
        require(i2v.get("model_generates_core_readable_chinese") is False,
                f"{prefix}:i2v_generates_core_chinese", errors)
        references = i2v.get("approved_reference_frames")
        require(isinstance(references, list) and any(filled(item) for item in references or []),
                f"{prefix}:approved_reference_frames_missing", errors)
        requested = float(i2v.get("requested_seconds", 0) or 0)
        planned = float(i2v.get("planned_coverage_seconds", 0) or 0)
        continuation = filled(i2v.get("continuation_plan"))
        require(requested > 0, f"{prefix}:i2v_requested_duration_missing", errors)
        require(planned >= duration - 0.05 or continuation,
                f"{prefix}:i2v_shorter_than_spoken_segment_without_continuation", errors)
        require(requested <= max_i2v + 0.05,
                f"{prefix}:single_i2v_request_exceeds_provider_limit", errors)

    if route == "hybrid":
        hybrid = segment.get("hybrid_plan", {})
        require(hybrid.get("used") is True, f"{prefix}:hybrid_plan_missing", errors)
        require(hybrid.get("unique_primary_visual") is True, f"{prefix}:hybrid_has_competing_primary", errors)
        require(filled(hybrid.get("i2v_responsibility")), f"{prefix}:hybrid_i2v_responsibility_missing", errors)
        require(filled(hybrid.get("native_data_or_text_layer_id")),
                f"{prefix}:hybrid_native_data_layer_missing", errors)
        require(hybrid.get("i2v_receives_exact_text_or_data") is False,
                f"{prefix}:hybrid_exact_information_sent_to_i2v", errors)
        require(filled(hybrid.get("auxiliary_layer_exit")), f"{prefix}:hybrid_auxiliary_exit_missing", errors)

    containers = segment.get("container_plan", {})
    communicative = int(containers.get("communicative_container_count", 0) or 0)
    container_records = containers.get("container_records")
    require(isinstance(container_records, list), f"{prefix}:container_records_not_array", errors)
    if isinstance(container_records, list):
        require(len(container_records) == communicative,
                f"{prefix}:container_record_count_mismatch", errors)
    if communicative > 0:
        require(int(containers.get("blank_communicative_container_count", 1)) == 0,
                f"{prefix}:blank_communicative_container", errors)
        require(containers.get("all_text_uses_parent_local_coordinates") is True,
                f"{prefix}:text_not_parent_local", errors)
        require(int(containers.get("detached_overlay_text_count", 1)) == 0,
                f"{prefix}:detached_overlay_text", errors)
        if isinstance(container_records, list):
            for index, record in enumerate(container_records):
                record_prefix = f"{prefix}:container[{index}]"
                if not isinstance(record, dict):
                    errors.append(f"{record_prefix}:not_object")
                    continue
                for field in ("container_id", "content_text", "parent_layer_id"):
                    require(filled(record.get(field)), f"{record_prefix}:{field}_missing", errors)
                require(record.get("coordinate_space") == "parent_local",
                        f"{record_prefix}:coordinate_space_not_parent_local", errors)
                require(record.get("clip_to_container") is True,
                        f"{record_prefix}:clip_to_container_failed", errors)
                require(record.get("moves_with_parent") is True,
                        f"{record_prefix}:moves_with_parent_failed", errors)
                validate_file(record.get("visual_evidence_path"), record.get("visual_evidence_sha256"), base,
                              f"{record_prefix}:visual_evidence", errors)
                visual_path = resolved_path(record.get("visual_evidence_path"), base)
                if visual_path is not None:
                    validate_visual_file(visual_path, f"{record_prefix}:visual_evidence", errors)

    mobile = segment.get("mobile_readability", {})
    require(mobile.get("core_content_in_center_safe_area") is True, f"{prefix}:core_outside_safe_area", errors)
    require(int(mobile.get("caption_conflict_count", 1)) == 0, f"{prefix}:caption_conflict", errors)
    require(mobile.get("viewer_can_read_before_exit") is True, f"{prefix}:viewer_cannot_read_before_exit", errors)


def validate_storyboard(data: dict, path: Path, stage: str, trusted_bgm_registry: Path | None = None) -> list[str]:
    errors: list[str] = []
    base = path.parent

    try:
        schema = float(data.get("schema_version", 0))
    except (TypeError, ValueError):
        schema = 0
    require(schema >= 1.0, "storyboard:old_schema", errors)
    require(data.get("mode") == "production", "storyboard:not_production_mode", errors)
    reject_quota_fields(data, "storyboard", errors)

    clock = data.get("production_clock", {})
    require(clock.get("starts_after_locked_script_evidence_and_audio") is True,
            "clock:wrong_start_condition", errors)
    for field in ("locked_script_ready", "evidence_pack_ready", "final_narration_ready", "same_day_delivery_target"):
        require(clock.get(field) is True, f"clock:{field}_failed", errors)
    require(filled(clock.get("started_at")), "clock:start_time_missing", errors)
    require(clock.get("fixed_stage_time_limits") is False, "clock:fixed_stage_limits_forbidden", errors)
    require(clock.get("quality_gates_may_be_skipped_for_deadline") is False,
            "clock:quality_skip_allowed", errors)

    director = data.get("director_interpretation", {})
    for field in ("core_promise", "audience_starting_question", "opening_first_3_seconds_value", "opening_first_10_seconds_value", "final_takeaway", "desired_audience_action"):
        require(filled(director.get(field)), f"director:{field}_missing", errors)
    require(isinstance(director.get("narrative_arc"), list) and any(filled(x) for x in director.get("narrative_arc", [])),
            "director:narrative_arc_missing", errors)

    policy = data.get("planning_policy", {})
    require(policy.get("fixed_chapter_count") is None, "planning:fixed_chapter_count_forbidden", errors)
    require(policy.get("fixed_shot_count") is None, "planning:fixed_shot_count_forbidden", errors)
    require(policy.get("visual_segment_count_is_derived") is True,
            "planning:visual_segment_count_not_derived", errors)
    require(policy.get("segment_count_driven_by_semantics") is True, "planning:not_semantic_driven", errors)
    require(policy.get("viewer_comprehension_before_cut") is True, "planning:comprehension_not_required", errors)
    for field in ("forced_slow_motion_allowed", "freeze_frame_padding_allowed", "meaningless_loop_padding_allowed", "static_flash_padding_allowed"):
        require(policy.get(field) is False, f"planning:{field}", errors)
    max_i2v = float(policy.get("provider_typical_max_i2v_seconds", 0) or 0)
    require(max_i2v > 0, "planning:i2v_limit_missing", errors)
    require(max_i2v <= 10.0, "planning:i2v_limit_above_10_seconds", errors)

    coverage = data.get("audio_coverage", {})
    duration = float(coverage.get("duration_seconds", 0) or 0)
    tolerance = float(coverage.get("tolerance_seconds", 0.1) or 0.1)
    require(0 < tolerance <= 0.1, "coverage:tolerance_too_wide", errors)
    require(duration > 0, "coverage:audio_duration_missing", errors)
    validate_file(coverage.get("master_audio_path"), coverage.get("master_audio_sha256"), base, "coverage:master_audio", errors)
    validate_file(coverage.get("locked_srt_path"), coverage.get("locked_srt_sha256"), base, "coverage:locked_srt", errors)
    srt_cues: dict[str, tuple[float, float, str]] = {}
    locked_srt_path = resolved_path(coverage.get("locked_srt_path"), base)
    if locked_srt_path is not None and locked_srt_path.is_file():
        try:
            srt_cues = parse_srt(locked_srt_path)
            require(len(srt_cues) > 0, "coverage:locked_srt_has_no_cues", errors)
        except (OSError, ValueError):
            errors.append("coverage:locked_srt_parse_failed")
    master_audio_path = resolved_path(coverage.get("master_audio_path"), base)
    if master_audio_path is not None and master_audio_path.is_file():
        try:
            probed_duration, stream_types = probe_media(master_audio_path)
            require("audio" in stream_types, "coverage:master_audio_stream_missing", errors)
            require(abs(probed_duration - duration) <= tolerance,
                    "coverage:declared_duration_does_not_match_master_audio", errors)
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            errors.append("coverage:master_audio_probe_failed")
    require(float(coverage.get("coverage_start_seconds", -1)) == 0, "coverage:not_starting_at_zero", errors)
    require(abs(float(coverage.get("coverage_end_seconds", 0)) - duration) <= tolerance,
            "coverage:end_mismatch", errors)
    require(float(coverage.get("gap_seconds", 1)) <= tolerance, "coverage:reported_gap", errors)
    require(float(coverage.get("overlap_seconds", 1)) <= tolerance, "coverage:reported_overlap", errors)

    segments = data.get("visual_segments")
    require(isinstance(segments, list) and len(segments) > 0, "segments:empty", errors)
    if isinstance(segments, list) and segments:
        require(policy.get("actual_visual_segment_count") == len(segments),
                "planning:actual_visual_segment_count_mismatch", errors)
        ordered = sorted((segment for segment in segments if isinstance(segment, dict)), key=lambda x: float(x.get("start_seconds", 0) or 0))
        require(len(ordered) == len(segments), "segments:not_objects", errors)
        previous_end = 0.0
        previous_segment: dict | None = None
        previous_cue_ids: set[str] = set()
        for index, segment in enumerate(ordered):
            start = segment.get("start_seconds")
            if isinstance(start, (int, float)):
                delta = float(start) - previous_end
                require(abs(delta) <= tolerance, f"coverage:segment_{index + 1}_{'gap' if delta > 0 else 'overlap'}", errors)
            validate_segment(segment, max_i2v, base, errors)
            cue_ids = {str(item) for item in segment.get("srt_cue_ids", []) if filled(item)}
            for cue_id in cue_ids:
                require(cue_id in srt_cues, f"segment:{segment.get('id', 'unknown')}:srt_cue_not_found:{cue_id}", errors)
            existing_cues = [srt_cues[cue_id] for cue_id in cue_ids if cue_id in srt_cues]
            if existing_cues and isinstance(segment.get("start_seconds"), (int, float)) and isinstance(segment.get("end_seconds"), (int, float)):
                cue_start = min(item[0] for item in existing_cues)
                cue_end = max(item[1] for item in existing_cues)
                require(float(segment["end_seconds"]) > cue_start - tolerance and float(segment["start_seconds"]) < cue_end + tolerance,
                        f"segment:{segment.get('id', 'unknown')}:srt_cues_do_not_overlap_segment", errors)
            if previous_segment is not None:
                same_event = segment.get("semantic_event_id") == previous_segment.get("semantic_event_id")
                shared_cues = bool(cue_ids & previous_cue_ids)
                if same_event or shared_cues:
                    require(segment.get("continuation_of") == previous_segment.get("id"),
                            f"segment:{segment.get('id', 'unknown')}:duplicate_event_not_continuation", errors)
                else:
                    require(filled(segment.get("new_primary_reason")),
                            f"segment:{segment.get('id', 'unknown')}:new_primary_reason_missing", errors)
            else:
                require(filled(segment.get("new_primary_reason")),
                        f"segment:{segment.get('id', 'unknown')}:new_primary_reason_missing", errors)
            if isinstance(segment.get("end_seconds"), (int, float)):
                previous_end = float(segment["end_seconds"])
            previous_segment = segment
            previous_cue_ids = cue_ids
        require(abs(previous_end - duration) <= tolerance, "coverage:segments_do_not_reach_audio_end", errors)

    music = data.get("music", {})
    opted_out = music.get("user_opted_out") is True
    require(music.get("required") is True or opted_out, "music:not_required_without_optout", errors)
    if not opted_out:
        brief = music.get("brief", {})
        for field in ("theme_and_mood", "energy_arc", "instrumentation_and_texture", "speech_role"):
            require(filled(brief.get(field)), f"music:brief_{field}_missing", errors)
        require(brief.get("no_vocals") is True, "music:vocals_not_forbidden", errors)
        require(music.get("newly_created_or_newly_licensed_for_project") is True,
                "music:not_new_for_project", errors)
        require(music.get("reused_from_previous_project") is False, "music:previous_bgm_reused", errors)
        require(filled(music.get("provider_or_source")), "music:source_missing", errors)
        require(filled(music.get("canonical_track_id")), "music:canonical_track_id_missing", errors)
        require(filled(music.get("generation_or_license_record")),
                "music:generation_or_license_record_missing", errors)
        require(music.get("ducking_planned") is True, "music:ducking_not_planned", errors)
        require(music.get("full_runtime_coverage_planned") is True, "music:full_coverage_not_planned", errors)

    if stage == "batch":
        require(director.get("user_approved") is True, "director:not_user_approved", errors)
        require(filled(director.get("approval_quote")), "director:approval_quote_missing", errors)
        require(filled(director.get("approved_at")), "director:approval_time_missing", errors)

        artifacts = data.get("storyboard_artifacts", {})
        validate_file(artifacts.get("plain_language_director_brief_path"), artifacts.get("plain_language_director_brief_sha256"), base, "artifacts:director_brief", errors)
        validate_file(artifacts.get("visual_storyboard_path"), artifacts.get("visual_storyboard_sha256"), base, "artifacts:visual_storyboard", errors)
        visual_storyboard_path = resolved_path(artifacts.get("visual_storyboard_path"), base)
        if visual_storyboard_path is not None:
            validate_visual_file(visual_storyboard_path, "artifacts:visual_storyboard", errors)
        require(artifacts.get("mobile_9x16_preview") is True, "artifacts:no_mobile_preview", errors)
        require(artifacts.get("all_text_bearing_segments_previewed") is True,
                "artifacts:text_segments_not_previewed", errors)

        animatic = data.get("full_voiced_animatic", {})
        for field in ("required", "uses_locked_narration", "uses_locked_caption_style", "covers_full_runtime", "user_approved"):
            require(animatic.get(field) is True, f"animatic:{field}_failed", errors)
        require(animatic.get("has_video_stream") is True, "animatic:video_stream_missing", errors)
        require(animatic.get("has_audio_stream") is True, "animatic:audio_stream_missing", errors)
        require(abs(float(animatic.get("duration_seconds", 0) or 0) - duration) <= tolerance,
                "animatic:duration_mismatch", errors)
        require(int(animatic.get("missing_visual_segment_count", 1)) == 0,
                "animatic:missing_visual_segments", errors)
        require(int(animatic.get("forced_slow_or_freeze_count", 1)) == 0,
                "animatic:forced_slow_or_freeze", errors)
        require(filled(animatic.get("approval_quote")), "animatic:approval_quote_missing", errors)
        require(filled(animatic.get("approved_at")), "animatic:approval_time_missing", errors)
        validate_file(animatic.get("path"), animatic.get("sha256"), base, "animatic", errors)
        validate_file(animatic.get("probe_report_path"), animatic.get("probe_report_sha256"), base, "animatic:probe", errors)
        animatic_path = resolved_path(animatic.get("path"), base)
        if animatic_path is not None and animatic_path.is_file():
            try:
                probed_duration, stream_types = probe_media(animatic_path)
                require("video" in stream_types, "animatic:real_video_stream_missing", errors)
                require("audio" in stream_types, "animatic:real_audio_stream_missing", errors)
                require(abs(probed_duration - duration) <= tolerance, "animatic:real_duration_mismatch", errors)
                if master_audio_path is not None and master_audio_path.is_file():
                    similarity = narration_similarity(master_audio_path, animatic_path)
                    require(similarity >= 0.82, "animatic:locked_narration_audio_mismatch", errors)
            except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
                errors.append("animatic:real_media_probe_failed")

        if not opted_out:
            validate_file(music.get("asset_path"), music.get("asset_sha256"), base, "music", errors)
            validate_file(music.get("generation_or_license_record_path"), music.get("generation_or_license_record_sha256"), base, "music:source_record", errors)
            previous = str(music.get("previous_project_bgm_sha256", "")).strip().upper()
            current = str(music.get("asset_sha256", "")).strip().upper()
            if len(previous) == 64 and len(current) == 64:
                require(previous != current, "music:same_hash_as_previous_project", errors)
            current_track = str(music.get("canonical_track_id", "")).strip()
            previous_track = str(music.get("previous_project_canonical_track_id", "")).strip()
            if current_track and previous_track:
                require(current_track != previous_track, "music:same_track_id_as_previous_project", errors)
            fingerprint = str(music.get("audio_fingerprint", "")).strip()
            require(filled(fingerprint), "music:audio_fingerprint_missing", errors)
            current_windows = {
                str(item).strip() for item in music.get("audio_window_fingerprints", []) if filled(item)
            }
            require(len(current_windows) > 0, "music:audio_window_fingerprints_missing", errors)
            require(music.get("registry_checked") is True, "music:registry_not_checked", errors)
            registry_path = resolved_path(music.get("bgm_registry_path"), base)
            if trusted_bgm_registry is not None and registry_path is not None:
                require(registry_path.resolve() == trusted_bgm_registry.resolve(),
                        "music:untrusted_or_truncated_registry_path", errors)
            validate_file(music.get("bgm_registry_path"), music.get("bgm_registry_sha256"), base, "music:registry", errors)
            match_count = 0
            if registry_path is not None and registry_path.is_file():
                try:
                    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
                    entries = registry.get("entries", []) if isinstance(registry, dict) else []
                    for entry in entries:
                        if not isinstance(entry, dict) or entry.get("project_id") == data.get("project_id"):
                            continue
                        if (
                            str(entry.get("canonical_track_id", "")).strip() == current_track
                            or str(entry.get("audio_fingerprint", "")).strip() == fingerprint
                            or str(entry.get("asset_sha256", "")).strip().upper() == current
                            or bool(current_windows & {str(item).strip() for item in entry.get("audio_window_fingerprints", []) if filled(item)})
                        ):
                            match_count += 1
                except (OSError, json.JSONDecodeError):
                    errors.append("music:registry_invalid_json")
            require(int(music.get("registry_match_count", -1)) == match_count,
                    "music:registry_match_count_incorrect", errors)
            if match_count > 0:
                require(music.get("user_approved_reuse_exception") is True,
                        "music:registry_match_without_user_exception", errors)
                require(filled(music.get("reuse_exception_quote")), "music:reuse_exception_quote_missing", errors)
                require(filled(music.get("reuse_exception_approved_at")), "music:reuse_exception_time_missing", errors)

        approval = data.get("approval", {})
        require(approval.get("storyboard_user_approved") is True, "approval:storyboard_not_approved", errors)
        require(filled(approval.get("storyboard_approval_quote")), "approval:storyboard_quote_missing", errors)
        require(filled(approval.get("storyboard_approved_at")), "approval:storyboard_time_missing", errors)
        brand = approval.get("brand_06_signoff", {})
        technical = approval.get("technical_07_signoff", {})
        require(isinstance(brand, dict) and brand.get("status") == "pass", "approval:brand_06_not_pass", errors)
        require(isinstance(technical, dict) and technical.get("status") == "pass", "approval:technical_07_not_pass", errors)
        board_hash = str(data.get("storyboard_artifacts", {}).get("visual_storyboard_sha256", "")).upper()
        for signoff, department, scope in ((brand, "06｜品牌设计部", "brand_06"), (technical, "07｜技术管家", "technical_07")):
            if not isinstance(signoff, dict):
                continue
            require(signoff.get("department") == department, f"approval:{scope}_department_mismatch", errors)
            require(filled(signoff.get("signer_id")), f"approval:{scope}_signer_missing", errors)
            require(filled(signoff.get("signed_at")), f"approval:{scope}_time_missing", errors)
            require(str(signoff.get("reviewed_visual_storyboard_sha256", "")).upper() == board_hash,
                    f"approval:{scope}_board_hash_mismatch", errors)
            validate_file(signoff.get("evidence_path"), signoff.get("evidence_sha256"), base,
                          f"approval:{scope}", errors)
            signoff_path = resolved_path(signoff.get("evidence_path"), base)
            if signoff_path is not None and signoff_path.is_file():
                try:
                    signoff_record = json.loads(signoff_path.read_text(encoding="utf-8-sig"))
                    require(signoff_record.get("project_id") == data.get("project_id"),
                            f"approval:{scope}_evidence_project_mismatch", errors)
                    require(signoff_record.get("department") == department,
                            f"approval:{scope}_evidence_department_mismatch", errors)
                    require(signoff_record.get("signer_id") == signoff.get("signer_id"),
                            f"approval:{scope}_evidence_signer_mismatch", errors)
                    require(signoff_record.get("signed_at") == signoff.get("signed_at"),
                            f"approval:{scope}_evidence_time_mismatch", errors)
                    require(signoff_record.get("status") == "pass",
                            f"approval:{scope}_evidence_not_pass", errors)
                    require(str(signoff_record.get("reviewed_visual_storyboard_sha256", "")).upper() == board_hash,
                            f"approval:{scope}_evidence_board_hash_mismatch", errors)
                except (OSError, json.JSONDecodeError):
                    errors.append(f"approval:{scope}_evidence_invalid_json")
        if isinstance(brand, dict) and isinstance(technical, dict):
            require(str(brand.get("signer_id", "")) != str(technical.get("signer_id", "")),
                    "approval:independent_dual_signoff_required", errors)
        require(approval.get("batch_generation_allowed") is True, "approval:batch_not_allowed", errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate director storyboard, visual routing, animatic and per-project music.")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--stage", choices=("plan", "batch"), default="plan")
    args = parser.parse_args()
    path = args.contract.resolve()
    if not path.is_file():
        print(f"FAIL contract missing: {path}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    errors = validate_storyboard(data, path, args.stage, trusted_bgm_registry_from_local_config(data))
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print(f"DIRECTOR STORYBOARD GATE CLOSED ({len(errors)} failures)")
        return 1
    print(f"DIRECTOR STORYBOARD {args.stage.upper()} GATE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
