#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import re
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require(condition: bool, code: str, errors: list[str]) -> None:
    if not condition:
        errors.append(code)


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


def maximum_freeze_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf", "freezedetect=n=0.002:d=0.8", "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    matches = [float(value) for value in re.findall(r"freeze_duration:\s*([0-9.]+)", result.stderr)]
    starts = [float(value) for value in re.findall(r"freeze_start:\s*([0-9.]+)", result.stderr)]
    if starts and len(starts) > len(matches):
        try:
            duration, _ = probe_media(path)
            matches.append(max(0.0, duration - starts[-1]))
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            pass
    return max(matches, default=0.0)


def repeated_motion_loop_period(path: Path, sample_fps: int = 5, side: int = 32) -> float:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-an",
            "-vf", f"fps={sample_fps},scale={side}:{side},format=gray",
            "-f", "rawvideo", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    frame_size = side * side
    frames = [result.stdout[offset:offset + frame_size] for offset in range(0, len(result.stdout) - frame_size + 1, frame_size)]
    minimum_period = max(3, sample_fps)
    for period in range(minimum_period, len(frames) // 2 + 1):
        comparable = len(frames) - period
        if comparable < period:
            continue
        difference_sum = 0
        pixel_count = 0
        for index in range(comparable):
            left = frames[index]
            right = frames[index + period]
            difference_sum += sum(abs(a - b) for a, b in zip(left, right))
            pixel_count += frame_size
        mean_difference = difference_sum / max(1, pixel_count)
        if mean_difference <= 2.5:
            return period / sample_fps
    return 0.0


def validate(data: dict, manifest_path: Path, verify_media: bool = True) -> list[str]:
    errors: list[str] = []
    require(str(data.get("schema_version")) == "1.0", "manifest:invalid_schema", errors)
    root_value = str(data.get("project_root", "")).strip()
    root = Path(root_value) if root_value else manifest_path.parent
    require(root.is_absolute(), "manifest:project_root_not_absolute", errors)
    require(data.get("ffprobe_required") is True, "manifest:ffprobe_not_required", errors)

    records = data.get("records")
    require(isinstance(records, list) and len(records) > 0, "records:empty", errors)
    if not isinstance(records, list):
        return errors
    require(data.get("actual_record_count") == len(records), "records:actual_count_mismatch", errors)

    for index, record in enumerate(records):
        prefix = f"record[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix}:not_object")
            continue
        require(bool(str(record.get("visual_segment_id", "")).strip()), f"{prefix}:visual_segment_id_missing", errors)
        start = float(record.get("spoken_start_seconds", 0) or 0)
        end = float(record.get("spoken_end_seconds", 0) or 0)
        required = float(record.get("required_coverage_seconds", 0) or 0)
        require(end > start, f"{prefix}:spoken_range_invalid", errors)
        require(abs(required - (end - start)) <= 0.1, f"{prefix}:required_coverage_mismatch", errors)

        value = str(record.get("asset_path", "")).strip()
        digest = str(record.get("asset_sha256", "")).strip().upper()
        require(bool(value) and "__FILL" not in value, f"{prefix}:asset_path_missing", errors)
        require(len(digest) == 64, f"{prefix}:asset_sha256_missing", errors)
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        require(path.is_file(), f"{prefix}:asset_file_missing", errors)

        actual_duration = float(record.get("declared_source_duration_seconds", 0) or 0)
        used_duration = float(record.get("timeline_used_seconds", 0) or 0)
        timeline_start = float(record.get("timeline_start_seconds", -1) or 0)
        timeline_end = float(record.get("timeline_end_seconds", -1) or 0)
        maximum_continuous = float(record.get("maximum_continuous_i2v_seconds", 0) or 0)
        require(0 < maximum_continuous <= 10.0, f"{prefix}:maximum_i2v_limit_invalid", errors)
        require(used_duration > 0, f"{prefix}:timeline_used_duration_missing", errors)
        require(abs(timeline_start - start) <= 0.05, f"{prefix}:timeline_start_mismatch", errors)
        require(abs(timeline_end - (timeline_start + used_duration)) <= 0.05,
                f"{prefix}:timeline_end_mismatch", errors)
        if path.is_file() and len(digest) == 64:
            require(sha256(path) == digest, f"{prefix}:asset_hash_mismatch", errors)
        if verify_media and path.is_file():
            try:
                probed, stream_types = probe_media(path)
                require("video" in stream_types, f"{prefix}:video_stream_missing", errors)
                require(abs(probed - actual_duration) <= 0.12,
                        f"{prefix}:declared_duration_does_not_match_media", errors)
                detected_freeze = maximum_freeze_duration(path)
                freeze_limit = float(record.get("maximum_allowed_unexplained_freeze_seconds", 0.8) or 0.8)
                require(0 < freeze_limit <= 0.8, f"{prefix}:freeze_limit_invalid", errors)
                if detected_freeze > freeze_limit + 0.05:
                    require(record.get("intentional_freeze_approved") is True,
                            f"{prefix}:real_media_contains_unapproved_freeze", errors)
                    require(bool(str(record.get("intentional_freeze_approval_reason", "")).strip()),
                            f"{prefix}:intentional_freeze_reason_missing", errors)
                loop_period = repeated_motion_loop_period(path)
                if loop_period > 0:
                    require(record.get("intentional_motion_loop_approved") is True,
                            f"{prefix}:repeated_motion_loop_detected", errors)
                    require(bool(str(record.get("intentional_motion_loop_approval_quote", "")).strip()),
                            f"{prefix}:motion_loop_approval_quote_missing", errors)
                    require(bool(str(record.get("intentional_motion_loop_approved_at", "")).strip()),
                            f"{prefix}:motion_loop_approval_time_missing", errors)
                actual_duration = probed
            except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
                errors.append(f"{prefix}:ffprobe_failed")

        speed = float(record.get("playback_speed", 0) or 0)
        require(speed > 0, f"{prefix}:playback_speed_invalid", errors)
        intentional = record.get("intentional_retiming_approved") is True
        if speed < 0.98 or speed > 1.02:
            require(intentional, f"{prefix}:forced_slow_or_speed_change", errors)
            require(bool(str(record.get("intentional_retiming_approval_reason", "")).strip()),
                    f"{prefix}:retiming_approval_reason_missing", errors)

        effective = actual_duration / speed if speed > 0 else 0
        require(used_duration <= effective + 0.1, f"{prefix}:timeline_uses_more_than_real_asset", errors)
        if used_duration > maximum_continuous + 0.05:
            require(record.get("over_limit_exception_approved") is True,
                    f"{prefix}:i2v_over_10_without_exception", errors)
            require(bool(str(record.get("over_limit_exception_quote", "")).strip()),
                    f"{prefix}:i2v_over_10_exception_quote_missing", errors)
            require(bool(str(record.get("over_limit_exception_approved_at", "")).strip()),
                    f"{prefix}:i2v_over_10_exception_time_missing", errors)
        continuation = record.get("continuation_segments")
        continuation_total = 0.0
        continuation_cursor = timeline_end
        if isinstance(continuation, list):
            for continuation_index, item in enumerate(continuation):
                if isinstance(item, dict):
                    item_prefix = f"{prefix}:continuation[{continuation_index}]"
                    item_start = float(item.get("start_seconds", -1) or 0)
                    item_end = float(item.get("end_seconds", -1) or 0)
                    item_coverage = float(item.get("coverage_seconds", 0) or 0)
                    require(item_end > item_start, f"{item_prefix}:range_invalid", errors)
                    require(abs(item_coverage - (item_end - item_start)) <= 0.05,
                            f"{item_prefix}:coverage_mismatch", errors)
                    require(abs(item_start - continuation_cursor) <= 0.05,
                            f"{item_prefix}:timeline_gap_or_overlap", errors)
                    continuation_cursor = item_end
                    continuation_total += item_coverage
                    require(bool(str(item.get("mode", "")).strip()), f"{item_prefix}:mode_missing", errors)
                    require(bool(str(item.get("handoff", "")).strip()), f"{item_prefix}:handoff_missing", errors)
                    continuation_path_value = str(item.get("asset_path", "")).strip()
                    continuation_hash = str(item.get("asset_sha256", "")).strip().upper()
                    require(bool(continuation_path_value), f"{item_prefix}:asset_path_missing", errors)
                    require(len(continuation_hash) == 64, f"{item_prefix}:asset_sha256_missing", errors)
                    continuation_path = Path(continuation_path_value)
                    if not continuation_path.is_absolute():
                        continuation_path = root / continuation_path
                    require(continuation_path.is_file(), f"{item_prefix}:asset_file_missing", errors)
                    if continuation_path.is_file() and len(continuation_hash) == 64:
                        require(sha256(continuation_path) == continuation_hash,
                                f"{item_prefix}:asset_hash_mismatch", errors)
                    declared_continuation_duration = float(item.get("declared_source_duration_seconds", 0) or 0)
                    if verify_media and continuation_path.is_file():
                        try:
                            continuation_duration, continuation_streams = probe_media(continuation_path)
                            require("video" in continuation_streams, f"{item_prefix}:video_stream_missing", errors)
                            require(abs(continuation_duration - declared_continuation_duration) <= 0.12,
                                    f"{item_prefix}:declared_duration_does_not_match_media", errors)
                            require(continuation_duration >= item_coverage - 0.1,
                                    f"{item_prefix}:real_asset_shorter_than_coverage", errors)
                            continuation_freeze = maximum_freeze_duration(continuation_path)
                            continuation_freeze_limit = float(item.get("maximum_allowed_unexplained_freeze_seconds", 0.8) or 0.8)
                            if continuation_freeze > continuation_freeze_limit + 0.05:
                                require(item.get("intentional_freeze_approved") is True,
                                        f"{item_prefix}:real_media_contains_unapproved_freeze", errors)
                            continuation_loop = repeated_motion_loop_period(continuation_path)
                            if continuation_loop > 0:
                                require(item.get("intentional_motion_loop_approved") is True,
                                        f"{item_prefix}:repeated_motion_loop_detected", errors)
                                require(bool(str(item.get("intentional_motion_loop_approval_quote", "")).strip()),
                                        f"{item_prefix}:motion_loop_approval_quote_missing", errors)
                                require(bool(str(item.get("intentional_motion_loop_approved_at", "")).strip()),
                                        f"{item_prefix}:motion_loop_approval_time_missing", errors)
                        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
                            errors.append(f"{item_prefix}:ffprobe_failed")
                    require(item.get("content_matches_approved_segment") is True,
                            f"{item_prefix}:content_mismatch", errors)
                    require(float(item.get("forced_freeze_seconds", 1) or 0) == 0,
                            f"{item_prefix}:forced_freeze_padding", errors)
                    require(int(item.get("meaningless_loop_count", 1) or 0) == 0,
                            f"{item_prefix}:meaningless_loop_padding", errors)
                    require(int(item.get("static_flash_padding_count", 1) or 0) == 0,
                            f"{item_prefix}:static_flash_padding", errors)
        else:
            errors.append(f"{prefix}:continuation_segments_not_array")
        require(used_duration + continuation_total >= required - 0.1,
                f"{prefix}:duration_shortfall_without_continuation", errors)
        require(abs(continuation_cursor - end) <= 0.1,
                f"{prefix}:continuation_does_not_end_with_spoken_segment", errors)

        require(float(record.get("forced_freeze_seconds", 1) or 0) == 0,
                f"{prefix}:forced_freeze_padding", errors)
        require(int(record.get("meaningless_loop_count", 1) or 0) == 0,
                f"{prefix}:meaningless_loop_padding", errors)
        require(int(record.get("static_flash_padding_count", 1) or 0) == 0,
                f"{prefix}:static_flash_padding", errors)
        require(record.get("content_matches_approved_segment") is True,
                f"{prefix}:content_mismatch", errors)

    summary = data.get("summary", {})
    if isinstance(summary, dict) and summary.get("status") == "pass":
        require(summary.get("reviewed_record_count") == len(records), "summary:reviewed_count_mismatch", errors)
        for field in (
            "duration_probe_failure_count",
            "hash_mismatch_count",
            "shortfall_without_continuation_count",
            "forced_slow_count",
            "freeze_loop_or_static_flash_padding_count",
            "content_mismatch_count",
        ):
            require(int(summary.get(field, 1)) == 0, f"summary:{field}", errors)
    else:
        errors.append("summary:status_not_pass")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate real dynamic-asset duration against spoken coverage.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--skip-media-probe", action="store_true")
    args = parser.parse_args()
    if args.skip_media_probe:
        print("FAIL --skip-media-probe is draft-only and cannot unlock the production Gate")
        return 1
    path = args.manifest.resolve()
    if not path.is_file():
        print(f"FAIL manifest missing: {path}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    errors = validate(data, path, verify_media=not args.skip_media_probe)
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print(f"DYNAMIC ASSET DURATION GATE CLOSED ({len(errors)} failures)")
        return 1
    print("DYNAMIC ASSET DURATION GATE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
