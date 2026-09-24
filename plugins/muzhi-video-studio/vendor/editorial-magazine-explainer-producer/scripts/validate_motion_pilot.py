from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from validate_director_storyboard import probe_media, trusted_bgm_registry_from_local_config, validate_storyboard


REQUIRED_PILOT_FLAGS = (
    "hardest_representative_section",
    "real_narration",
    "final_caption_style",
    "flow_or_equivalent_organic_action",
    "local_semantic_animation",
    "data_or_evidence_scene",
    "object_based_handoff",
    "actual_voice_processing_sample",
    "actual_music_sample",
)
VETOES = ("ppt_like", "cheap_ai_like", "style_inconsistent", "stiff_animation")
FORBIDDEN = (
    "batch_asset_generation_started",
    "full_flow_batch_started",
    "full_formal_production_timeline_created",
    "full_audio_processing_started",
    "final_master_render_started",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "__FILL" not in value


def verify_artifact(section: dict, path_key: str, hash_key: str, project_root: Path, scope: str, verify_files: bool, errors: list[str]) -> None:
    value = section.get(path_key)
    digest = str(section.get(hash_key, "")).upper()
    if not filled(value):
        errors.append(f"{scope}.{path_key} must be filled")
        return
    if len(digest) != 64:
        errors.append(f"{scope}.{hash_key} must be SHA-256")
        return
    if verify_files:
        path = Path(str(value))
        if not path.is_absolute():
            path = project_root / path
        if not path.is_file():
            errors.append(f"{scope} file missing: {path}")
        elif sha256(path) != digest:
            errors.append(f"{scope} SHA-256 mismatch")


def validate(data: dict[str, object], contract_path: Path, verify_files: bool) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != "1.1":
        errors.append("schema_version must equal 1.1")
    for key in ("project_id", "project_root", "title"):
        if not filled(data.get(key)):
            errors.append(f"{key} must be filled")
    status = data.get("status")
    if status not in {"draft", "waiting_user_review", "approved", "rejected"}:
        errors.append("status is invalid")

    baseline = data.get("golden_baseline") if isinstance(data.get("golden_baseline"), dict) else {}
    for key in ("asset_id", "reference_path", "source_master_sha256"):
        if not filled(baseline.get(key)):
            errors.append(f"golden_baseline.{key} must be filled")
    if len(str(baseline.get("source_master_sha256", ""))) != 64:
        errors.append("golden_baseline.source_master_sha256 must be SHA-256")
    if baseline.get("ninety_percent_locked") is not True:
        errors.append("golden_baseline.ninety_percent_locked must be true")
    if baseline.get("maximum_upgrade_percent") != 10:
        errors.append("golden_baseline.maximum_upgrade_percent must equal 10")

    upstream = data.get("upstream_gates") if isinstance(data.get("upstream_gates"), dict) else {}
    for key in ("director_interpretation_user_approved", "visual_storyboard_user_approved", "full_voiced_animatic_user_approved"):
        if upstream.get(key) is not True:
            errors.append(f"upstream_gates.{key} must be true")
    if upstream.get("brand_06_signoff") != "pass":
        errors.append("upstream_gates.brand_06_signoff must be pass")
    if upstream.get("technical_07_signoff") != "pass":
        errors.append("upstream_gates.technical_07_signoff must be pass")
    project_root = Path(str(data.get("project_root", contract_path.parent)))
    verify_artifact(upstream, "director_storyboard_contract_path", "director_storyboard_contract_sha256", project_root, "upstream_gates.director_storyboard", verify_files, errors)
    verify_artifact(upstream, "new_project_bgm_path", "new_project_bgm_sha256", project_root, "upstream_gates.new_project_bgm", verify_files, errors)
    current_bgm = str(upstream.get("new_project_bgm_sha256", "")).upper()
    previous_bgm = str(upstream.get("previous_project_bgm_sha256", "")).upper()
    if len(current_bgm) == 64 and len(previous_bgm) == 64 and current_bgm == previous_bgm:
        errors.append("upstream_gates new BGM must differ from previous project")
    storyboard_value = upstream.get("director_storyboard_contract_path")
    if verify_files and filled(storyboard_value):
        storyboard_path = Path(str(storyboard_value))
        if not storyboard_path.is_absolute():
            storyboard_path = project_root / storyboard_path
        if storyboard_path.is_file():
            try:
                storyboard_data = json.loads(storyboard_path.read_text(encoding="utf-8-sig"))
                for error in validate_storyboard(storyboard_data, storyboard_path, "batch", trusted_bgm_registry_from_local_config(storyboard_data)):
                    errors.append(f"upstream_gates.director_storyboard:{error}")
            except (OSError, json.JSONDecodeError):
                errors.append("upstream_gates.director_storyboard:invalid_json")

    pilot = data.get("pilot") if isinstance(data.get("pilot"), dict) else {}
    for key in REQUIRED_PILOT_FLAGS:
        if pilot.get(key) is not True:
            errors.append(f"pilot.{key} must be true")
    duration = pilot.get("duration_seconds")
    if not isinstance(duration, (int, float)) or not 15 <= float(duration) <= 20:
        errors.append("pilot.duration_seconds must be between 15 and 20")

    budget = data.get("preapproval_budget") if isinstance(data.get("preapproval_budget"), dict) else {}
    image_used = budget.get("image_generation_calls_used")
    image_cap = budget.get("image_generation_call_cap")
    flow_used = budget.get("flow_tests_used")
    flow_cap = budget.get("flow_test_cap")
    if image_cap != 10 or not isinstance(image_used, int) or image_used < 0 or image_used > image_cap:
        errors.append("preapproval_budget image calls exceed the fixed cap")
    if flow_cap != 2 or not isinstance(flow_used, int) or flow_used < 0 or flow_used > flow_cap:
        errors.append("preapproval_budget Flow tests exceed the fixed cap")

    forbidden = data.get("forbidden_before_approval") if isinstance(data.get("forbidden_before_approval"), dict) else {}
    if status != "approved":
        for key in FORBIDDEN:
            if forbidden.get(key) is not False:
                errors.append(f"forbidden_before_approval.{key} must remain false")

    vetoes = data.get("aesthetic_vetoes") if isinstance(data.get("aesthetic_vetoes"), dict) else {}
    veto_count = sum(1 for key in VETOES if vetoes.get(key) is True)
    for key in VETOES:
        if not isinstance(vetoes.get(key), bool):
            errors.append(f"aesthetic_vetoes.{key} must be boolean")

    review = data.get("human_review") if isinstance(data.get("human_review"), dict) else {}
    batch_release = data.get("batch_release_allowed")
    if status == "approved":
        if veto_count:
            errors.append("approved pilot cannot contain aesthetic vetoes")
        for key in ("approved_by", "approval_quote", "approved_at"):
            if not filled(review.get(key)):
                errors.append(f"human_review.{key} is required for approval")
        if batch_release is not True:
            errors.append("batch_release_allowed must be true after approval")
        if not filled(pilot.get("path")) or len(str(pilot.get("sha256", ""))) != 64:
            errors.append("approved pilot requires real path and SHA-256")
        if verify_files and filled(pilot.get("path")):
            path = Path(str(pilot["path"]))
            if not path.is_absolute():
                path = Path(str(data["project_root"])) / path
            if not path.exists():
                errors.append(f"pilot file missing: {path}")
            elif sha256(path) != str(pilot.get("sha256", "")).upper():
                errors.append("pilot SHA-256 mismatch")
            else:
                try:
                    actual_duration, stream_types = probe_media(path)
                    if "video" not in stream_types:
                        errors.append("pilot real video stream missing")
                    if "audio" not in stream_types:
                        errors.append("pilot real audio stream missing")
                    if not 15 <= actual_duration <= 20.1:
                        errors.append("pilot real duration must be between 15 and 20 seconds")
                    if abs(actual_duration - float(duration)) > 0.12:
                        errors.append("pilot declared duration does not match real media")
                except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
                    errors.append("pilot real media probe failed")
    else:
        if batch_release is not False:
            errors.append("batch_release_allowed must remain false before approval")
    return errors


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from test_director_storyboard import good_contract

        storyboard = good_contract(root)
        storyboard_file = root / "director-storyboard.json"
        storyboard_file.write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
        pilot_file = root / "pilot.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=10:d=16",
            "-i", str(root / "voice.wav"), "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(pilot_file)
        ], check=True)
        data = {
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
                "director_storyboard_contract_path": str(storyboard_file),
                "director_storyboard_contract_sha256": sha256(storyboard_file),
                "new_project_bgm_path": str(root / "music.wav"),
                "new_project_bgm_sha256": sha256(root / "music.wav"),
                "previous_project_bgm_sha256": "B" * 64,
                "brand_06_signoff": "pass",
                "technical_07_signoff": "pass",
            },
            "pilot": {"path": str(pilot_file), "sha256": sha256(pilot_file), "duration_seconds": 16, **{key: True for key in REQUIRED_PILOT_FLAGS}},
            "preapproval_budget": {"image_generation_calls_used": 8, "image_generation_call_cap": 10, "flow_tests_used": 2, "flow_test_cap": 2},
            "forbidden_before_approval": {key: False for key in FORBIDDEN},
            "aesthetic_vetoes": {key: False for key in VETOES},
            "human_review": {"approved_by": "品牌", "approval_quote": "样片通过", "approved_at": "2026-01-01T00:00:00+08:00"},
            "batch_release_allowed": True,
        }
        errors = validate(data, root / "contract.json", True)
        if errors:
            print("SELF-TEST FAIL", errors)
            return 1
        dummy = root / "dummy.mp4"
        dummy.write_bytes(b"not-media")
        bad_storyboard = copy.deepcopy(storyboard)
        bad_storyboard["planning_policy"]["fixed_shot_count"] = 60
        bad_storyboard_file = root / "bad-director-storyboard.json"
        bad_storyboard_file.write_text(json.dumps(bad_storyboard, ensure_ascii=False), encoding="utf-8")
        cases = [
            ("ppt", lambda d: d["aesthetic_vetoes"].update(ppt_like=True), "approved pilot cannot contain aesthetic vetoes"),
            ("dummy_media", lambda d: d["pilot"].update(path=str(dummy), sha256=sha256(dummy)), "pilot real media probe failed"),
            ("invalid_storyboard", lambda d: d["upstream_gates"].update(director_storyboard_contract_path=str(bad_storyboard_file), director_storyboard_contract_sha256=sha256(bad_storyboard_file)), "fixed_shot_count_forbidden"),
            ("same_bgm", lambda d: d["upstream_gates"].update(previous_project_bgm_sha256=d["upstream_gates"]["new_project_bgm_sha256"]), "new BGM must differ"),
            ("brand_unsigned", lambda d: d["upstream_gates"].update(brand_06_signoff="pending"), "brand_06_signoff must be pass"),
        ]
        for name, mutate, expected in cases:
            candidate = copy.deepcopy(data)
            mutate(candidate)
            candidate_errors = validate(candidate, root / "contract.json", True)
            if not any(expected in error for error in candidate_errors):
                print("SELF-TEST FAIL", name, candidate_errors)
                return 1
    print(f"SELF-TEST PASS {len(cases)}/{len(cases)} negative cases")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--skip-file-verification", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.contract is None:
        parser.error("--contract is required unless --self-test is used")
    if args.skip_file_verification:
        print("FAIL --skip-file-verification is draft-only and cannot unlock the motion-pilot Gate")
        return 1
    data = json.loads(args.contract.read_text(encoding="utf-8-sig"))
    errors = validate(data, args.contract, not args.skip_file_verification)
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        print(f"MOTION PILOT GATE CLOSED ({len(errors)} failures)")
        return 1
    if data.get("status") != "approved":
        print("MOTION PILOT CONTRACT VALID")
        print(f"MOTION PILOT GATE CLOSED ({data.get('status')})")
        return 1
    print("MOTION PILOT GATE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
