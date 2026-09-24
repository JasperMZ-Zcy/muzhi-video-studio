#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from validate_director_storyboard import trusted_bgm_registry_from_local_config, validate_storyboard
from validate_dynamic_asset_duration import validate as validate_dynamic_asset_duration
from validate_motion_pilot import validate as validate_motion_pilot_contract


CORE_RULES = {
    "master_clock", "gate2_stop", "semantic_motion", "layer_exit",
    "caption_readability", "speech_first_bgm", "evidence_qa",
    "separate_publish_authorization", "golden_baseline", "motion_pilot",
    "complete_rough_cut", "aesthetic_fail_fast",
    "director_storyboard", "semantic_visual_routing", "full_voiced_animatic",
    "new_bgm_per_project", "source_attribution", "same_day_delivery_target",
    "dynamic_asset_duration_gate",
}
SEMANTIC_FIELDS = ("subject", "action", "object", "turn", "result", "audience_takeaway")
TIMING_FIELDS = ("sceneStart", "actionCue", "textCue", "resultCue", "exitCue")
LIFECYCLE_FIELDS = ("enter", "settle", "act_or_receive", "yield", "resolve", "exit")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def require(condition: bool, code: str, errors: list[str]) -> None:
    if not condition:
        errors.append(code)


def text_tokens(value: str) -> set[str]:
    return {token for token in value.replace("，", " ").replace("。", " ").split() if token}


def validate_evidence(items: object, base: Path, scope: str, errors: list[str]) -> None:
    require(isinstance(items, list) and len(items) > 0, f"{scope}:missing_evidence", errors)
    if not isinstance(items, list):
        return
    for index, item in enumerate(items):
        tag = f"{scope}:evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{tag}:not_object")
            continue
        rel = item.get("path")
        digest = str(item.get("sha256", "")).upper()
        require(bool(rel), f"{tag}:missing_path", errors)
        require(len(digest) == 64, f"{tag}:missing_sha256", errors)
        if not rel:
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = base / path
        require(path.is_file(), f"{tag}:file_missing", errors)
        if path.is_file() and len(digest) == 64:
            require(sha256(path) == digest, f"{tag}:hash_mismatch", errors)


def validate_director_contract(section: dict, base: Path, errors: list[str]) -> dict:
    require(section.get("required") is True, "director_storyboard:not_required", errors)
    rel = section.get("contract_path")
    digest = str(section.get("contract_sha256", "")).upper()
    require(bool(rel), "director_storyboard:path_missing", errors)
    require(len(digest) == 64, "director_storyboard:sha256_missing", errors)
    if not rel:
        return {}
    path = Path(rel)
    if not path.is_absolute():
        path = base / path
    require(path.is_file(), "director_storyboard:file_missing", errors)
    if not path.is_file():
        return {}
    if len(digest) == 64:
        require(sha256(path) == digest, "director_storyboard:hash_mismatch", errors)
    try:
        contract = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        errors.append("director_storyboard:invalid_json")
        return {}
    for error in validate_storyboard(contract, path, "batch", trusted_bgm_registry_from_local_config(contract)):
        errors.append(f"director_storyboard_contract:{error}")
    return contract


