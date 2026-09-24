#!/usr/bin/env python3
"""Independent stdlib tests for provider_router.py."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provider_router as router  # noqa: E402


class ProviderRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.other = Path(self.temporary.name) / "other-project"
        self.other.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: bytes | str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def delivery(self, provider: str, path: str, digest: str, job_id: str | None = None) -> dict:
        return {
            "shot_id": "shot-001",
            "source_provider": provider,
            "provider_job_id": job_id,
            "path": path,
            "sha256": digest,
            "duration": 2.0,
            "width": 1920,
            "height": 1080,
            "fps": "30000/1001",
            "source_audio_removed": True,
            "source_start": 0.0,
            "timeline_start": 4.0,
            "usable_duration": 2.0,
            "playback_rate": 1,
        }

    def manifest(self, deliveries: list[dict]) -> Path:
        return self.write("artifacts/delivery-manifest.json", json.dumps({"deliveries": deliveries}))

    def test_builtin_list_has_the_required_provider_modes(self) -> None:
        listed = router.list_providers()
        modes = {provider["id"]: provider["mode"] for provider in listed["providers"]}
        self.assertEqual(modes, {"local-h3": "local_workflow", "wan": "configured_api", "minimax": "configured_api", "google-flow": "manual"})
        google = next(provider for provider in listed["providers"] if provider["id"] == "google-flow")
        self.assertEqual(google["manual_delivery"], "first_frame_prompt_flatpack")

    def test_missing_project_state_asks_for_user_choice_without_writing(self) -> None:
        result = router.status(self.root)
        self.assertTrue(result["needs_user_choice"])
        self.assertIsNone(result["selection"])
        self.assertFalse((self.root / router.STATE_RELATIVE).exists())

    def test_select_is_idempotent_and_preserves_actual_initial_quote(self) -> None:
        first = router.select_provider(self.root, "wan", quote="本项目未来未提交镜头使用 Wan")
        repeated = router.select_provider(self.root, "wan")
        self.assertTrue(first["changed"])
        self.assertFalse(repeated["changed"])
        self.assertTrue(repeated["idempotent"])
        current = router.status(self.root)
        self.assertEqual(current["selection"]["quote"], "本项目未来未提交镜头使用 Wan")
        self.assertEqual(len(current["history"]), 1)
        self.assertEqual(current["selection"]["scope"], "future_unsubmitted")

    def test_switch_logs_history_without_erasing_receipts_or_pending_jobs(self) -> None:
        router.select_provider(self.root, "wan", quote="先用 Wan")
        state_path = self.root / router.STATE_RELATIVE
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        saved["delivery_receipts"] = [{"shot_id": "old-shot", "receipt": "kept"}]
        saved["pending_job_ids"] = ["wan-pending-17"]
        state_path.write_text(json.dumps(saved), encoding="utf-8")

        router.select_provider(self.root, "minimax", quote="后续未提交镜头换 MiniMax")
        current = router.status(self.root)
        self.assertEqual(current["selection"]["provider_id"], "minimax")
        self.assertEqual(current["delivery_receipts"], [{"shot_id": "old-shot", "receipt": "kept"}])
        self.assertEqual(current["pending_job_ids"], ["wan-pending-17"])
        self.assertEqual([item["action"] for item in current["history"]], ["selected", "switched"])
        self.assertEqual(current["history"][1]["from_provider"], "wan")

    def test_custom_registry_is_project_local_and_unverified(self) -> None:
        created = router.register_provider(
            self.root,
            "local-video",
            "Local Video Adapter",
            "configured_api",
            "新增此项目的临时能力描述",
            tool_ref="local_video_adapter",
        )
        self.assertTrue(created["changed"])
        self.assertFalse(created["provider"]["adapter_verified"])
        here = router.list_providers(self.root)
        elsewhere = router.list_providers(self.other)
        self.assertIn("local-video", {provider["id"] for provider in here["providers"]})
        self.assertNotIn("local-video", {provider["id"] for provider in elsewhere["providers"]})
        self.assertFalse(router.status(self.root)["custom_registry"]["local-video"]["adapter_verified"])

    def test_register_refuses_credentials_urls_and_missing_configured_tool_ref(self) -> None:
        with self.assertRaises(router.RouterError):
            router.register_provider(self.root, "unsafe", "Unsafe", "configured_api", "不允许", tool_ref="https://bad.example")
        with self.assertRaises(router.RouterError):
            router.register_provider(self.root, "unsafe", "Unsafe", "configured_api", "不允许", tool_ref="MY_API_TOKEN")
        with self.assertRaises(router.RouterError):
            router.register_provider(self.root, "no-ref", "No Ref", "configured_api", "缺少能力名")
        self.assertFalse((self.root / router.STATE_RELATIVE).exists())

    def test_contract_is_renderer_agnostic(self) -> None:
        result = router.contract(self.root)
        self.assertTrue(result["provider_agnostic"])
        self.assertFalse(result["renderer_provider_branches"])
        self.assertEqual(set(router.DELIVERY_REQUIRED_FIELDS), set(result["required_fields"]))
        self.assertIn("provider_job_id", result["optional_fields"])

    def test_manual_and_configured_api_deliveries_share_one_contract(self) -> None:
        media = self.write("media/clip.mp4", b"provider-independent bytes")
        digest = self.digest(media)
        manifest = self.manifest(
            [
                self.delivery("google-flow", "media/clip.mp4", digest, None),
                self.delivery("wan", "media/clip.mp4", digest, "wan-job-1"),
            ]
        )
        result = router.validate_delivery(self.root, manifest)
        self.assertTrue(result["passed"])
        self.assertTrue(result["provider_agnostic"])
        self.assertEqual([item["source_provider"] for item in result["checks"]], ["google-flow", "wan"])

    def test_delivery_bad_hash_and_speed_change_are_refused(self) -> None:
        media = self.write("media/clip.mp4", b"correct bytes")
        bad = self.delivery("wan", "media/clip.mp4", "0" * 64, "job")
        bad["playback_rate"] = 1.25
        result = router.validate_delivery(self.root, self.manifest([bad]))
        self.assertFalse(result["passed"])
        # Hash validation runs on the actual source and cannot be overridden by
        # a manifest's own claims.
        self.assertEqual(result["checks"][0]["error"], "playback_rate must equal 1; speed changes are not permitted")
        bad["playback_rate"] = 1
        result = router.validate_delivery(self.root, self.manifest([bad]))
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks"][0]["error"], "SHA-256 drift")

    def test_optional_ffprobe_checks_actual_facts_and_audio_removed_promise(self) -> None:
        media = self.write("media/clip.mp4", b"media bytes")
        manifest = self.manifest([self.delivery("minimax", "media/clip.mp4", self.digest(media), "mini-job")])
        payload = json.dumps(
            {
                "format": {"duration": "2.02"},
                "streams": [
                    {"codec_type": "video", "width": 1920, "height": 1080, "r_frame_rate": "30000/1001"},
                    {"codec_type": "audio"},
                ],
            }
        )
        with patch.object(
            router.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, payload, ""),
        ):
            result = router.validate_delivery(self.root, manifest, ffprobe="fake-ffprobe")
        self.assertFalse(result["passed"])
        self.assertIn("source_audio_removed promised no audio stream", result["probe_checks"][0]["errors"])
        self.assertFalse(result["quality_review_claimed"])

    def test_manifest_paths_outside_project_are_refused(self) -> None:
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text(json.dumps({"deliveries": []}), encoding="utf-8")
        result = router.validate_delivery(self.root, outside)
        self.assertFalse(result["passed"])
        self.assertIn("inside --project", result["manifest_check"]["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
