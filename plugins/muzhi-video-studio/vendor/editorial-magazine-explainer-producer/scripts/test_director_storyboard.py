#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from validate_director_storyboard import validate_storyboard


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def make_wave(path: Path, seconds: int = 16, sample_rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate * seconds):
            sample = int(9000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(bytes(frames))


def make_image(path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64",
        "-frames:v", "1", str(path)
    ], check=True)


def good_contract(root: Path) -> dict:
    brief = root / "brief.md"
    board = root / "board.png"
    animatic = root / "animatic.mp4"
    music = root / "music.wav"
    source_snapshot = root / "official-source.png"
    animatic_probe = root / "animatic-probe.json"
    brand_review = root / "brand-review.json"
    technical_review = root / "technical-review.json"
    bgm_registry = root / "bgm-registry.json"
    music_record = root / "music-generation-record.json"
    voice = root / "voice.wav"
    locked_srt = root / "locked.srt"
    for path, body in ((brief, b"brief"),):
        path.write_bytes(body)
    make_wave(voice)
    make_wave(music)
    make_image(board)
    make_image(source_snapshot)
    brand_review.write_text(json.dumps({"project_id": "test", "department": "06｜品牌设计部", "signer_id": "brand-06", "signed_at": "2026-09-02T10:35:00+08:00", "status": "pass", "reviewed_visual_storyboard_sha256": digest(board)}), encoding="utf-8")
    technical_review.write_text(json.dumps({"project_id": "test", "department": "07｜技术管家", "signer_id": "technical-07", "signed_at": "2026-09-02T10:36:00+08:00", "status": "pass", "reviewed_visual_storyboard_sha256": digest(board)}), encoding="utf-8")
    locked_srt.write_text("1\n00:00:00,000 --> 00:00:08,000\n先看学生反应\n\n2\n00:00:08,000 --> 00:00:16,000\n再看准确数据\n", encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=10:d=16",
        "-i", str(voice), "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(animatic)
    ], check=True)
    animatic_probe.write_text(json.dumps({"has_video_stream": True, "has_audio_stream": True, "duration_seconds": 16}), encoding="utf-8")
    bgm_registry.write_text(json.dumps({"entries": [{"project_id": "older", "canonical_track_id": "older-track", "audio_fingerprint": "older-fingerprint", "audio_window_fingerprints": ["older-window"], "asset_sha256": "C" * 64}]}), encoding="utf-8")
    music_record.write_text(json.dumps({"provider": "Mureka", "job_id": "mureka-job-test-current"}), encoding="utf-8")
    evidence = {
        "source_id": "SRC01",
        "kind": "official_pdf",
        "path_or_url": "https://example.edu/2026-list.pdf",
        "publisher": "示例大学研究生院",
        "source_title": "2026拟录取名单",
        "year_or_date": "2026",
        "retrieved_at": "2026-09-02T09:30:00+08:00",
        "local_snapshot_path": source_snapshot.name,
        "local_snapshot_sha256": digest(source_snapshot),
        "supports": "录取人数与分数",
        "verified": True,
        "source_footer_text": "来源：示例大学2026拟录取名单",
        "integrated_with_design_carrier": True,
        "raw_browser_chrome_visible": False,
    }
    return {
        "schema_version": "1.0",
        "mode": "production",
        "project_id": "test",
        "project_root": str(root),
        "production_clock": {
            "starts_after_locked_script_evidence_and_audio": True,
            "locked_script_ready": True,
            "evidence_pack_ready": True,
            "final_narration_ready": True,
            "started_at": "2026-09-02T09:00:00+08:00",
            "same_day_delivery_target": True,
            "fixed_stage_time_limits": False,
            "quality_gates_may_be_skipped_for_deadline": False,
        },
        "director_interpretation": {
            "core_promise": "给出有证据的答案",
            "audience_starting_question": "这所学校能不能考",
            "opening_first_3_seconds_value": "直接给出学校",
            "opening_first_10_seconds_value": "展示证据范围",
            "final_takeaway": "会按学院和数据判断",
            "desired_audience_action": "保存并核对",
            "narrative_arc": ["答案", "证据", "方法"],
            "user_approved": True,
            "approval_quote": "导演理解通过",
            "approved_at": "2026-09-02T10:00:00+08:00",
        },
        "planning_policy": {
            "fixed_chapter_count": None,
            "fixed_shot_count": None,
            "actual_visual_segment_count": 2,
            "visual_segment_count_is_derived": True,
            "segment_count_driven_by_semantics": True,
            "viewer_comprehension_before_cut": True,
            "provider_typical_max_i2v_seconds": 10,
            "forced_slow_motion_allowed": False,
            "freeze_frame_padding_allowed": False,
            "meaningless_loop_padding_allowed": False,
            "static_flash_padding_allowed": False,
        },
        "audio_coverage": {
            "master_audio_path": voice.name,
            "master_audio_sha256": digest(voice),
            "locked_srt_path": locked_srt.name,
            "locked_srt_sha256": digest(locked_srt),
            "duration_seconds": 16,
            "coverage_start_seconds": 0,
            "coverage_end_seconds": 16,
            "gap_seconds": 0,
            "overlap_seconds": 0,
            "tolerance_seconds": 0.1,
        },
        "storyboard_artifacts": {
            "plain_language_director_brief_path": brief.name,
            "plain_language_director_brief_sha256": digest(brief),
            "visual_storyboard_path": board.name,
            "visual_storyboard_sha256": digest(board),
            "mobile_9x16_preview": True,
            "all_text_bearing_segments_previewed": True,
        },
        "visual_segments": [
            {
                "id": "V01",
                "start_seconds": 0,
                "end_seconds": 8,
                "spoken_text": "先看学生反应",
                "semantic_event_id": "E01",
                "srt_cue_ids": ["C01"],
                "new_primary_reason": "开头提出问题",
                "continuation_of": None,
                "audience_question": "为什么不能只看最低分",
                "audience_takeaway": "最低分会误导",
                "content_function": "hook",
                "visual_route": "image_to_video",
                "route_reason": "人物动作承接笑点",
                "requires_exact_text": False,
                "requires_exact_data": False,
                "entry": "学生翻开资料",
                "settle": "看见数字",
                "explain": "准备搜索攻略",
                "animation_beats": ["翻页", "抬头", "收回手"],
                "readable_hold_seconds": 0.8,
                "exit": "资料盖住屏幕",
                "transition_to_next": "资料成为数据图表",
                "screen_text": [],
                "evidence": [],
                "chart_plan": {"self_drawn": False, "source_footer_required": False, "source_footer_text": ""},
                "i2v_plan": {
                    "used": True,
                    "provider": "WAN",
                    "requested_seconds": 8,
                    "planned_coverage_seconds": 8,
                    "continuation_plan": "",
                    "approved_reference_frames": ["frame-01.png"],
                    "model_generates_core_readable_chinese": False,
                },
                "container_plan": {
                    "communicative_container_count": 0,
                    "blank_communicative_container_count": 0,
                    "all_text_uses_parent_local_coordinates": True,
                    "detached_overlay_text_count": 0,
                    "container_records": [],
                },
                "mobile_readability": {
                    "core_content_in_center_safe_area": True,
                    "caption_conflict_count": 0,
                    "viewer_can_read_before_exit": True,
                },
            },
            {
                "id": "V02",
                "start_seconds": 8,
                "end_seconds": 16,
                "spoken_text": "再看准确数据",
                "semantic_event_id": "E02",
                "srt_cue_ids": ["C02"],
                "new_primary_reason": "从情境转入数据证据",
                "continuation_of": None,
                "audience_question": "正常录取是多少",
                "audience_takeaway": "中位分比最低分更有用",
                "content_function": "data",
                "visual_route": "sourced_chart",
                "route_reason": "准确数据必须由本地图表解释",
                "requires_exact_text": True,
                "requires_exact_data": True,
                "entry": "真实名单进入",
                "settle": "最低分与中位分出现",
                "explain": "分数尺完成比较",
                "animation_beats": ["最低分放大", "中位线推进", "结论落稳"],
                "readable_hold_seconds": 1.2,
                "exit": "分数尺收进档案",
                "transition_to_next": "档案翻页",
                "screen_text": [{"text": "最低分264｜中位分387", "parent_component": "score-chart"}],
                "evidence": [evidence],
                "chart_plan": {
                    "self_drawn": True,
                    "source_footer_required": True,
                    "source_footer_text": "来源：示例大学2026拟录取名单",
                    "source_ids": ["SRC01"],
                },
                "i2v_plan": {
                    "used": False,
                    "provider": "",
                    "requested_seconds": 0,
                    "planned_coverage_seconds": 0,
                    "continuation_plan": "",
                    "approved_reference_frames": [],
                    "model_generates_core_readable_chinese": False,
                },
                "container_plan": {
                    "communicative_container_count": 1,
                    "blank_communicative_container_count": 0,
                    "all_text_uses_parent_local_coordinates": True,
                    "detached_overlay_text_count": 0,
                    "container_records": [{
                        "container_id": "V02-C01",
                        "content_text": "最低分264｜中位分387",
                        "parent_layer_id": "score-chart",
                        "coordinate_space": "parent_local",
                        "clip_to_container": True,
                        "moves_with_parent": True,
                        "visual_evidence_path": board.name,
                        "visual_evidence_sha256": digest(board),
                    }],
                },
                "mobile_readability": {
                    "core_content_in_center_safe_area": True,
                    "caption_conflict_count": 0,
                    "viewer_can_read_before_exit": True,
                },
            },
        ],
        "full_voiced_animatic": {
            "required": True,
            "path": animatic.name,
            "sha256": digest(animatic),
            "probe_report_path": animatic_probe.name,
            "probe_report_sha256": digest(animatic_probe),
            "has_video_stream": True,
            "has_audio_stream": True,
            "duration_seconds": 16,
            "uses_locked_narration": True,
            "uses_locked_caption_style": True,
            "covers_full_runtime": True,
            "missing_visual_segment_count": 0,
            "forced_slow_or_freeze_count": 0,
            "user_approved": True,
            "approval_quote": "动态分镜通过",
            "approved_at": "2026-09-02T11:00:00+08:00",
        },
        "music": {
            "required": True,
            "user_opted_out": False,
            "brief": {
                "theme_and_mood": "理性但有推进感",
                "energy_arc": "开头抓人，中段让位，结尾收稳",
                "instrumentation_and_texture": "轻打击与暖木质音色",
                "speech_role": "只托住口播",
                "no_vocals": True,
            },
            "newly_created_or_newly_licensed_for_project": True,
            "reused_from_previous_project": False,
            "provider_or_source": "Mureka",
            "canonical_track_id": "mureka-job-test-current",
            "generation_or_license_record": "Mureka generation job test-current",
            "generation_or_license_record_path": music_record.name,
            "generation_or_license_record_sha256": digest(music_record),
            "asset_path": music.name,
            "asset_sha256": digest(music),
            "previous_project_bgm_sha256": "B" * 64,
            "previous_project_canonical_track_id": "mureka-job-test-previous",
            "audio_fingerprint": "fingerprint-current-001",
            "audio_window_fingerprints": ["current-window"],
            "bgm_registry_path": bgm_registry.name,
            "bgm_registry_sha256": digest(bgm_registry),
            "registry_checked": True,
            "registry_match_count": 0,
            "user_approved_reuse_exception": False,
            "reuse_exception_quote": "",
            "reuse_exception_approved_at": "",
            "ducking_planned": True,
            "full_runtime_coverage_planned": True,
        },
        "approval": {
            "storyboard_user_approved": True,
            "storyboard_approval_quote": "故事板通过",
            "storyboard_approved_at": "2026-09-02T10:30:00+08:00",
            "brand_06_signoff": {
                "status": "pass",
                "department": "06｜品牌设计部",
                "signer_id": "brand-06",
                "signed_at": "2026-09-02T10:35:00+08:00",
                "reviewed_visual_storyboard_sha256": digest(board),
                "evidence_path": brand_review.name,
                "evidence_sha256": digest(brand_review),
            },
            "technical_07_signoff": {
                "status": "pass",
                "department": "07｜技术管家",
                "signer_id": "technical-07",
                "signed_at": "2026-09-02T10:36:00+08:00",
                "reviewed_visual_storyboard_sha256": digest(board),
                "evidence_path": technical_review.name,
                "evidence_sha256": digest(technical_review),
            },
            "batch_generation_allowed": True,
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = good_contract(root)
        path = root / "director-storyboard.json"
        path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        assert not validate_storyboard(good, path, "batch")
        wrong_animatic = root / "wrong-audio-animatic.mp4"
        unrelated_signoff = root / "unrelated-signoff.json"
        unrelated_signoff.write_text(json.dumps({"project_id": "other", "department": "06｜品牌设计部", "signer_id": "brand-06", "signed_at": "2026-09-02T10:35:00+08:00", "status": "pass", "reviewed_visual_storyboard_sha256": "A" * 64}), encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=10:d=16",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=16", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(wrong_animatic)
        ], check=True)

        cases = [
            ("fixed_shot_count", lambda d: d["planning_policy"].update(fixed_shot_count=60), "fixed_shot_count_forbidden"),
            ("fixed_chapter_count", lambda d: d["planning_policy"].update(fixed_chapter_count=8), "fixed_chapter_count_forbidden"),
            ("hidden_target_shot_count", lambda d: d.update(target_shot_count=60), "target_shot_count_forbidden"),
            ("nested_fixed_shot_count", lambda d: d.update(internal_execution_note={"fixed_shot_count": 60}), "fixed_shot_count_forbidden"),
            ("master_audio_missing", lambda d: d["audio_coverage"].update(master_audio_path="missing.wav"), "master_audio:file_missing"),
            ("master_audio_hash", lambda d: d["audio_coverage"].update(master_audio_sha256="A" * 64), "master_audio:hash_mismatch"),
            ("tolerance_widened", lambda d: d["audio_coverage"].update(tolerance_seconds=999), "tolerance_too_wide"),
            ("timeline_gap", lambda d: d["visual_segments"][1].update(start_seconds=9), "segment_2_gap"),
            ("timeline_overlap", lambda d: d["visual_segments"][1].update(start_seconds=7), "segment_2_overlap"),
            ("no_takeaway", lambda d: d["visual_segments"][0].update(audience_takeaway=""), "audience_takeaway_missing"),
            ("no_route", lambda d: d["visual_segments"][0].update(visual_route=""), "visual_route_invalid"),
            ("data_to_i2v", lambda d: d["visual_segments"][1].update(visual_route="image_to_video"), "exact_information_routed_to_i2v"),
            ("screen_text_hidden_in_i2v", lambda d: d["visual_segments"][0].update(screen_text=[{"text": "2026中位分387"}]), "readable_screen_text_in_pure_i2v"),
            ("hybrid_exact_data_sent_to_i2v", lambda d: d["visual_segments"][0].update(visual_route="hybrid", screen_text=[{"text": "2026中位分387"}], hybrid_plan={"used": True, "unique_primary_visual": True, "i2v_responsibility": "人物动作", "native_data_or_text_layer_id": "data-layer", "i2v_receives_exact_text_or_data": True, "auxiliary_layer_exit": "数据落稳后人物退出"}), "hybrid_exact_information_sent_to_i2v"),
            ("data_disguised_as_i2v", lambda d: d["visual_segments"][0].update(content_function="data"), "data_or_evidence_disguised_as_i2v"),
            ("official_no_source", lambda d: d["visual_segments"][1].update(evidence=[]), "evidence_missing"),
            ("official_no_snapshot", lambda d: d["visual_segments"][1]["evidence"][0].update(local_snapshot_path=""), "local_snapshot_missing"),
            ("chart_no_footer", lambda d: d["visual_segments"][1]["chart_plan"].update(source_footer_text=""), "chart_source_footer_missing"),
            ("chart_source_mismatch", lambda d: d["visual_segments"][1]["chart_plan"].update(source_ids=["SRC99"]), "chart_source_ids_do_not_match_evidence"),
            ("blank_card", lambda d: d["visual_segments"][1]["container_plan"].update(blank_communicative_container_count=1), "blank_communicative_container"),
            ("detached_text", lambda d: d["visual_segments"][1]["container_plan"].update(detached_overlay_text_count=1), "detached_overlay_text"),
            ("container_record_missing", lambda d: d["visual_segments"][1]["container_plan"].update(container_records=[]), "container_record_count_mismatch"),
            ("container_global_coordinates", lambda d: d["visual_segments"][1]["container_plan"]["container_records"][0].update(coordinate_space="frame_global"), "coordinate_space_not_parent_local"),
            ("container_irrelevant_visual_evidence", lambda d: d["visual_segments"][1]["container_plan"]["container_records"][0].update(visual_evidence_path="brief.md", visual_evidence_sha256=digest(root / "brief.md")), "unsupported_visual_evidence_type"),
            ("i2v_short", lambda d: d["visual_segments"][0]["i2v_plan"].update(planned_coverage_seconds=4), "i2v_shorter_than_spoken_segment_without_continuation"),
            ("i2v_over_10_even_with_continuation", lambda d: d["visual_segments"][0]["i2v_plan"].update(requested_seconds=14, continuation_plan="第二条连续镜头"), "single_i2v_request_exceeds_provider_limit"),
            ("no_animatic", lambda d: d["full_voiced_animatic"].update(user_approved=False), "animatic:user_approved_failed"),
            ("animatic_no_audio", lambda d: d["full_voiced_animatic"].update(has_audio_stream=False), "animatic:audio_stream_missing"),
            ("animatic_dummy_bytes", lambda d: d["full_voiced_animatic"].update(path="brand-review.json", sha256=digest(root / "brand-review.json")), "animatic:real_media_probe_failed"),
            ("animatic_wrong_narration", lambda d: d["full_voiced_animatic"].update(path=wrong_animatic.name, sha256=digest(wrong_animatic)), "animatic:locked_narration_audio_mismatch"),
            ("reuse_bgm", lambda d: d["music"].update(reused_from_previous_project=True), "music:previous_bgm_reused"),
            ("same_bgm_hash", lambda d: d["music"].update(previous_project_bgm_sha256=d["music"]["asset_sha256"]), "music:same_hash_as_previous_project"),
            ("same_bgm_track_id", lambda d: d["music"].update(previous_project_canonical_track_id=d["music"]["canonical_track_id"]), "music:same_track_id_as_previous_project"),
            ("bgm_registry_match", lambda d: d["music"].update(audio_fingerprint="older-fingerprint", registry_match_count=1), "music:registry_match_without_user_exception"),
            ("bgm_window_registry_match", lambda d: d["music"].update(audio_window_fingerprints=["older-window"], registry_match_count=1), "music:registry_match_without_user_exception"),
            ("no_music_source", lambda d: d["music"].update(provider_or_source=""), "music:source_missing"),
            ("bgm_registry_missing", lambda d: d["music"].update(bgm_registry_path="missing.json"), "music:registry:file_missing"),
            ("brand_not_pass", lambda d: d["approval"].update(brand_06_signoff="pending"), "approval:brand_06_not_pass"),
            ("technical_not_pass", lambda d: d["approval"].update(technical_07_signoff="pending"), "approval:technical_07_not_pass"),
            ("brand_board_hash_mismatch", lambda d: d["approval"]["brand_06_signoff"].update(reviewed_visual_storyboard_sha256="A" * 64), "brand_06_board_hash_mismatch"),
            ("same_signer", lambda d: d["approval"]["technical_07_signoff"].update(signer_id=d["approval"]["brand_06_signoff"]["signer_id"]), "independent_dual_signoff_required"),
            ("unrelated_signoff_evidence", lambda d: d["approval"]["brand_06_signoff"].update(evidence_path=unrelated_signoff.name, evidence_sha256=digest(unrelated_signoff)), "brand_06_evidence_project_mismatch"),
            ("forced_freeze", lambda d: d["full_voiced_animatic"].update(forced_slow_or_freeze_count=1), "animatic:forced_slow_or_freeze"),
        ]
        for name, mutate, expected in cases:
            candidate = copy.deepcopy(good)
            mutate(candidate)
            errors = validate_storyboard(candidate, path, "batch")
            assert any(expected in error for error in errors), (name, expected, errors)
        trusted_errors = validate_storyboard(good, path, "batch", root / "different-global-registry.json")
        assert any("untrusted_or_truncated_registry_path" in error for error in trusted_errors)
        print(f"DIRECTOR STORYBOARD NEGATIVE TESTS PASS {len(cases)}/{len(cases)}")


if __name__ == "__main__":
    main()