def validate_shot(shot: dict, base: Path, errors: list[str]) -> None:
    sid = str(shot.get("id", "unknown"))
    prefix = f"shot:{sid}"
    semantic = shot.get("semantic", {})
    for field in SEMANTIC_FIELDS:
        require(bool(str(semantic.get(field, "")).strip()), f"{prefix}:semantic_{field}_missing", errors)

    timing = shot.get("timing", {})
    for field in TIMING_FIELDS:
        require(isinstance(timing.get(field), (int, float)), f"{prefix}:timing_{field}_missing", errors)
    if all(isinstance(timing.get(field), (int, float)) for field in TIMING_FIELDS):
        require(timing["sceneStart"] <= timing["actionCue"] <= timing["resultCue"] <= timing["exitCue"],
                f"{prefix}:early_action_or_invalid_order", errors)
        require(timing["textCue"] >= timing["sceneStart"], f"{prefix}:text_before_scene", errors)
        require(timing["actionCue"] >= timing.get("keywordCue", timing["actionCue"]) - 0.18,
                f"{prefix}:early_action", errors)

    lifecycle = shot.get("lifecycle", {})
    for field in LIFECYCLE_FIELDS:
        require(bool(lifecycle.get(field)), f"{prefix}:lifecycle_{field}_missing", errors)

    layers = shot.get("layers", {})
    require(layers.get("previous_exited_before_next_main") is True, f"{prefix}:previous_layer_not_exited", errors)
    require(layers.get("lingering_layer_count") == 0, f"{prefix}:lingering_layer", errors)

    visual = shot.get("visual", {})
    require(not visual.get("giant_ordinal_only", False), f"{prefix}:giant_ordinal", errors)
    require(not visual.get("persistent_top_title", False), f"{prefix}:persistent_top_title", errors)

    text = shot.get("text", {})
    if text.get("explanation_required", False):
        require(bool(str(text.get("explanation", "")).strip()), f"{prefix}:required_explanation_missing", errors)
    caption = str(text.get("caption", "")).strip()
    explanation = str(text.get("explanation", "")).strip()
    require(not text.get("explanation_repeats_caption", False), f"{prefix}:explanation_repeats_caption", errors)
    if caption and explanation:
        c, e = text_tokens(caption), text_tokens(explanation)
        if c and e:
            require(len(c & e) / max(1, len(e)) < 0.8, f"{prefix}:explanation_probably_duplicates_caption", errors)
    highlight_mode = text.get("highlight_mode")
    require(highlight_mode in {"semantic_keyword", "karaoke_character", "none"}, f"{prefix}:invalid_highlight_mode", errors)

    layout = shot.get("layout", {})
    require(float(layout.get("main_visual_fill_ratio", 0)) >= 0.60, f"{prefix}:main_visual_too_small", errors)
    require(float(layout.get("caption_main_visual_gap_px", 9999)) <= 390, f"{prefix}:caption_too_far", errors)
    require(int(layout.get("overlap_count", 1)) == 0, f"{prefix}:overlap", errors)
    for box in ("main_visual_bbox", "explanation_bbox", "caption_bbox"):
        require(isinstance(layout.get(box), list) and len(layout.get(box, [])) == 4,
                f"{prefix}:{box}_missing", errors)
    validate_evidence(shot.get("evidence"), base, prefix, errors)


