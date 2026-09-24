#!/usr/bin/env python3
"""Independent stdlib tests for production_runner.py."""

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
import production_runner as runner  # noqa: E402


class ProductionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()

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

    def input_manifest(self, files: list[dict], requiredroles: list[str] | None = None) -> None:
        payload: dict = {"files": files}
        if requiredroles is not None:
            payload["requiredroles"] = requiredroles
        self.write("artifacts/editorial-plugin-inputs.json", json.dumps(payload))

    def media_manifest(self, files: list[dict], tolerance: float = 0.08) -> Path:
        return self.write("artifacts/media-audit.json", json.dumps({"files": files, "max_duration_tol": tolerance}))

    def test_plan_maps_all_original_critical_gates(self) -> None:
        expected = {
            "design": [("validate_design_lock.py", ["--lock", "artifacts/design-lock.json", "--require-approved"])],
            "storyboard": [("validate_director_storyboard.py", ["--contract", "artifacts/director-storyboard.json", "--stage", "plan"])],
            "batch": [
                ("validate_director_storyboard.py", ["--contract", "artifacts/director-storyboard.json", "--stage", "batch"]),
                ("validate_production_enforcement.py", ["--manifest", "artifacts/production-enforcement.json"]),
            ],
            "ingest": [("validate_dynamic_asset_duration.py", ["--manifest", "artifacts/dynamic-asset-duration-records.json"])],
            "master": [
                (
                    "validate_editorial_project.py",
                    [
                        "--project-contract",
                        "artifacts/editorial-project-contract.json",
                        "--qa-manifest",
                        "artifacts/editorial-qa-manifest-v1.json",
                    ],
                ),
                ("validate_production_enforcement.py", ["--manifest", "artifacts/production-enforcement.json"]),
            ],
        }
        for stage, expected_checks in expected.items():
            with self.subTest(stage=stage):
                plan = runner.plan_stage(stage)
                self.assertEqual(
                    [(check["script"], check["arguments"]) for check in plan["checks"]], expected_checks
                )

    def test_check_hashes_inputs_and_runs_real_mapped_validator(self) -> None:
        source = self.write("source/script.txt", "approved script")
        self.input_manifest([{"path": "source/script.txt", "sha256": self.digest(source), "role": "script"}], ["script"])
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "validator passed", "")

        with patch.object(runner.subprocess, "run", side_effect=fake_run):
            result = runner.check_stage(self.root, "design")
        self.assertTrue(result["passed"])
        self.assertTrue(result["input_check"]["passed"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].endswith("validate_design_lock.py"))
        self.assertEqual(calls[0][2:], ["--lock", "artifacts/design-lock.json", "--require-approved"])
        self.assertFalse(result["quality_review_claimed"])

    def test_validator_exit_failure_is_not_overridden_by_manifest_like_pass_text(self) -> None:
        source = self.write("source/script.txt", "approved script")
        self.input_manifest([{"path": "source/script.txt", "sha256": self.digest(source)}])

        def failed_run(command, **_kwargs):
            return subprocess.CompletedProcess(command, 1, '{"passed": true}', "actual gate failed")

        with patch.object(runner.subprocess, "run", side_effect=failed_run):
            result = runner.check_stage(self.root, "design")
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"][0]["passed"])
        self.assertEqual(result["checks"][0]["exit_code"], 1)

    def test_input_hash_drift_and_required_role_fail(self) -> None:
        source = self.write("source/script.txt", "changed")
        self.input_manifest([{"path": "source/script.txt", "sha256": "0" * 64, "role": "other"}], ["script"])
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "OK", "")):
            result = runner.check_stage(self.root, "storyboard")
        self.assertFalse(result["passed"])
        self.assertFalse(result["input_check"]["passed"])
        self.assertIn("missing required roles: script", result["input_check"]["errors"])
        self.assertEqual(result["input_check"]["files"][0]["error"], "SHA-256 drift")

    def test_input_path_outside_project_is_refused(self) -> None:
        source = self.write("source/script.txt", "approved")
        self.input_manifest([{"path": "../source/script.txt", "sha256": self.digest(source)}])
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "OK", "")):
            result = runner.check_stage(self.root, "design")
        self.assertFalse(result["input_check"]["passed"])
        self.assertIn("safe project-relative", result["input_check"]["files"][0]["error"])

    def video_entry(self, path: str, digest: str, allow_audio: bool = True) -> dict:
        return {
            "path": path,
            "sha256": digest,
            "kind": "video",
            "expected_duration": 2.0,
            "expected_width": 1920,
            "expected_height": 1080,
            "sample_rate": 48000,
            "channels": 2,
            "allow_audio": allow_audio,
        }

    @staticmethod
    def probe_payload(include_audio: bool = True) -> str:
        streams = [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30000/1001",
                "avg_frame_rate": "30000/1001",
            }
        ]
        if include_audio:
            streams.append({"codec_type": "audio", "sample_rate": "48000", "channels": 2})
        return json.dumps({"format": {"duration": "2.03"}, "streams": streams})

    @staticmethod
    def audio_probe_payload() -> str:
        return json.dumps(
            {
                "format": {"duration": "2.00"},
                "streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2}],
            }
        )

    def test_media_audit_hash_probe_dimensions_duration_and_rational(self) -> None:
        video = self.write("media/clip.mp4", b"tiny synthetic media")
        manifest = self.media_manifest([self.video_entry("media/clip.mp4", self.digest(video))])

        def fake_probe(command, **_kwargs):
            self.assertEqual(command[0], "fake-ffprobe")
            return subprocess.CompletedProcess(command, 0, self.probe_payload(), "")

        with patch.object(runner.subprocess, "run", side_effect=fake_probe):
            result = runner.media_audit(self.root, manifest, ffprobe="fake-ffprobe")
        self.assertTrue(result["passed"])
        self.assertTrue(result["checks"][0]["passed"])
        self.assertEqual(result["checks"][0]["frame_rate"], "30000/1001")
        self.assertEqual(result["checks"][0]["streams"], {"video": 1, "audio": 1})

    def test_media_audit_rejects_extra_audio_and_hash_drift_without_guessing(self) -> None:
        video = self.write("media/mute.mp4", b"known bytes")
        manifest = self.media_manifest([self.video_entry("media/mute.mp4", self.digest(video), allow_audio=False)])

        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, self.probe_payload(include_audio=True), ""),
        ):
            extra_audio = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertFalse(extra_audio["passed"])
        self.assertIn("unexpected extra audio stream", extra_audio["checks"][0]["errors"])

        video.write_bytes(b"old export or drift")
        with patch.object(runner.subprocess, "run") as not_called:
            drift = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertFalse(drift["passed"])
        self.assertEqual(drift["checks"][0]["error"], "SHA-256 drift")
        not_called.assert_not_called()

    def test_media_audit_accepts_pure_audio_without_meaningless_dimensions(self) -> None:
        audio = self.write("media/voice.wav", b"tiny audio")
        entry = {
            "path": "media/voice.wav",
            "sha256": self.digest(audio),
            "kind": "audio",
            "expected_duration": 2.0,
            # Null/missing dimensions are valid for a pure audio asset.
            "expected_width": None,
            "sample_rate": 48000,
            "channels": 2,
            "allow_audio": True,
        }
        manifest = self.media_manifest([entry])
        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, self.audio_probe_payload(), ""),
        ):
            result = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks"][0]["streams"], {"video": 0, "audio": 1})

    def test_media_audit_accepts_silent_video_and_rejects_wrong_expected_fps(self) -> None:
        video = self.write("media/silent.mp4", b"tiny silent video")
        entry = self.video_entry("media/silent.mp4", self.digest(video), allow_audio=False)
        # Null/missing audio settings are valid when the video must be silent.
        entry["sample_rate"] = None
        entry.pop("channels")
        entry["expected_fps"] = "30000/1001"
        manifest = self.media_manifest([entry])
        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, self.probe_payload(include_audio=False), ""),
        ):
            passed = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertTrue(passed["passed"])
        self.assertEqual(passed["checks"][0]["expected_fps"], "30000/1001")

        entry["expected_fps"] = "24/1"
        manifest = self.media_manifest([entry])
        with patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, self.probe_payload(include_audio=False), ""),
        ):
            wrong_fps = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertFalse(wrong_fps["passed"])
        self.assertIn("video frame rational does not match expected_fps", wrong_fps["checks"][0]["errors"])

    def test_media_manifest_missing_required_data_fails(self) -> None:
        asset = self.write("media/audio.wav", b"bytes")
        manifest = self.media_manifest([{"path": "media/audio.wav", "sha256": self.digest(asset), "kind": "audio"}])
        result = runner.media_audit(self.root, manifest.relative_to(self.root), ffprobe="fake-ffprobe")
        self.assertFalse(result["passed"])
        self.assertIn("expected_duration", result["checks"][0]["error"])

    def test_decode_is_serial_two_threads_and_is_not_a_render(self) -> None:
        video = self.write("media/clip.mp4", b"tiny synthetic media")
        manifest = self.media_manifest([self.video_entry("media/clip.mp4", self.digest(video))])
        commands: list[list[str]] = []

        def fake_commands(command, **_kwargs):
            commands.append(list(command))
            if command[0] == "fake-ffprobe":
                return subprocess.CompletedProcess(command, 0, self.probe_payload(), "")
            self.assertEqual(command[0], "fake-ffmpeg")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(runner.subprocess, "run", side_effect=fake_commands):
            result = runner.media_audit(
                self.root,
                manifest.relative_to(self.root),
                ffprobe="fake-ffprobe",
                ffmpeg="fake-ffmpeg",
                decode=True,
            )
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["decode_checks"]), 1)
        self.assertEqual(result["decode_checks"][0]["threads"], 2)
        self.assertIn("-threads", commands[1])
        self.assertIn("2", commands[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
