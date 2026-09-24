#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from validate_dynamic_asset_duration import validate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def make_wave(path: Path, seconds: int = 2, sample_rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * sample_rate * seconds)


def make_video(path: Path, seconds: int = 2) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"testsrc2=size=64x64:rate=10:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast", str(path)
    ], check=True)


def make_static_video(path: Path, seconds: int = 2) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=navy:s=64x64:r=10:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", str(path)
    ], check=True)


def make_looped_video(source: Path, output: Path, seconds: int = 4) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-stream_loop", "1", "-i", str(source),
        "-t", str(seconds), "-an", "-c:v", "libx264", "-preset", "ultrafast", str(output)
    ], check=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        media = root / "motion.mp4"
        continuation_media = root / "continuation.mp4"
        audio_only = root / "audio.wav"
        static_media = root / "static.mp4"
        looped_media = root / "looped.mp4"
        make_video(media)
        make_video(continuation_media)
        make_wave(audio_only)
        make_static_video(static_media)
        make_looped_video(media, looped_media)
        good = {
            "schema_version": "1.0",
            "project_id": "test",
            "project_root": str(root),
            "ffprobe_required": True,
            "actual_record_count": 1,
            "records": [{
                "visual_segment_id": "V01",
                "spoken_start_seconds": 0,
                "spoken_end_seconds": 4,
                "required_coverage_seconds": 4,
                "asset_path": media.name,
                "asset_sha256": digest(media),
                "declared_source_duration_seconds": 2,
                "timeline_used_seconds": 2,
                "timeline_start_seconds": 0,
                "timeline_end_seconds": 2,
                "maximum_continuous_i2v_seconds": 10,
                "over_limit_exception_approved": False,
                "over_limit_exception_quote": "",
                "over_limit_exception_approved_at": "",
                "playback_speed": 1.0,
                "intentional_retiming_approved": False,
                "intentional_retiming_approval_reason": "",
                "continuation_segments": [{
                    "start_seconds": 2,
                    "end_seconds": 4,
                    "coverage_seconds": 2,
                    "mode": "native_mg",
                    "handoff": "MG接住后半段",
                    "asset_path": continuation_media.name,
                    "asset_sha256": digest(continuation_media),
                    "declared_source_duration_seconds": 2,
                    "content_matches_approved_segment": True,
                    "forced_freeze_seconds": 0,
                    "meaningless_loop_count": 0,
                    "static_flash_padding_count": 0
                }],
                "forced_freeze_seconds": 0,
                "meaningless_loop_count": 0,
                "intentional_motion_loop_approved": False,
                "intentional_motion_loop_approval_quote": "",
                "intentional_motion_loop_approved_at": "",
                "static_flash_padding_count": 0,
                "maximum_allowed_unexplained_freeze_seconds": 0.8,
                "intentional_freeze_approved": False,
                "intentional_freeze_approval_reason": "",
                "director_storyboard_route": "hybrid",
                "content_matches_approved_segment": True,
            }],
            "summary": {
                "reviewed_record_count": 1,
                "duration_probe_failure_count": 0,
                "hash_mismatch_count": 0,
                "shortfall_without_continuation_count": 0,
                "forced_slow_count": 0,
                "freeze_loop_or_static_flash_padding_count": 0,
                "content_mismatch_count": 0,
                "status": "pass",
            },
        }
        manifest = root / "duration.json"
        manifest.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        assert not validate(good, manifest, verify_media=True)

        cases = [
            ("shortfall", lambda d: d["records"][0].update(continuation_segments=[]), "duration_shortfall_without_continuation"),
            ("forced_slow", lambda d: d["records"][0].update(playback_speed=0.5), "forced_slow_or_speed_change"),
            ("mild_slow", lambda d: d["records"][0].update(playback_speed=0.95), "forced_slow_or_speed_change"),
            ("freeze", lambda d: d["records"][0].update(forced_freeze_seconds=1), "forced_freeze_padding"),
            ("loop", lambda d: d["records"][0].update(meaningless_loop_count=1), "meaningless_loop_padding"),
            ("static_flash", lambda d: d["records"][0].update(static_flash_padding_count=1), "static_flash_padding"),
            ("hash", lambda d: d["records"][0].update(asset_sha256="A" * 64), "asset_hash_mismatch"),
            ("content", lambda d: d["records"][0].update(content_matches_approved_segment=False), "content_mismatch"),
            ("over_10", lambda d: d["records"][0].update(timeline_used_seconds=12, declared_source_duration_seconds=12), "i2v_over_10_without_exception"),
            ("audio_only", lambda d: d["records"][0].update(asset_path=audio_only.name, asset_sha256=digest(audio_only), declared_source_duration_seconds=2), "video_stream_missing"),
            ("continuation_no_asset", lambda d: d["records"][0]["continuation_segments"][0].update(asset_path=""), "continuation[0]:asset_path_missing"),
            ("continuation_gap", lambda d: d["records"][0]["continuation_segments"][0].update(start_seconds=2.5, end_seconds=4.5), "continuation[0]:timeline_gap_or_overlap"),
            ("real_static_video", lambda d: d["records"][0].update(asset_path=static_media.name, asset_sha256=digest(static_media), declared_source_duration_seconds=2), "real_media_contains_unapproved_freeze"),
            ("repeated_motion_loop", lambda d: d["records"][0].update(asset_path=looped_media.name, asset_sha256=digest(looped_media), declared_source_duration_seconds=4, timeline_used_seconds=4, timeline_end_seconds=4, continuation_segments=[]), "repeated_motion_loop_detected"),
            ("continuation_loop_boolean_only", lambda d: d["records"][0].update(continuation_segments=[{"start_seconds": 2, "end_seconds": 4, "coverage_seconds": 2, "mode": "image_to_video", "handoff": "循环续接", "asset_path": looped_media.name, "asset_sha256": digest(looped_media), "declared_source_duration_seconds": 4, "content_matches_approved_segment": True, "forced_freeze_seconds": 0, "meaningless_loop_count": 0, "static_flash_padding_count": 0, "intentional_motion_loop_approved": True}]), "continuation[0]:motion_loop_approval_quote_missing"),
        ]
        for name, mutate, expected in cases:
            candidate = copy.deepcopy(good)
            mutate(candidate)
            errors = validate(candidate, manifest, verify_media=True)
            assert any(expected in error for error in errors), (name, expected, errors)
        skipped = subprocess.run([
            "python", str(Path(__file__).with_name("validate_dynamic_asset_duration.py")),
            "--manifest", str(manifest), "--skip-media-probe"
        ], capture_output=True, text=True)
        assert skipped.returncode != 0 and "cannot unlock" in skipped.stdout
        print(f"DYNAMIC ASSET DURATION NEGATIVE TESTS PASS {len(cases)}/{len(cases)}")


if __name__ == "__main__":
    main()