def validate_manifest(data: dict, manifest_path: Path) -> list[str]:
    errors: list[str] = []
    base = manifest_path.parent
    try:
        schema = float(data.get("schema_version", 0))
    except (TypeError, ValueError):
        schema = 0
    require(schema >= 3.0, "manifest:old_schema_rejected", errors)
    require(data.get("mode") == "production", "manifest:not_production_mode", errors)

    rules = data.get("rule_layers", {})
    require(set(rules.get("immutable_core", [])) >= CORE_RULES, "rules:immutable_core_incomplete", errors)
    require(rules.get("core_rules_cannot_be_weakened") is True, "rules:core_can_be_weakened", errors)
    require(rules.get("conflicts") == [], "rules:unresolved_conflicts", errors)

    gate2 = data.get("gate2", {})
    require(gate2.get("approved") is True, "gate2:not_approved", errors)
    require(bool(str(gate2.get("approval_quote", "")).strip()), "gate2:missing_approval_quote", errors)
    require(bool(str(gate2.get("approved_at", "")).strip()), "gate2:missing_approval_time", errors)
    require(gate2.get("render_started_after_approval") is True, "gate2:render_before_approval", errors)
    validate_evidence(gate2.get("evidence"), base, "gate2", errors)

    director_storyboard = data.get("director_storyboard", {})
    director_contract = validate_director_contract(director_storyboard, base, errors)
    for field in ("plan_gate_passed", "batch_gate_passed", "director_interpretation_user_approved",
                  "visual_storyboard_user_approved", "full_voiced_animatic_user_approved",
                  "no_fixed_chapter_or_shot_count", "full_audio_coverage"):
        require(director_storyboard.get(field) is True, f"director_storyboard:{field}_failed", errors)
    require(director_storyboard.get("brand_06_signoff") == "pass",
            "director_storyboard:brand_06_not_pass", errors)
    require(director_storyboard.get("technical_07_signoff") == "pass",
            "director_storyboard:technical_07_not_pass", errors)
    validate_evidence(director_storyboard.get("evidence"), base, "director_storyboard", errors)

    creative = data.get("creative_direction", {})
    require(bool(str(creative.get("golden_baseline_id", "")).strip()),
            "creative:golden_baseline_missing", errors)
    require(len(str(creative.get("golden_baseline_sha256", ""))) == 64,
            "creative:golden_baseline_hash_missing", errors)
    require(float(creative.get("inheritance_target_percent", 0)) >= 90,
            "creative:baseline_inheritance_below_90", errors)
    require(float(creative.get("topic_specific_upgrade_cap_percent", 100)) <= 10,
            "creative:topic_upgrade_above_10", errors)
    require(creative.get("single_director") is True, "creative:multiple_directors", errors)
    require(creative.get("single_timeline_owner") is True, "creative:multiple_timeline_owners", errors)
    require(int(creative.get("maximum_active_roles", 99)) <= 3, "creative:too_many_roles", errors)
    require(int(creative.get("parallel_visual_directions", 99)) == 0,
            "creative:parallel_visual_directions", errors)
    validate_evidence(creative.get("evidence"), base, "creative_direction", errors)

    pilot = data.get("motion_pilot", {})
    require(pilot.get("required") is True, "pilot:not_required", errors)
    require(pilot.get("contract_validator_passed") is True, "pilot:contract_validator_not_passed", errors)
    pilot_contract_path_value = pilot.get("contract_path")
    pilot_contract_hash = str(pilot.get("contract_sha256", "")).upper()
    require(bool(pilot_contract_path_value), "pilot:contract_path_missing", errors)
    require(len(pilot_contract_hash) == 64, "pilot:contract_sha256_missing", errors)
    if pilot_contract_path_value:
        pilot_contract_path = Path(pilot_contract_path_value)
        if not pilot_contract_path.is_absolute():
            pilot_contract_path = base / pilot_contract_path
        require(pilot_contract_path.is_file(), "pilot:contract_file_missing", errors)
        if pilot_contract_path.is_file() and len(pilot_contract_hash) == 64:
            require(sha256(pilot_contract_path) == pilot_contract_hash, "pilot:contract_hash_mismatch", errors)
        if pilot_contract_path.is_file():
            try:
                pilot_contract = json.loads(pilot_contract_path.read_text(encoding="utf-8-sig"))
                for error in validate_motion_pilot_contract(pilot_contract, pilot_contract_path, True):
                    errors.append(f"pilot_contract:{error}")
                require(pilot_contract.get("project_id") == data.get("project_id"),
                        "pilot_contract:project_id_mismatch", errors)
            except (OSError, json.JSONDecodeError):
                errors.append("pilot:contract_invalid_json")
    duration = float(pilot.get("duration_seconds", 0))
    require(15 <= duration <= 20, "pilot:duration_out_of_range", errors)
    for field in ("uses_real_voice", "uses_locked_captions", "uses_real_assets",
                  "uses_real_motion", "uses_real_audio_relationship", "user_approved"):
        require(pilot.get(field) is True, f"pilot:{field}_failed", errors)
    require(int(pilot.get("image_generation_calls_used", 999)) <=
            int(pilot.get("image_generation_call_cap", 10)), "pilot:image_budget_exceeded", errors)
    require(int(pilot.get("flow_test_calls_used", 999)) <=
            int(pilot.get("flow_test_call_cap", 2)), "pilot:flow_budget_exceeded", errors)
    require(pilot.get("batch_production_started_after_approval") is True,
            "pilot:batch_started_before_approval", errors)
    validate_evidence(pilot.get("evidence"), base, "motion_pilot", errors)

    aesthetic = data.get("aesthetic_fail_fast", {})
    for field in ("looks_like_ppt", "looks_like_cheap_ai", "style_inconsistent", "motion_stiff"):
        require(aesthetic.get(field) is False, f"aesthetic:{field}", errors)
    failures = int(aesthetic.get("directional_failure_count", 0))
    if failures >= 2:
        require(aesthetic.get("direction_stopped_after_two_same_failures") is True,
                "aesthetic:failed_direction_not_stopped", errors)
    validate_evidence(aesthetic.get("human_review_evidence"), base, "aesthetic_fail_fast", errors)

    duration_audit = data.get("dynamic_asset_duration_audit", {})
    require(duration_audit.get("required") is True, "duration_audit:not_required", errors)
    require(duration_audit.get("validator_passed") is True, "duration_audit:validator_not_passed", errors)
    require(duration_audit.get("all_media_probed") is True, "duration_audit:media_not_probed", errors)
    require(int(duration_audit.get("shortfall_without_continuation_count", 1)) == 0,
            "duration_audit:shortfall", errors)
    require(int(duration_audit.get("forced_slow_freeze_loop_or_static_flash_count", 1)) == 0,
            "duration_audit:forced_padding", errors)
    require(int(duration_audit.get("content_mismatch_count", 1)) == 0,
            "duration_audit:content_mismatch", errors)
    audit_path = duration_audit.get("manifest_path")
    audit_hash = str(duration_audit.get("manifest_sha256", "")).upper()
    require(bool(audit_path), "duration_audit:manifest_path_missing", errors)
    require(len(audit_hash) == 64, "duration_audit:manifest_sha256_missing", errors)
    if audit_path:
        resolved_audit = Path(audit_path)
        if not resolved_audit.is_absolute():
            resolved_audit = base / resolved_audit
        require(resolved_audit.is_file(), "duration_audit:manifest_file_missing", errors)
        if resolved_audit.is_file() and len(audit_hash) == 64:
            require(sha256(resolved_audit) == audit_hash, "duration_audit:manifest_hash_mismatch", errors)
        if resolved_audit.is_file():
            try:
                duration_data = json.loads(resolved_audit.read_text(encoding="utf-8-sig"))
                for error in validate_dynamic_asset_duration(duration_data, resolved_audit, verify_media=True):
                    errors.append(f"duration_audit_contract:{error}")
            except (OSError, json.JSONDecodeError):
                errors.append("duration_audit:manifest_invalid_json")
    validate_evidence(duration_audit.get("evidence"), base, "dynamic_asset_duration_audit", errors)

    rough_cut = data.get("complete_rough_cut", {})
    for field in ("required", "start_to_end_complete", "uses_real_timeline", "user_approved",
                  "final_render_started_after_approval"):
        require(rough_cut.get(field) is True, f"rough_cut:{field}_failed", errors)
    validate_evidence(rough_cut.get("evidence"), base, "complete_rough_cut", errors)

    shots = data.get("shots")
    require(isinstance(shots, list) and len(shots) > 0, "shots:empty", errors)
    if isinstance(shots, list):
        for shot in shots:
            if isinstance(shot, dict):
                validate_shot(shot, base, errors)
            else:
                errors.append("shots:not_object")

    global_visual = data.get("global_visual", {})
    require(not global_visual.get("single_card_form_only", False), "visual:single_card_form", errors)
    require(not global_visual.get("persistent_top_title", False), "visual:persistent_top_title", errors)
    require(global_visual.get("flow_change_count") == 0, "visual:flow_changed", errors)
    require(global_visual.get("overlap_count") == 0, "visual:overlap", errors)
    require(int(global_visual.get("exact_information_routed_to_pure_i2v_count", 1)) == 0,
            "visual:exact_information_routed_to_pure_i2v", errors)
    require(int(global_visual.get("official_source_missing_count", 1)) == 0,
            "visual:official_source_missing", errors)
    require(int(global_visual.get("sourced_chart_footer_missing_count", 1)) == 0,
            "visual:sourced_chart_footer_missing", errors)
    require(int(global_visual.get("i2v_duration_shortfall_without_continuation_count", 1)) == 0,
            "visual:i2v_duration_shortfall", errors)
    require(int(global_visual.get("forced_slow_freeze_loop_or_static_flash_count", 1)) == 0,
            "visual:forced_padding", errors)
    require(int(global_visual.get("official_evidence_not_design_integrated_count", 1)) == 0,
            "visual:official_evidence_not_design_integrated", errors)
    require(int(global_visual.get("empty_background_text_only_count", 1)) == 0,
            "visual:empty_background_text_only", errors)
    require(float(global_visual.get("caption_main_visual_max_gap_px", 9999)) <= 390, "visual:caption_too_far", errors)
    validate_evidence(global_visual.get("evidence"), base, "global_visual", errors)

    audio = data.get("audio", {})
    require(abs(float(audio.get("voice_duration_drift_ms", 9999))) <= 1.0, "audio:voice_duration_drift", errors)
    bgm = float(audio.get("bgm_integrated_lufs", -999))
    margin = float(audio.get("voice_bgm_margin_db", 999))
    require(-36 <= bgm <= -30, "audio:bgm_inaudible_or_too_loud", errors)
    require(14 <= margin <= 22, "audio:voice_bgm_margin_out_of_range", errors)
    for field in ("bgm_normal_lufs", "bgm_dense_lufs", "bgm_cta_lufs"):
        value = float(audio.get(field, -999))
        require(-42 <= value <= -28, f"audio:{field}_failed", errors)
    require(-18 <= float(audio.get("final_integrated_lufs", -999)) <= -14,
            "audio:final_loudness_failed", errors)
    require(bool(str(audio.get("music_brief", "")).strip()), "audio:music_brief_missing", errors)
    require(bool(str(audio.get("bgm_provider_or_license_source", "")).strip()),
            "audio:bgm_source_missing", errors)
    require(bool(str(audio.get("bgm_canonical_track_id", "")).strip()),
            "audio:bgm_canonical_track_id_missing", errors)
    require(bool(str(audio.get("bgm_generation_or_license_record", "")).strip()),
            "audio:bgm_generation_or_license_record_missing", errors)
    require(audio.get("new_bgm_for_this_project") is True, "audio:bgm_not_new_for_project", errors)
    require(audio.get("bgm_reused_from_previous_project") is False,
            "audio:previous_bgm_reused", errors)
    require(bool(str(audio.get("bgm_original_path", "")).strip()), "audio:bgm_original_path_missing", errors)
    current_bgm_hash = str(audio.get("bgm_original_sha256", "")).strip().upper()
    previous_bgm_hash = str(audio.get("previous_project_bgm_sha256", "")).strip().upper()
    require(len(current_bgm_hash) == 64, "audio:bgm_original_sha256_missing", errors)
    require(bool(str(audio.get("bgm_audio_fingerprint", "")).strip()),
            "audio:bgm_audio_fingerprint_missing", errors)
    require(isinstance(audio.get("bgm_audio_window_fingerprints"), list) and len(audio.get("bgm_audio_window_fingerprints", [])) > 0,
            "audio:bgm_audio_window_fingerprints_missing", errors)
    require(int(audio.get("bgm_registry_match_count", -1)) == 0,
            "audio:bgm_registry_match", errors)
    bgm_path_value = str(audio.get("bgm_original_path", "")).strip()
    if bgm_path_value:
        bgm_path = Path(bgm_path_value)
        if not bgm_path.is_absolute():
            bgm_path = base / bgm_path
        require(bgm_path.is_file(), "audio:bgm_original_file_missing", errors)
        if bgm_path.is_file() and len(current_bgm_hash) == 64:
            require(sha256(bgm_path) == current_bgm_hash, "audio:bgm_original_hash_mismatch", errors)
    if len(current_bgm_hash) == 64 and len(previous_bgm_hash) == 64:
        require(current_bgm_hash != previous_bgm_hash, "audio:same_bgm_as_previous_project", errors)
    current_track_id = str(audio.get("bgm_canonical_track_id", "")).strip()
    previous_track_id = str(audio.get("previous_project_bgm_canonical_track_id", "")).strip()
    if current_track_id and previous_track_id:
        require(current_track_id != previous_track_id, "audio:same_bgm_track_id_as_previous_project", errors)
    director_music = director_contract.get("music", {}) if isinstance(director_contract, dict) else {}
    if isinstance(director_music, dict) and director_music:
        require(current_bgm_hash == str(director_music.get("asset_sha256", "")).upper(),
                "audio:bgm_hash_differs_from_approved_storyboard", errors)
        require(current_track_id == str(director_music.get("canonical_track_id", "")),
                "audio:bgm_track_id_differs_from_approved_storyboard", errors)
        require(str(audio.get("bgm_audio_fingerprint", "")) == str(director_music.get("audio_fingerprint", "")),
                "audio:bgm_fingerprint_differs_from_approved_storyboard", errors)
        require(set(map(str, audio.get("bgm_audio_window_fingerprints", []))) == set(map(str, director_music.get("audio_window_fingerprints", []))),
                "audio:bgm_window_fingerprints_differ_from_approved_storyboard", errors)
        require(str(audio.get("bgm_registry_sha256", "")).upper() == str(director_music.get("bgm_registry_sha256", "")).upper(),
                "audio:bgm_registry_differs_from_approved_storyboard", errors)
    for field in ("voice_path", "bgm_ducked_path", "final_mix_path"):
        require(bool(audio.get(field)), f"audio:{field}_missing", errors)
    validate_evidence(audio.get("evidence"), base, "audio", errors)

    qa = data.get("qa", {})
    for field in ("full_decode_zero_errors", "continuous_ranges_reviewed", "full_watch_completed", "desktop_hash_match"):
        require(qa.get(field) is True, f"qa:{field}_failed", errors)
    validate_evidence(qa.get("evidence"), base, "qa", errors)

    publication = data.get("publication", {})
    require(not (publication.get("performed") and not publication.get("authorized")),
            "publication:unauthorized_publish", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the mandatory editorial production contract.")
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    path = args.manifest.resolve()
    if not path.is_file():
        print(f"FAIL manifest missing: {path}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    errors = validate_manifest(data, path)
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print(f"PRODUCTION GATE CLOSED ({len(errors)} failures)")
        return 1
    print("PRODUCTION ENFORCEMENT PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
