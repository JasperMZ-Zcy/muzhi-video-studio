"""Mock-only tests: these never start ComfyUI or invoke a GPU runner."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_h3_adapter as adapter  # noqa: E402
import provider_router  # noqa: E402


class LocalH3AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "first.png").write_bytes(b"approved-first-frame")
        (self.project / "motion.txt").write_text("Turn one page, then read.", encoding="utf-8")
        self.ai = self.root / "ai"
        self.ai.mkdir()
        self.desktop = self.root / "desktop"
        self.desktop.mkdir()
        self.runner = self.root / "generate-h3-i2v-v2.ps1"
        self.runner.write_text("formal runner fixture", encoding="utf-8")
        self.image_hash = hashlib.sha256((self.project / "first.png").read_bytes()).hexdigest()
        self.prompt_hash = hashlib.sha256((self.project / "motion.txt").read_bytes()).hexdigest()
        self.ffprobe = str(self.root / "ffprobe.exe")
        Path(self.ffprobe).write_bytes(b"mock-ffprobe")
        self.calls = []
        self.args = adapter._parser().parse_args([
            "run", "--project", str(self.project), "--shot-id", "s01",
            "--input-image", "first.png", "--prompt-file", "motion.txt",
            "--profile", "Fast720Seven", "--seed", "42", "--runner", str(self.runner),
            "--accept-local-heavy", "--authorization-quote", "本条未提交镜头用本地 H3",
            "--approved-input-sha256", self.image_hash, "--ffprobe", self.ffprobe,
            "--approved-prompt-sha256", self.prompt_hash,
            "--timeline-start", "12.5", "--usable-duration", "6.9",
        ])
        self.context = adapter._context(self.args)
        route_patch = patch.object(adapter, "provider_status", return_value={
            "selection": {"provider_id": "local-h3", "scope": "future_unsubmitted",
                          "quote": "以后图生视频默认本地", "source": "project_explicit"}})
        route_patch.start()
        self.addCleanup(route_patch.stop)

    def response(self, stdout="", code=0, stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def mock_command(self, command, *, timeout=None):
        self.calls.append(command)
        if "-ValidateOnly" in command:
            return self.response(json.dumps({"status": "ready", "profile": self.args.profile,
                                             "aiRoot": str(self.ai), "hotRoot": str(self.root / "hot")}))
        if "-Command" in command:
            return self.response(str(self.desktop) + "\n")
        if Path(command[0]).resolve() == Path(self.ffprobe).resolve() and command[1:] == ["-version"]:
            return self.response("ffprobe mock version")
        if Path(command[0]).resolve() == Path(self.ffprobe).resolve():
            return self.response(json.dumps({"streams": [{"codec_type": "video", "width": 720,
                "height": 1280, "avg_frame_rate": "24/1", "nb_frames": "168", "nb_read_frames": "168"}],
                "format": {"duration": "7.000000"}}))
        if "-InputImage" in command:
            self.write_formal_result()
            return self.response("runner completed")
        raise AssertionError(command)

    def write_formal_result(self, *, bad_hash=False, with_bom=True):
        runtime_outputs = self.ai / "H3_v2_lab_runtime" / "outputs"
        runtime_outputs.mkdir(parents=True, exist_ok=True)
        source = runtime_outputs / (self.context["output_name"] + ".mp4")
        source.write_bytes(b"mock-mp4-bytes")
        preview_root = self.desktop / "牧之远见-视频预览"
        preview_root.mkdir(exist_ok=True)
        (preview_root / source.name).write_bytes(source.read_bytes())
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if bad_hash:
            digest = "0" * 64
        result = {"status": "success", "profile": self.args.profile,
                  "input": str(self.project / "first.png"), "output": str(source),
                  "desktop": str(preview_root / source.name),
                  "sha256": digest, "copyHashMatches": True, "base": {"runKey": "v2run_mock"}}
        result_path = runtime_outputs / (self.context["output_name"] + ".v2-result.json")
        result_path.write_text(json.dumps(result), encoding="utf-8-sig" if with_bom else "utf-8")

    def test_plan_is_read_only_and_identifies_inputs(self):
        args = adapter._parser().parse_args([
            "plan", "--project", str(self.project), "--shot-id", "s01",
            "--input-image", "first.png", "--prompt-file", "motion.txt",
            "--profile", "Fast720Seven", "--seed", "42", "--runner", str(self.runner),
        ])
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            result = adapter.plan(args)
        self.assertTrue(result["ready"])
        self.assertEqual(result["input_sha256"], self.image_hash)
        self.assertFalse(result["generation_started"])
        self.assertTrue(result["route_selected"])
        self.assertFalse(any("-InputImage" in command for command in self.calls))
        self.assertFalse((self.project / "artifacts").exists())

    def test_success_receipt_and_deduplication(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            first = adapter.run(self.args)
            second = adapter.run(self.args)
        self.assertEqual(first["status"], "ingested_pending_visual_review")
        self.assertTrue(second["reused_existing_result"])
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)
        manifest = json.loads(Path(first["delivery_manifest"]).read_text(encoding="utf-8"))
        delivery = manifest["deliveries"][0]
        self.assertEqual(delivery["source_provider"], "local-h3")
        self.assertEqual(delivery["provider_job_id"], "v2run_mock")
        self.assertEqual(delivery["width"], 720)
        self.assertEqual(delivery["duration"], 7)
        self.assertEqual(delivery["quality_review_status"], "not_reviewed")
        self.assertEqual(delivery["source_audio_removed"], True)
        self.assertEqual(adapter._sha256(self.project / delivery["path"]), first["source_sha256"])
        router_check = provider_router.validate_delivery(self.project, first["delivery_manifest"])
        self.assertTrue(router_check["passed"], router_check)

    def test_existing_result_recovers_without_new_preflight(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            first = adapter.run(self.args)
        def no_preflight(command, *, timeout=None):
            if "-ValidateOnly" in command:
                raise AssertionError("existing result must not require new model/drive preflight")
            return self.mock_command(command, timeout=timeout)
        with patch.object(adapter, "_command", side_effect=no_preflight):
            recovered = adapter.run(self.args)
        self.assertEqual(first["status"], "ingested_pending_visual_review")
        self.assertTrue(recovered["reused_existing_result"])

    def test_submitted_h3_success_can_be_recovered_after_switch_to_wan(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            first = adapter.run(self.args)
        self.assertEqual(first["status"], "ingested_pending_visual_review")
        with patch.object(adapter, "provider_status", return_value={
            "selection": {"provider_id": "wan", "scope": "future_unsubmitted"}}), \
             patch.object(adapter, "_command", side_effect=self.mock_command):
            recovered = adapter.run(self.args)
        self.assertEqual(recovered["status"], "ingested_pending_visual_review")
        self.assertTrue(recovered["reused_existing_result"])
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_incomplete_h3_only_returns_resume_after_switch_to_wan(self):
        def fail_runner(command, *, timeout=None):
            if "-InputImage" in command:
                self.calls.append(command)
                return self.response(code=1, stderr="stage stopped")
            return self.mock_command(command, timeout=timeout)
        with patch.object(adapter, "_command", side_effect=fail_runner):
            first = adapter.run(self.args)
        self.assertEqual(first["status"], "resume_required")
        with patch.object(adapter, "provider_status", return_value={
            "selection": {"provider_id": "wan", "scope": "future_unsubmitted"}}), \
             patch.object(adapter, "_command", side_effect=fail_runner):
            recovered = adapter.run(self.args)
        self.assertEqual(recovered["status"], "resume_required")
        self.assertFalse(recovered["generation_started"])
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_failed_runner_does_not_submit_again(self):
        def fail(command, *, timeout=None):
            if "-InputImage" in command:
                self.calls.append(command)
                return self.response(code=1, stderr="stage stopped")
            return self.mock_command(command, timeout=timeout)
        with patch.object(adapter, "_command", side_effect=fail):
            first = adapter.run(self.args)
            second = adapter.run(self.args)
        self.assertEqual(first["status"], "resume_required")
        self.assertEqual(second["status"], "resume_required")
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_runner_code_change_does_not_create_new_submission_identity(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            first = adapter.run(self.args)
            self.runner.write_text("updated fixture", encoding="utf-8")
            second = adapter.run(self.args)
        self.assertEqual(first["status"], "ingested_pending_visual_review")
        self.assertTrue(second["reused_existing_result"])
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_bad_hash_and_bad_video_spec_are_not_ingested(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            adapter._preflight(self.args, self.context)
        self.write_formal_result(bad_hash=True)
        with self.assertRaisesRegex(adapter.AdapterError, "SHA-256 mismatch"):
            adapter._ingest(self.context, self.args)
        self.assertFalse(self.context["media"].exists())
        self.write_formal_result()
        def bad_probe(command, *, timeout=None):
            response = self.mock_command(command, timeout=timeout)
            if Path(command[0]).resolve() == Path(self.ffprobe).resolve() and "-version" not in command:
                value = json.loads(response.stdout)
                value["streams"][0]["width"] = 640
                return self.response(json.dumps(value))
            return response
        with patch.object(adapter, "_command", side_effect=bad_probe):
            with self.assertRaisesRegex(adapter.AdapterError, "dimensions or frame count"):
                adapter._ingest(self.context, self.args)

    def test_old_media_and_formal_output_are_not_overwritten(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            adapter._preflight(self.args, self.context)
            self.context["media"].parent.mkdir(parents=True, exist_ok=True)
            self.context["media"].write_bytes(b"old-user-media")
            with self.assertRaisesRegex(adapter.AdapterError, "collision"):
                adapter.run(self.args)
        self.assertEqual(self.context["media"].read_bytes(), b"old-user-media")
        self.assertFalse(any("-InputImage" in command for command in self.calls))

    def test_existing_base_video_is_not_overwritten(self):
        base = self.ai / "H3_v2_lab_runtime" / "outputs" / (
            self.context["output_name"] + "-fast-720-seven-base.mp4")
        base.parent.mkdir(parents=True)
        base.write_bytes(b"existing-base")
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            with self.assertRaisesRegex(adapter.AdapterError, "collision"):
                adapter.run(self.args)
        self.assertEqual(base.read_bytes(), b"existing-base")
        self.assertFalse(any("-InputImage" in command for command in self.calls))

    def test_existing_optical_temp_video_is_not_overwritten(self):
        temporary = self.ai / "H3_v2_lab_runtime" / "outputs" / (
            self.context["output_name"] + ".optical.tmp.mp4")
        temporary.parent.mkdir(parents=True)
        temporary.write_bytes(b"existing-optical-temp")
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            with self.assertRaisesRegex(adapter.AdapterError, "collision"):
                adapter.run(self.args)
        self.assertEqual(temporary.read_bytes(), b"existing-optical-temp")
        self.assertFalse(any("-InputImage" in command for command in self.calls))

    def test_video_with_audio_is_not_ingested(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            adapter._preflight(self.args, self.context)
        self.write_formal_result()
        def audio_probe(command, *, timeout=None):
            response = self.mock_command(command, timeout=timeout)
            if Path(command[0]).resolve() == Path(self.ffprobe).resolve() and "-version" not in command:
                value = json.loads(response.stdout)
                value["streams"].append({"codec_type": "audio"})
                return self.response(json.dumps(value))
            return response
        with patch.object(adapter, "_command", side_effect=audio_probe):
            with self.assertRaisesRegex(adapter.AdapterError, "no audio"):
                adapter._ingest(self.context, self.args)
        self.assertFalse(self.context["media"].exists())

    def test_missing_ffprobe_blocks_before_runner(self):
        Path(self.ffprobe).unlink()
        with patch.object(adapter, "_command", side_effect=self.mock_command):
            with self.assertRaisesRegex(adapter.AdapterError, "ffprobe path does not exist"):
                adapter.run(self.args)
        self.assertFalse(any("-InputImage" in command for command in self.calls))
        self.assertFalse(self.context["attempt"].exists())

    def test_timeout_keeps_lock_and_unknown_attempt(self):
        def timeout_runner(command, *, timeout=None):
            if "-InputImage" in command:
                self.calls.append(command)
                raise subprocess.TimeoutExpired(command, timeout)
            return self.mock_command(command, timeout=timeout)
        with patch.object(adapter, "_command", side_effect=timeout_runner):
            response = adapter.run(self.args)
        self.assertEqual(response["status"], "resume_required")
        self.assertEqual(json.loads(self.context["attempt"].read_text(encoding="utf-8"))["status"], "unknown_after_timeout")
        self.assertTrue((self.ai / "H3_v2_lab_runtime" / "local-h3-adapter.lock").exists())
        with patch.object(adapter, "_command", side_effect=timeout_runner):
            again = adapter.run(self.args)
        self.assertEqual(again["status"], "resume_required")
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_approval_hash_must_match(self):
        self.args.approved_input_sha256 = "0" * 64
        with self.assertRaisesRegex(adapter.AdapterError, "approved-input-sha256"):
            adapter.run(self.args)
        self.assertEqual(self.calls, [])
        self.args.approved_input_sha256 = self.image_hash
        self.args.approved_prompt_sha256 = "0" * 64
        with self.assertRaisesRegex(adapter.AdapterError, "approved-prompt-sha256"):
            adapter.run(self.args)

    def test_nonfinite_timing_blocks_before_runner(self):
        for field, value in (("source_start", float("nan")), ("timeline_start", float("inf")),
                             ("usable_duration", float("-inf"))):
            with self.subTest(field=field):
                setattr(self.args, field, value)
                with self.assertRaisesRegex(adapter.AdapterError, "finite"):
                    adapter.run(self.args)
                self.assertFalse(self.context["attempt"].exists())
                setattr(self.args, field, {"source_start": 0.0, "timeline_start": 12.5,
                                           "usable_duration": 6.9}[field])
        self.assertEqual(self.calls, [])

    def test_corrupt_result_after_generation_is_recoverable_not_unstarted(self):
        def corrupt_after_run(command, *, timeout=None):
            response = self.mock_command(command, timeout=timeout)
            if "-InputImage" in command:
                result_path = self.ai / "H3_v2_lab_runtime" / "outputs" / (self.context["output_name"] + ".v2-result.json")
                result_path.write_text("{broken", encoding="utf-8-sig")
            return response
        with patch.object(adapter, "_command", side_effect=corrupt_after_run):
            response = adapter.run(self.args)
            again = adapter.run(self.args)
        self.assertEqual(response["status"], "resume_required")
        self.assertTrue(response["generation_started"])
        self.assertEqual(json.loads(self.context["attempt"].read_text(encoding="utf-8"))["status"], "result_needs_review")
        self.assertEqual(again["status"], "resume_required")
        self.assertEqual(sum("-InputImage" in command for command in self.calls), 1)

    def test_ingest_oserror_after_generation_is_recoverable(self):
        with patch.object(adapter, "_command", side_effect=self.mock_command), \
             patch.object(adapter, "_ingest", side_effect=OSError("result disk unavailable")):
            response = adapter.run(self.args)
        self.assertEqual(response["status"], "resume_required")
        self.assertTrue(response["generation_started"])
        self.assertEqual(json.loads(self.context["attempt"].read_text(encoding="utf-8"))["status"], "result_needs_review")

    def test_other_selected_provider_blocks_local_run(self):
        for provider in ("google-flow", "wan", "minimax"):
            with self.subTest(provider=provider), patch.object(adapter, "provider_status", return_value={
                "selection": {"provider_id": provider, "scope": "future_unsubmitted"}}):
                with self.assertRaisesRegex(adapter.AdapterError, "not local-h3"):
                    adapter.run(self.args)
        self.assertEqual(self.calls, [])

    def test_runner_discovery_from_openmontage_project(self):
        workspace = self.root / "OpenMontage"
        project = workspace / "projects" / "video-01"
        project.mkdir(parents=True)
        (project / "first.png").write_bytes(b"frame")
        (project / "motion.txt").write_text("turn page", encoding="utf-8")
        runner = workspace / "services" / "muzhi-h3-local" / "scripts" / "generate-h3-i2v-v2.ps1"
        runner.parent.mkdir(parents=True)
        runner.write_text("fixture", encoding="utf-8")
        args = adapter._parser().parse_args([
            "plan", "--project", str(project), "--shot-id", "s01", "--input-image", "first.png",
            "--prompt-file", "motion.txt", "--profile", "Fast720Seven", "--seed", "1",
        ])
        with patch.dict("os.environ", {"MUZHI_H3_V2_RUNNER": ""}):
            context = adapter._context(args)
        self.assertEqual(context["runner"], runner.resolve())


if __name__ == "__main__":
    unittest.main()
