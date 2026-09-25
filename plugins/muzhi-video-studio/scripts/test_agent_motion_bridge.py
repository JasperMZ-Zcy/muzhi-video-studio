import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_motion_bridge as bridge


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project = root / "synthetic-video"
        self.project.mkdir()
        self.upstream = root / "separate-upstream"
        self.upstream.mkdir()
        for relative in bridge.PINNED_BLOBS:
            path = self.upstream / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"name": "agent-motion", "version": bridge.VERSION})
                            if relative == "package.json" else "test pinned upstream file", encoding="utf-8")
        self.pin = patch.object(bridge, "PINNED_BLOBS", {
            relative: bridge.git_blob(self.upstream / relative) for relative in bridge.PINNED_BLOBS
        })
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.case_count = patch.object(bridge, "CASE_COUNT", 1)
        self.case_count.start()
        self.addCleanup(self.case_count.stop)
        analysis = self.upstream / "reference-library" / "analysis"
        (analysis / "vanemotion").mkdir(parents=True)
        (analysis / "INDEX.md").write_text("| V01 | [case](vanemotion/V01.md) |\n", encoding="utf-8")
        (analysis / "catalog.json").write_text(json.dumps({"case_count": 1, "cases": [
            {"case_id": "V01", "report": "vanemotion/V01.md"}]}), encoding="utf-8")
        (analysis / "vanemotion" / "V01.md").write_text("synthetic analysis", encoding="utf-8")
        self.reference_pin = patch.object(bridge, "REFERENCE_TREE_DIGEST",
                                          bridge.reference_snapshot(self.upstream)[1])
        self.reference_pin.start()
        self.addCleanup(self.reference_pin.stop)
        (self.project / "artifacts").mkdir()
        (self.project / "script.txt").write_text("先比较条件", encoding="utf-8")
        (self.project / "design.md").write_text("保留本片既定画风", encoding="utf-8")
        (self.project / "speech.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n先比较条件\n", encoding="utf-8")
        (self.project / "voice.wav").write_bytes(b"RIFF" + b"synthetic original recording")
        self.segment = {
            "id": "s1", "spoken_text": "先比较条件", "audience_takeaway": "同口径比较",
            "visual_route": "native_mg", "reason": "需要看懂关系", "visual_action": "两列条件逐项对齐",
            "library_candidates": ["list-reveal"], "requires_exact_information": False,
            "evidence": [], "reading_plan": "落位后留阅读时间", "handoff": "进入下一镜",
            "motion_backend": "agent_motion",
            "reference_cases": [{"case_id": "V01",
                "source_path": "reference-library/analysis/vanemotion/V01.md",
                "source_sha256": sha(analysis / "vanemotion" / "V01.md"),
                "mechanism": "two-column relation", "srt_timecode": "00:00:00,000 --> 00:00:01,000",
                "style_adaptation": "retain established style", "visible_action": "align two columns",
                "sample_timecode_evidence": {"status": "pending"}}],
        }
        self.plan = {"source_script": "script.txt", "source_sha256": sha(self.project / "script.txt"),
                     "style_intent": "沿用本片画风", "design_source": "design.md",
                     "design_sha256": sha(self.project / "design.md"),
                     "reference_index_source": "reference-library/analysis/INDEX.md",
                     "reference_index_sha256": sha(analysis / "INDEX.md"), "segments": [self.segment]}
        self.write_plan()
        (self.project / "artifacts" / "video-studio-style.json").write_text(json.dumps({
            "schemaVersion": 1, "style": "editorial-illustration", "mode": "trial"}), encoding="utf-8")
        self.receipt = {"attestation": "user_attested", "scope": "local_use_only",
                        "upstream_commit": bridge.COMMIT, "project_root": str(self.project.resolve()),
                        "selected_backend": "agent_motion", "no_public_redistribution": True,
                        "user_quote": "作者说了随便用", "attested_at": "2026-09-26"}
        self.write_receipt()

    def write_plan(self):
        (self.project / "plan.json").write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")

    def write_receipt(self):
        (self.project / "authorization.json").write_text(json.dumps(self.receipt, ensure_ascii=False), encoding="utf-8")

    def assess(self):
        return bridge.project_status(self.project.resolve(), self.upstream.resolve(), "plan.json",
                                     "authorization.json", "speech.srt", sha(self.project / "speech.srt"),
                                     "voice.wav", sha(self.project / "voice.wav"))

    def cli(self, command):
        args = ["bridge", command, "--upstream", str(self.upstream)]
        if command != "check":
            args += ["--project", str(self.project)]
        if command == "prepare":
            args += ["--plan", "plan.json", "--receipt", "authorization.json",
                     "--srt", "speech.srt", "--srt-sha256", sha(self.project / "speech.srt"),
                     "--voice", "voice.wav", "--voice-sha256", sha(self.project / "voice.wav")]
        output = io.StringIO()
        with patch.object(sys, "argv", args), contextlib.redirect_stdout(output):
            code = bridge.main()
        return code, json.loads(output.getvalue())

    def test_prepare_readback_and_drift(self):
        self.assertEqual(self.cli("status")[1]["state"], "not_prepared")
        code, result = self.cli("prepare")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["state"], "prepared_for_manual_production")
        handoff = self.project / bridge.HANDOFF
        packet = json.loads(handoff.read_text(encoding="utf-8"))
        self.assertEqual(packet["inputs"]["original_voice"]["sha256"], sha(self.project / "voice.wav"))
        self.assertEqual(packet["agent_motion_segments"][0]["id"], "s1")
        self.assertEqual(packet["reference_index"]["indexed_cases"], 1)
        self.assertEqual(packet["agent_motion_segments"][0]["reference_cases"][0]["sample_timecode_evidence"]["status"], "pending")
        self.assertEqual(self.cli("status")[1]["state"], "prepared_readback")
        (self.project / "speech.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n内容漂移\n", encoding="utf-8")
        code, result = self.cli("status")
        self.assertEqual(code, 1)
        self.assertIn("drift", result["reason"])
        self.assertTrue(handoff.exists(), "readback must not overwrite an existing packet")

    def test_requires_authorization_and_style_lock(self):
        self.receipt["attestation"] = "unverified"
        self.write_receipt()
        with self.assertRaisesRegex(bridge.BridgeError, "authorization receipt"):
            self.assess()
        self.receipt["attestation"] = "user_attested"
        self.write_receipt()
        (self.project / "artifacts" / "video-studio-style.json").unlink()
        with self.assertRaisesRegex(bridge.BridgeError, "style lock"):
            self.assess()

    def test_trial_only_style_cannot_claim_production_in_handoff(self):
        lock = self.project / "artifacts" / "video-studio-style.json"
        lock.write_text(json.dumps({"schemaVersion": 1, "style": "trial-style", "mode": "production"}), encoding="utf-8")
        with patch.object(bridge.style_registry, "catalog", return_value=({}, {"trial-style": {"status": "trial_only"}})):
            with self.assertRaisesRegex(bridge.style_registry.StyleError, "trial-only"):
                self.assess()

    def test_srt_timecode_must_be_real_cue_line_with_valid_clock(self):
        srt = self.project / "speech.srt"
        srt.write_text("1\n00:00:60,000 --> 00:00:61,000\n先比较条件\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.BridgeError, "below 60"):
            self.assess()
        srt.write_text("1\n字幕里提到 00:00:00,000 --> 00:00:01,000 而非真正时码\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.BridgeError, "cue needs"):
            self.assess()
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n先比较条件\n00:00:01,000 --> 00:00:02,000\n", encoding="utf-8")
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:01,000 --> 00:00:02,000"
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "interval outside bound cues"):
            self.assess()
        srt.write_text("1\n00:00:01,000 --> 00:00:00,000\n先比较条件\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.BridgeError, "cue end must follow"):
            self.assess()
        srt.write_text("1\n00:00:02,000 --> 00:00:03,000\n先比较\n\n"
                       "2\n00:00:00,000 --> 00:00:01,000\n再看结论\n", encoding="utf-8")
        with self.assertRaisesRegex(bridge.BridgeError, "time order"):
            self.assess()

    def test_path_escape_and_wrong_hash(self):
        with self.assertRaisesRegex(bridge.BridgeError, "stay inside"):
            bridge.project_status(self.project.resolve(), self.upstream.resolve(), "../plan.json",
                                  "authorization.json", "speech.srt", sha(self.project / "speech.srt"),
                                  "voice.wav", sha(self.project / "voice.wav"))
        with self.assertRaisesRegex(bridge.BridgeError, "SHA-256 drift"):
            bridge.project_status(self.project.resolve(), self.upstream.resolve(), "plan.json",
                                  "authorization.json", "speech.srt", "0" * 64,
                                  "voice.wav", sha(self.project / "voice.wav"))

    def test_image_to_video_never_replaced(self):
        self.segment.update(visual_route="image_to_video", generation_action="原渠道生成动作",
                            library_candidates=[])
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "cannot replace"):
            self.assess()

    def test_hybrid_preserves_separate_image_to_video_scope(self):
        self.segment.update(visual_route="hybrid", responsibilities="本地关系动效与原渠道人物动作分工",
                            uses_image_to_video=True, generation_action="保留 H3 原渠道动作",
                            agent_motion_scope="仅本地关系箭头", image_to_video_scope="仅人物动作")
        self.write_plan()
        packet = self.assess()
        selected = packet["agent_motion_segments"][0]
        self.assertEqual(selected["agent_motion_scope"], "仅本地关系箭头")
        self.assertEqual(selected["excluded_image_to_video_scope"], "仅人物动作")
        self.assertEqual(selected["existing_generation_action_preserved"], "保留 H3 原渠道动作")
        self.segment["image_to_video_scope"] = "仅本地关系箭头"
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "distinct image_to_video_scope"):
            self.assess()

    def test_no_implicit_selection_or_overwrite(self):
        del self.segment["motion_backend"]
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "no segment explicitly"):
            self.assess()
        self.segment["motion_backend"] = "agent_motion"
        self.write_plan()
        self.assertEqual(self.cli("prepare")[0], 0)
        code, result = self.cli("prepare")
        self.assertEqual(code, 1)
        self.assertIn("already exists", result["reason"])

    def test_prepare_rejects_artifacts_junction(self):
        artifacts = (self.project / "artifacts").resolve()
        original = getattr(Path, "is_junction", lambda self: False)

        def reported_junction(candidate):
            return candidate == artifacts or original(candidate)

        with patch.object(Path, "is_junction", new=reported_junction, create=True):
            code, result = self.cli("prepare")
        self.assertEqual(code, 1)
        self.assertIn("artifacts", result["reason"])
        self.assertFalse((self.project / bridge.HANDOFF).exists())

    def test_reference_case_and_srt_timecode_are_bound(self):
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:03,000 --> 00:00:04,000"
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "interval outside bound cues"):
            self.assess()
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:00,000 --> 00:00:01,000"
        self.segment["reference_cases"][0]["sample_timecode_evidence"] = {"status": "observed"}
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "only pending"):
            self.assess()
        self.segment["reference_cases"][0]["sample_timecode_evidence"] = {"status": "pending"}
        self.segment["reference_cases"][0]["source_sha256"] = "0" * 64
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "page missing or SHA-256 drift"):
            self.assess()

    def test_reference_tree_drift_rejected_even_if_plan_updates_page_hash(self):
        page = self.upstream / "reference-library" / "analysis" / "vanemotion" / "V01.md"
        page.write_text("altered analysis", encoding="utf-8")
        self.segment["reference_cases"][0]["source_sha256"] = sha(page)
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "pinned reference-library snapshot drift"):
            self.assess()

    def test_reference_interval_can_span_complete_consecutive_srt_cues(self):
        (self.project / "speech.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n先比较条件\n\n"
            "2\n00:00:01,000 --> 00:00:03,000\n再看结论\n", encoding="utf-8")
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:00,000 --> 00:00:03,000"
        self.write_plan()
        self.assertEqual(self.assess()["agent_motion_segments"][0]["reference_cases"][0]["srt_timecode"],
                         "00:00:00,000 --> 00:00:03,000")
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:00,000 --> 00:00:04,000"
        self.write_plan()
        with self.assertRaisesRegex(bridge.BridgeError, "interval outside bound cues"):
            self.assess()

    def test_srt_common_crlf_and_multiline_subtitle_remain_supported(self):
        (self.project / "speech.srt").write_bytes(
            "1\r\n00:00:00,000 --> 00:00:01,000\r\n先比较\r\n条件\r\n\r\n"
            "2\r\n00:00:01,000 --> 00:00:03,000\r\n再看结论\r\n".encode("utf-8"))
        self.segment["reference_cases"][0]["srt_timecode"] = "00:00:00,000 --> 00:00:03,000"
        self.write_plan()
        self.assertEqual(len(bridge.srt_cues((self.project / "speech.srt").read_text(encoding="utf-8"))), 2)
        self.assertEqual(self.assess()["agent_motion_segments"][0]["reference_cases"][0]["srt_timecode"],
                         "00:00:00,000 --> 00:00:03,000")


if __name__ == "__main__":
    unittest.main()
