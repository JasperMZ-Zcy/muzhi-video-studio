#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from validate_production_enforcement import validate_manifest
from test_director_storyboard import good_contract as good_storyboard_contract


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def make_video(path: Path, seconds: int = 1) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"testsrc2=size=64x64:rate=10:duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast", str(path)
    ], check=True)


def base_manifest(root: Path) -> dict:
    evidence = root / "evidence.txt"
    evidence.write_text("verified", encoding="utf-8")
    item = {"path": "evidence.txt", "sha256": digest(evidence)}
    storyboard = good_storyboard_contract(root)
    storyboard_path = root / "director-storyboard.json"
    storyboard_path.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
    pilot_file = root / "animatic.mp4"
    motion_pilot_contract = {
        "schema_version": "1.1",
        "project_id": "test",
        "project_root": str(root),
        "title": "test",
        "status": "approved",
        "golden_baseline": {"asset_id": "baseline", "reference_path": "reference", "source_master_sha256": "A" * 64, "ninety_percent_locked": True, "maximum_upgrade_percent": 10},
        "upstream_gates": {
            "director_interpretation_user_approved": True,
            "visual_storyboard_user_approved": True,
            "full_voiced_animatic_user_approved": True,
            "director_storyboard_contract_path": storyboard_path.name,
            "director_storyboard_contract_sha256": digest(storyboard_path),
            "new_project_bgm_path": "music.wav",
            "new_project_bgm_sha256": digest(root / "music.wav"),
            "previous_project_bgm_sha256": "B" * 64,
            "brand_06_signoff": "pass",
            "technical_07_signoff": "pass",
        },
        "pilot": {
            "path": pilot_file.name,
            "sha256": digest(pilot_file),
            "duration_seconds": 16,
            "hardest_representative_section": True,
            "real_narration": True,
            "final_caption_style": True,
            "flow_or_equivalent_organic_action": True,
            "local_semantic_animation": True,
            "data_or_evidence_scene": True,
            "object_based_handoff": True,
            "actual_voice_processing_sample": True,
            "actual_music_sample": True,
        },
        "preapproval_budget": {"image_generation_calls_used": 8, "image_generation_call_cap": 10, "flow_tests_used": 1, "flow_test_cap": 2},
        "forbidden_before_approval": {"batch_asset_generation_started": False, "full_flow_batch_started": False, "full_formal_production_timeline_created": False, "full_audio_processing_started": False, "final_master_render_started": False},
        "aesthetic_vetoes": {"ppt_like": False, "cheap_ai_like": False, "style_inconsistent": False, "stiff_animation": False},
        "human_review": {"approved_by": "品牌", "approval_quote": "样片通过", "approved_at": "2026-09-02T11:30:00+08:00"},
        "batch_release_allowed": True,
    }
    motion_pilot_contract_path = root / "motion-pilot-contract.json"
    motion_pilot_contract_path.write_text(json.dumps(motion_pilot_contract, ensure_ascii=False), encoding="utf-8")
    duration_media = root / "duration-motion.mp4"
    make_video(duration_media)
    duration_audit_path = root / "dynamic-duration.json"
    duration_audit_path.write_text(json.dumps({
        "schema_version": "1.0",
        "project_id": "test",
        "project_root": str(root),
        "ffprobe_required": True,
        "actual_record_count": 1,
        "records": [{
            "visual_segment_id": "V01",
            "spoken_start_seconds": 0,
            "spoken_end_seconds": 1,
            "required_coverage_seconds": 1,
            "asset_path": duration_media.name,
            "asset_sha256": digest(duration_media),
            "declared_source_duration_seconds": 1,
            "timeline_used_seconds": 1,
            "timeline_start_seconds": 0,
            "timeline_end_seconds": 1,
            "timeline_start_seconds": 0,
            "timeline_end_seconds": 1,
            "maximum_continuous_i2v_seconds": 10,
            "over_limit_exception_approved": False,
            "over_limit_exception_quote": "",
            "playback_speed": 1.0,
            "intentional_retiming_approved": False,
            "intentional_retiming_approval_reason": "",
            "continuation_segments": [],
            "forced_freeze_seconds": 0,
            "meaningless_loop_count": 0,
            "intentional_motion_loop_approved": False,
            "intentional_motion_loop_approval_quote": "",
            "intentional_motion_loop_approved_at": "",
            "static_flash_padding_count": 0,
            "maximum_allowed_unexplained_freeze_seconds": 0.8,
            "intentional_freeze_approved": False,
            "intentional_freeze_approval_reason": "",
            "director_storyboard_route": "image_to_video",
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
    }), encoding="utf-8")
    return {
        "schema_version": "3.0", "mode": "production", "project_id": "test",
        "rule_layers": {
            "immutable_core": ["master_clock", "gate2_stop", "semantic_motion", "layer_exit", "caption_readability", "speech_first_bgm", "evidence_qa", "separate_publish_authorization", "golden_baseline", "director_storyboard", "semantic_visual_routing", "full_voiced_animatic", "new_bgm_per_project", "source_attribution", "same_day_delivery_target", "dynamic_asset_duration_gate", "motion_pilot", "complete_rough_cut", "aesthetic_fail_fast"],
            "project_style": [], "additive_requirements": [], "revision_scope": [],
            "core_rules_cannot_be_weakened": True, "conflicts": []},
        "gate2": {"approved": True, "approval_quote": "整套通过", "approved_at": "2026-08-15T12:00:00+08:00", "render_started_after_approval": True, "evidence": [item]},
        "director_storyboard": {
            "required": True,
            "contract_path": storyboard_path.name,
            "contract_sha256": digest(storyboard_path),
            "plan_gate_passed": True,
            "batch_gate_passed": True,
            "director_interpretation_user_approved": True,
            "visual_storyboard_user_approved": True,
            "full_voiced_animatic_user_approved": True,
            "no_fixed_chapter_or_shot_count": True,
            "full_audio_coverage": True,
            "brand_06_signoff": "pass",
            "technical_07_signoff": "pass",
            "evidence": [item],
        },
        "creative_direction": {"golden_baseline_id": "editorial-golden-test", "golden_baseline_sha256": "A" * 64, "inheritance_target_percent": 90, "topic_specific_upgrade_cap_percent": 10, "single_director": True, "single_timeline_owner": True, "maximum_active_roles": 3, "parallel_visual_directions": 0, "evidence": [item]},
        "motion_pilot": {"required": True, "contract_path": motion_pilot_contract_path.name, "contract_sha256": digest(motion_pilot_contract_path), "contract_validator_passed": True, "duration_seconds": 16, "uses_real_voice": True, "uses_locked_captions": True, "uses_real_assets": True, "uses_real_motion": True, "uses_real_audio_relationship": True, "image_generation_call_cap": 10, "image_generation_calls_used": 8, "flow_test_call_cap": 2, "flow_test_calls_used": 1, "user_approved": True, "batch_production_started_after_approval": True, "evidence": [item]},
        "aesthetic_fail_fast": {"looks_like_ppt": False, "looks_like_cheap_ai": False, "style_inconsistent": False, "motion_stiff": False, "directional_failure_count": 0, "direction_stopped_after_two_same_failures": False, "human_review_evidence": [item]},
        "dynamic_asset_duration_audit": {"required": True, "validator_passed": True, "manifest_path": duration_audit_path.name, "manifest_sha256": digest(duration_audit_path), "all_media_probed": True, "shortfall_without_continuation_count": 0, "forced_slow_freeze_loop_or_static_flash_count": 0, "content_mismatch_count": 0, "evidence": [item]},
        "complete_rough_cut": {"required": True, "start_to_end_complete": True, "uses_real_timeline": True, "user_approved": True, "final_render_started_after_approval": True, "evidence": [item]},
        "shots": [{
            "id": "S01",
            "semantic": {"subject": "考生", "action": "比较", "object": "项目", "turn": "校名相同规则不同", "result": "按项目判断", "audience_takeaway": "不是问学校好不好考"},
            "timing": {"sceneStart": 0, "keywordCue": 0.5, "actionCue": 0.5, "textCue": 0.6, "resultCue": 1.6, "exitCue": 2.5},
            "lifecycle": {"enter": "slide", "settle": "hold", "act_or_receive": "compare", "yield": "dim", "resolve": "focus", "exit": "wipe"},
            "layers": {"previous_exited_before_next_main": True, "lingering_layer_count": 0},
            "visual": {"giant_ordinal_only": False, "persistent_top_title": False},
            "text": {"caption": "别只问哪所学校好考", "highlight": "哪所学校好考", "highlight_mode": "semantic_keyword", "explanation_required": True, "explanation": "判断单位是具体项目", "explanation_repeats_caption": False, "form": "comparison"},
            "layout": {"main_visual_fill_ratio": 0.75, "caption_main_visual_gap_px": 240, "overlap_count": 0, "main_visual_bbox": [100, 400, 900, 1200], "explanation_bbox": [120, 280, 880, 400], "caption_bbox": [100, 1300, 980, 1480]},
            "evidence": [item]}],
        "global_visual": {"single_card_form_only": False, "persistent_top_title": False, "flow_change_count": 0, "caption_main_visual_max_gap_px": 240, "overlap_count": 0, "exact_information_routed_to_pure_i2v_count": 0, "official_source_missing_count": 0, "sourced_chart_footer_missing_count": 0, "i2v_duration_shortfall_without_continuation_count": 0, "forced_slow_freeze_loop_or_static_flash_count": 0, "official_evidence_not_design_integrated_count": 0, "empty_background_text_only_count": 0, "evidence": [item]},
        "audio": {"voice_duration_drift_ms": 0, "voice_integrated_lufs": -16, "bgm_integrated_lufs": -34.5, "bgm_normal_lufs": -33.5, "bgm_dense_lufs": -35.1, "bgm_cta_lufs": -38.2, "voice_bgm_margin_db": 18.5, "final_integrated_lufs": -16, "music_brief": "理性、轻快、无歌词并让位口播", "bgm_provider_or_license_source": "Mureka", "bgm_canonical_track_id": storyboard["music"]["canonical_track_id"], "bgm_generation_or_license_record": "Mureka generation job mureka-current", "new_bgm_for_this_project": True, "bgm_reused_from_previous_project": False, "bgm_original_path": "music.wav", "bgm_original_sha256": storyboard["music"]["asset_sha256"], "bgm_audio_fingerprint": storyboard["music"]["audio_fingerprint"], "bgm_audio_window_fingerprints": storyboard["music"]["audio_window_fingerprints"], "bgm_registry_path": storyboard["music"]["bgm_registry_path"], "bgm_registry_sha256": storyboard["music"]["bgm_registry_sha256"], "bgm_registry_match_count": 0, "previous_project_bgm_sha256": "B" * 64, "previous_project_bgm_canonical_track_id": "mureka-previous", "voice_path": "voice.wav", "bgm_ducked_path": "bgm.wav", "final_mix_path": "mix.wav", "evidence": [item]},
        "qa": {"full_decode_zero_errors": True, "continuous_ranges_reviewed": True, "full_watch_completed": True, "desktop_hash_match": True, "evidence": [item]},
        "publication": {"authorized": False, "performed": False}}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = base_manifest(root)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        assert not validate_manifest(good, manifest)
        fake_duration = root / "fake-duration.json"
        fake_duration.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
        cases = [
            ("old_schema", lambda d: d.update(schema_version="1.2"), "old_schema_rejected"),
            ("no_storyboard", lambda d: d["director_storyboard"].update(batch_gate_passed=False), "batch_gate_passed_failed"),
            ("storyboard_fixed_count", lambda d: d["director_storyboard"].update(no_fixed_chapter_or_shot_count=False), "no_fixed_chapter_or_shot_count_failed"),
            ("brand_not_signed", lambda d: d["director_storyboard"].update(brand_06_signoff="pending"), "brand_06_not_pass"),
            ("no_exit", lambda d: d["shots"][0]["lifecycle"].update(exit=""), "lifecycle_exit_missing"),
            ("lingering", lambda d: d["shots"][0]["layers"].update(lingering_layer_count=1), "lingering_layer"),
            ("giant_ordinal", lambda d: d["shots"][0]["visual"].update(giant_ordinal_only=True), "giant_ordinal"),
            ("top_title", lambda d: d["global_visual"].update(persistent_top_title=True), "persistent_top_title"),
            ("missing_explanation", lambda d: d["shots"][0]["text"].update(explanation=""), "required_explanation_missing"),
            ("duplicate_explanation", lambda d: d["shots"][0]["text"].update(explanation_repeats_caption=True), "explanation_repeats_caption"),
            ("single_card", lambda d: d["global_visual"].update(single_card_form_only=True), "single_card_form"),
            ("exact_data_to_i2v", lambda d: d["global_visual"].update(exact_information_routed_to_pure_i2v_count=1), "exact_information_routed_to_pure_i2v"),
            ("source_missing", lambda d: d["global_visual"].update(official_source_missing_count=1), "official_source_missing"),
            ("chart_footer_missing", lambda d: d["global_visual"].update(sourced_chart_footer_missing_count=1), "sourced_chart_footer_missing"),
            ("i2v_shortfall", lambda d: d["global_visual"].update(i2v_duration_shortfall_without_continuation_count=1), "i2v_duration_shortfall"),
            ("forced_padding", lambda d: d["global_visual"].update(forced_slow_freeze_loop_or_static_flash_count=1), "forced_padding"),
            ("official_evidence_two_worlds", lambda d: d["global_visual"].update(official_evidence_not_design_integrated_count=1), "official_evidence_not_design_integrated"),
            ("empty_text_page", lambda d: d["global_visual"].update(empty_background_text_only_count=1), "empty_background_text_only"),
            ("small_visual", lambda d: d["shots"][0]["layout"].update(main_visual_fill_ratio=0.3), "main_visual_too_small"),
            ("caption_far", lambda d: d["shots"][0]["layout"].update(caption_main_visual_gap_px=600), "caption_too_far"),
            ("overlap", lambda d: d["shots"][0]["layout"].update(overlap_count=1), "overlap"),
            ("early_action", lambda d: d["shots"][0]["timing"].update(actionCue=0.1), "early_action"),
            ("flow_change", lambda d: d["global_visual"].update(flow_change_count=1), "flow_changed"),
            ("voice_drift", lambda d: d["audio"].update(voice_duration_drift_ms=25), "voice_duration_drift"),
            ("bgm_inaudible", lambda d: d["audio"].update(bgm_integrated_lufs=-50), "bgm_inaudible_or_too_loud"),
            ("segment_bgm_fail", lambda d: d["audio"].update(bgm_dense_lufs=-50), "bgm_dense_lufs_failed"),
            ("reused_bgm", lambda d: d["audio"].update(bgm_reused_from_previous_project=True), "previous_bgm_reused"),
            ("same_bgm_hash", lambda d: d["audio"].update(previous_project_bgm_sha256=d["audio"]["bgm_original_sha256"]), "same_bgm_as_previous_project"),
            ("same_bgm_track_id", lambda d: d["audio"].update(previous_project_bgm_canonical_track_id=d["audio"]["bgm_canonical_track_id"]), "same_bgm_track_id_as_previous_project"),
            ("gate2_missing", lambda d: d["gate2"].update(approved=False), "gate2:not_approved"),
            ("pilot_too_short", lambda d: d["motion_pilot"].update(duration_seconds=8), "pilot:duration_out_of_range"),
            ("pilot_contract_missing", lambda d: d["motion_pilot"].update(contract_path=""), "pilot:contract_path_missing"),
            ("pilot_not_real", lambda d: d["motion_pilot"].update(uses_real_motion=False), "pilot:uses_real_motion_failed"),
            ("image_budget", lambda d: d["motion_pilot"].update(image_generation_calls_used=11), "pilot:image_budget_exceeded"),
            ("ppt_veto", lambda d: d["aesthetic_fail_fast"].update(looks_like_ppt=True), "aesthetic:looks_like_ppt"),
            ("duration_shortfall", lambda d: d["dynamic_asset_duration_audit"].update(shortfall_without_continuation_count=1), "duration_audit:shortfall"),
            ("duration_not_probed", lambda d: d["dynamic_asset_duration_audit"].update(all_media_probed=False), "duration_audit:media_not_probed"),
            ("fake_duration_manifest", lambda d: d["dynamic_asset_duration_audit"].update(manifest_path=fake_duration.name, manifest_sha256=digest(fake_duration)), "duration_audit_contract:manifest:invalid_schema"),
            ("no_rough_cut", lambda d: d["complete_rough_cut"].update(user_approved=False), "rough_cut:user_approved_failed"),
            ("unauthorized_publish", lambda d: d["publication"].update(performed=True), "unauthorized_publish"),
        ]
        for name, mutate, expected in cases:
            candidate = copy.deepcopy(good)
            mutate(candidate)
            errors = validate_manifest(candidate, manifest)
            assert any(expected in error for error in errors), (name, errors)
        print(f"NEGATIVE TESTS PASS {len(cases)}/{len(cases)}")


if __name__ == "__main__":
    main()
