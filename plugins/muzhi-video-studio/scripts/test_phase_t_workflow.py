"""Synthetic sample and project-choice checks for the two-entry workflow."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import code_music
import music_method
import narration_track
import provider_router
import production_runner
from generation_ledger import ValidationError, reserve


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseTWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def original(self) -> Path:
        path = self.root / "audio/original.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(1000)
            output.writeframes(b"".join(round(12000 * math.sin(i / 10)).to_bytes(2, "little", signed=True)
                                         for i in range(1000)))
        return path

    def edit_plan(self, unresolved=None) -> Path:
        source = self.original()
        script = self.write("script.txt", "你好世界")
        payload = {"schema_version": 1, "original_wav": "audio/original.wav", "original_sha256": sha(source),
                   "approved_script": "script.txt", "approved_script_sha256": sha(script),
                   "unresolved_spoken_differences": unresolved or [],
                   "cuts": [{"start_sample": 200, "end_sample": 400, "reason": "clear_retake", "reviewed": True}]}
        return self.write("artifacts/narration-edit-plan.json", json.dumps(payload, ensure_ascii=False))

    def test_narration_cut_and_lock_use_final_samples_and_exact_files(self) -> None:
        self.edit_plan()
        result = narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        self.assertEqual(result["source_samples"], 1000)
        self.assertEqual(result["final_samples"], 800)
        self.assertEqual(result["kept_spans"][1], {"source_start_sample": 400, "source_end_sample": 1000,
                                                   "final_start_sample": 200, "final_end_sample": 800})
        self.assertEqual(sha(self.root / "audio/original.wav"), result["original_sha256"])
        self.write("captions.srt", "1\n00:00:00,000 --> 00:00:00,700\n你好世界\n")
        info = narration_track.comparison(self.root, "audio/candidate.wav.receipt.json", "captions.srt")
        self.assertEqual(info["audio_duration_ms"], 800)
        self.assertEqual(info["differences"], [])
        narration_track.confirm_audio(self.root, "audio/candidate.wav.receipt.json", "我已完整试听这版候选音轨")
        with self.assertRaises(narration_track.NarrationError):
            narration_track.lock_srt(self.root, "audio/candidate.wav.receipt.json", "captions.srt", "wrong",
                                     "我已完整试听这版候选音轨", "我逐句核对了字幕和时码")
        narration_track.lock_srt(self.root, "audio/candidate.wav.receipt.json", "captions.srt",
                                 info["difference_digest"], "我已完整试听这版候选音轨", "我逐句核对了字幕和时码")
        plan = {"source_script": "script.txt", "source_sha256": sha(self.root / "script.txt"),
                "audio_source": "audio/candidate.wav", "audio_sha256": sha(self.root / "audio/candidate.wav"),
                "srt_source": "captions.srt", "srt_sha256": sha(self.root / "captions.srt")}
        self.assertEqual(narration_track.verify_lock(self.root, plan), [])
        for key in ("source_sha256", "audio_sha256", "srt_sha256"):
            plan[key] = plan[key].upper()
        self.assertEqual(narration_track.verify_lock(self.root, plan), [])
        plan["srt_sha256"] = "0" * 64
        self.assertTrue(narration_track.verify_lock(self.root, plan))
        plan["srt_sha256"] = sha(self.root / "captions.srt")
        candidate = self.root / "audio/candidate.wav"
        original_bytes = candidate.read_bytes()
        candidate.write_bytes(original_bytes[:-2] + b"\x00\x00")
        self.assertTrue(narration_track.verify_lock(self.root, plan))

    def test_ambiguous_edit_and_out_of_bounds_srt_are_rejected(self) -> None:
        self.edit_plan(["这一句可能是改稿，不确定是否删"])
        with self.assertRaises(narration_track.NarrationError):
            narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        plan = json.loads((self.root / "artifacts/narration-edit-plan.json").read_text(encoding="utf-8"))
        plan["unresolved_spoken_differences"] = []
        self.write("artifacts/narration-edit-plan.json", json.dumps(plan, ensure_ascii=False))
        narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        self.write("bad.srt", "1\n00:00:00,100 --> 00:00:00,900\n你好世界\n")
        with self.assertRaises(narration_track.NarrationError):
            narration_track.comparison(self.root, "audio/candidate.wav.receipt.json", "bad.srt")

    def test_asr_cannot_start_before_exact_candidate_audio_confirmation(self) -> None:
        self.edit_plan()
        narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        with patch("narration_track.asr_status", return_value={"ready": True, "local_model_dir": "local-fixture"}):
            with self.assertRaisesRegex(narration_track.NarrationError, "listening confirmation"):
                narration_track.transcribe_local(self.root, "audio/candidate.wav", "artifacts/asr-v1", "unused")

    def test_long_tail_is_flagged_for_review_but_not_assumed_wrong(self) -> None:
        original = self.original()
        with wave.open(str(original), "rb") as source:
            params, frames = source.getparams(), source.readframes(source.getnframes())
        with wave.open(str(original), "wb") as output:
            output.setparams(params)
            output.writeframes(frames + b"\x00\x00" * 3000)
        script = self.write("script.txt", "你好世界")
        plan = {"schema_version": 1, "original_wav": "audio/original.wav", "original_sha256": sha(original),
                "approved_script": "script.txt", "approved_script_sha256": sha(script),
                "unresolved_spoken_differences": [], "cuts": []}
        self.write("artifacts/narration-edit-plan.json", json.dumps(plan, ensure_ascii=False))
        narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        self.write("captions.srt", "1\n00:00:00,000 --> 00:00:00,700\n你好世界\n")
        info = narration_track.comparison(self.root, "audio/candidate.wav.receipt.json", "captions.srt")
        self.assertTrue(info["warnings"])
        narration_track.confirm_audio(self.root, "audio/candidate.wav.receipt.json", "我已完整试听这版候选音轨")
        locked = narration_track.lock_srt(self.root, "audio/candidate.wav.receipt.json", "captions.srt",
                                          info["difference_digest"], "我已完整试听这版候选音轨", "我已核对尾部停顿和字幕时码")
        self.assertEqual(locked["srt_alignment_warnings_reviewed"], info["warnings"])

    def test_new_film_has_no_h3_default_and_music_needs_selection(self) -> None:
        self.assertTrue(provider_router.validate_new_film_choice(self.root))
        self.assertTrue(provider_router.status(self.root)["needs_user_choice"])
        self.assertFalse(music_method.status(self.root)["selected"])
        music_method.select(self.root, "none", "本片不配乐")
        self.assertEqual(music_method.status(self.root)["method"], "none")
        provider_router.select_provider(self.root, "local-h3", "本片明确选择本地H3")
        self.assertEqual(provider_router.validate_new_film_choice(self.root, "local-h3"), [])
        self.assertTrue(provider_router.validate_new_film_choice(self.root, "wan"))

    def test_asr_status_refuses_missing_local_model_without_running_asr(self) -> None:
        result = narration_track.asr_status(str(self.root / "missing-model"))
        self.assertFalse(result["ready"])
        self.assertFalse(result["transcription_claimed"])

    def test_local_m4a_decode_preserves_recording_and_binds_pcm_copy(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("local ffmpeg unavailable")
        source_wav = self.root / "audio/test-source.wav"
        source_wav.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(source_wav), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(b"".join(round(6000 * math.sin(i / 30)).to_bytes(2, "little", signed=True)
                                         for i in range(9600)))
        m4a = self.root / "audio/original.m4a"
        subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source_wav),
                        "-c:a", "aac", "-b:a", "96k", str(m4a)], check=True)
        original_sha = sha(m4a)
        with self.assertRaises(narration_track.NarrationError):
            narration_track.decode_local(self.root, "audio/original.m4a", "0" * 64, "audio/wrong.wav")
        decoded = narration_track.decode_local(self.root, "audio/original.m4a", original_sha.upper(), "audio/decoded.wav")
        self.assertEqual(sha(m4a), original_sha)
        self.assertEqual(decoded["decoded_wav_sha256"], sha(self.root / "audio/decoded.wav"))
        wav_header = (self.root / "audio/decoded.wav").read_bytes()[:44]
        self.assertEqual(wav_header[:4], b"RIFF")
        self.assertEqual(wav_header[8:12], b"WAVE")
        self.assertEqual(wav_header[12:16], b"fmt ")
        self.assertEqual(wav_header[20:22], b"\x01\x00")  # standard PCM, not WAVE_FORMAT_EXTENSIBLE
        script = self.write("script.txt", "测试声音")
        plan = {"schema_version": 1, "original_wav": "audio/decoded.wav", "original_sha256": decoded["decoded_wav_sha256"],
                "source_recording": "audio/original.m4a", "source_recording_sha256": original_sha.upper(),
                "decode_receipt": "audio/decoded.wav.decode-receipt.json",
                "decode_receipt_sha256": sha(self.root / "audio/decoded.wav.decode-receipt.json"),
                "approved_script": "script.txt", "approved_script_sha256": sha(script),
                "unresolved_spoken_differences": [], "cuts": []}
        self.write("artifacts/narration-edit-plan.json", json.dumps(plan, ensure_ascii=False))
        self.assertGreater(narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
                           ["final_samples"], 0)

    def test_authored_score_changes_audio_and_has_no_default_tune(self) -> None:
        music_method.select(self.root, "code_local", "这条片用本机代码配乐")
        score = {"schema_version": 1, "bpm": 96, "total_beats": 4, "tail_seconds": 0.2,
                 "sections": [{"name": "opening", "start_beat": 0, "end_beat": 2, "gain": 0.7},
                              {"name": "answer", "start_beat": 2, "end_beat": 4, "gain": 0.9}],
                 "events": [{"start_beat": 0, "duration_beats": 1, "note": "C4", "timbre": "warm_keys", "level": 0.6},
                            {"start_beat": 2, "duration_beats": 1, "note": "G4", "timbre": "soft_pad", "level": 0.5}]}
        self.write("score-a.json", json.dumps(score))
        first = code_music.render(self.root, "score-a.json", "music/a.wav")
        score["events"][1]["note"] = "A4"
        self.write("score-b.json", json.dumps(score))
        second = code_music.render(self.root, "score-b.json", "music/b.wav")
        self.assertNotEqual(first["output_sha256"], second["output_sha256"])
        with wave.open(str(self.root / "music/a.wav"), "rb") as audio:
            self.assertEqual(audio.getframerate(), 48000)
            self.assertEqual(audio.getnframes(), round((4 * 60 / 96 + 0.2) * 48000))

    def test_new_studio_batch_requires_locked_audio_music_and_generated_route_choice(self) -> None:
        self.edit_plan()
        narration_track.prepare(self.root, "artifacts/narration-edit-plan.json", "audio/candidate.wav")
        self.write("captions.srt", "1\n00:00:00,000 --> 00:00:00,700\n你好世界\n")
        info = narration_track.comparison(self.root, "audio/candidate.wav.receipt.json", "captions.srt")
        narration_track.confirm_audio(self.root, "audio/candidate.wav.receipt.json", "我已完整试听这版候选音轨")
        narration_track.lock_srt(self.root, "audio/candidate.wav.receipt.json", "captions.srt",
                                 info["difference_digest"], "我已完整试听这版候选音轨", "我逐句核对了字幕和时码")
        plan = {"source_script": "script.txt", "source_sha256": sha(self.root / "script.txt"),
                "audio_source": "audio/candidate.wav", "audio_sha256": sha(self.root / "audio/candidate.wav"),
                "srt_source": "captions.srt", "srt_sha256": sha(self.root / "captions.srt"),
                "timebase_kind": "real_voice_srt", "segments": [{"id": "S01", "visual_route": "hybrid",
                "uses_image_to_video": True, "preview_binding": {"preview_media": {"path": "clip.mp4"}}}]}
        self.write("motion-plan.json", json.dumps(plan, ensure_ascii=False))
        self.write("artifacts/director-storyboard.json", json.dumps({"motion_plan_source": "motion-plan.json",
                  "motion_plan_sha256": sha(self.root / "motion-plan.json"), "approval": {"status": "approved"}}))
        with patch("motion_plan.validate", return_value={"passed": True, "errors": []}), patch(
                "production_runner.validate_director_review", return_value={"passed": True, "errors": []}):
            result = production_runner.check_stage(self.root, "batch", "studio")
            self.assertTrue(any("music method" in issue for issue in result["errors"]))
            self.assertTrue(any("provider" in issue for issue in result["errors"]))
            music_method.select(self.root, "none", "本片不配乐")
            music_state = self.root / music_method.RELATIVE
            valid_music = music_state.read_bytes()
            music_state.write_text(json.dumps({"schema_version": 1, "selection": {}}), encoding="utf-8")
            self.assertTrue(any("music method" in issue for issue in production_runner.check_stage(
                self.root, "batch", "studio")["errors"]))
            music_state.write_bytes(valid_music)
            self.assertTrue(any("provider" in issue for issue in production_runner.check_stage(
                self.root, "batch", "studio")["errors"]))
            with patch("director_review_gate.validate", return_value={"passed": True, "errors": []}):
                with self.assertRaisesRegex(ValidationError, "provider selection"):
                    reserve(self.root, "video", "S01", ["script.txt"], "local-h3", "fixture", "0", "0", "none", "本片零费测试")
            provider_router.select_provider(self.root, "local-h3", "本片明确选择本地H3")
            self.assertTrue(production_runner.check_stage(self.root, "batch", "studio")["passed"])
            with patch("director_review_gate.validate", return_value={"passed": True, "errors": []}):
                booked = reserve(self.root, "video", "S01", ["script.txt"], "local-h3", "fixture", "0", "0", "none", "本片零费测试")
            self.assertEqual(booked["reservation"]["kind"], "video")
            provider_state = self.root / provider_router.STATE_RELATIVE
            valid_provider = provider_state.read_bytes()
            provider_state.write_text("not json", encoding="utf-8")
            self.assertTrue(any("video provider" in issue for issue in production_runner.check_stage(
                self.root, "batch", "studio")["errors"]))
            with patch("director_review_gate.validate", return_value={"passed": True, "errors": []}):
                with self.assertRaisesRegex(ValidationError, "provider selection"):
                    reserve(self.root, "video", "S02", ["script.txt"], "local-h3", "fixture", "0", "0", "none", "本片零费测试")
            provider_state.write_bytes(valid_provider)
            plan["segments"][0]["visual_route"] = "native_mg"
            plan["segments"][0]["uses_image_to_video"] = False
            self.write("motion-plan.json", json.dumps(plan, ensure_ascii=False))
            board = {"motion_plan_source": "motion-plan.json", "motion_plan_sha256": sha(self.root / "motion-plan.json"),
                     "approval": {"status": "approved"}}
            self.write("artifacts/director-storyboard.json", json.dumps(board))
            provider_state.unlink()
            self.assertTrue(production_runner.check_stage(self.root, "batch", "studio")["passed"])


if __name__ == "__main__":
    unittest.main()
