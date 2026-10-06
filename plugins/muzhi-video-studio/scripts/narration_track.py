"""Prepare a copy of a recorded WAV and bind a reviewed SRT to its final samples.

The preparation and cut steps do not recognize speech or decide whether a take
is a mistake. Optional offline ASR yields a draft for manual SRT correction.
Every cut is specified in source sample coordinates and reviewed before render.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any


LOCK = "artifacts/narration-lock.json"
AUDIO_CONFIRMATION = "artifacts/narration-audio-confirmation.json"
TIMECODE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})$")
REASONS = {"clear_retake", "clear_mistake", "overlong_silence"}


class NarrationError(ValueError):
    pass


def local(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise NarrationError("path must be relative to this project")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_symlink():
        raise NarrationError("path escapes project or is a symlink")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_sha(left: Any, right: Any) -> bool:
    return (isinstance(left, str) and isinstance(right, str) and
            re.fullmatch(r"[0-9a-fA-F]{64}", left) is not None and
            re.fullmatch(r"[0-9a-fA-F]{64}", right) is not None and
            left.lower() == right.lower())


def checked(root: Path, relative: str, sha: str) -> Path:
    path = local(root, relative)
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise NarrationError(f"invalid SHA-256 value: {relative}")
    if not path.is_file() or digest(path).lower() != sha.lower():
        raise NarrationError(f"missing or changed file: {relative}")
    return path


def read_json(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads(local(root, relative).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise NarrationError(f"expected object: {relative}")
    return value


def wav(path: Path) -> tuple[wave._wave_params, bytes]:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise NarrationError("source must be uncompressed PCM WAV")
            return source.getparams(), source.readframes(source.getnframes())
    except wave.Error as exc:
        raise NarrationError("unsupported WAV container on this Python; prepare a standard PCM16 copy and preserve the original") from exc


def plan_inputs(root: Path, plan: dict[str, Any]) -> tuple[Path, Path, wave._wave_params, bytes, list[dict[str, Any]]]:
    if plan.get("schema_version") != 1:
        raise NarrationError("edit plan schema_version 1 required")
    original = checked(root, plan.get("original_wav"), plan.get("original_sha256"))
    script = checked(root, plan.get("approved_script"), plan.get("approved_script_sha256"))
    if plan.get("source_recording") is not None:
        source = checked(root, plan.get("source_recording"), plan.get("source_recording_sha256"))
        receipt_path = checked(root, plan.get("decode_receipt"), plan.get("decode_receipt_sha256"))
        decoded = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        if (decoded.get("source_recording") != plan.get("source_recording") or
                decoded.get("source_recording_sha256") != digest(source) or
                decoded.get("decoded_wav") != plan.get("original_wav") or
                decoded.get("decoded_wav_sha256") != digest(original)):
            raise NarrationError("decoded WAV provenance differs from original recording")
    params, data = wav(original)
    if plan.get("unresolved_spoken_differences"):
        raise NarrationError("ambiguous spoken differences need a human decision before cutting")
    cuts = plan.get("cuts")
    if not isinstance(cuts, list):
        raise NarrationError("cuts must be an explicit list, including []")
    previous = 0
    for cut in cuts:
        if not isinstance(cut, dict) or cut.get("reason") not in REASONS or cut.get("reviewed") is not True:
            raise NarrationError("every cut needs a permitted reason and reviewed=true")
        start, end = cut.get("start_sample"), cut.get("end_sample")
        if type(start) is not int or type(end) is not int or start < previous or end <= start or end > params.nframes:
            raise NarrationError("cuts must use ordered, nonoverlapping source sample ranges")
        previous = end
    return original, script, params, data, cuts


def decode_local(root: Path, source_path: str, source_sha256: str, output_path: str) -> dict[str, Any]:
    source = checked(root, source_path, source_sha256)
    if source.suffix.lower() != ".m4a":
        raise NarrationError("decode-local currently accepts an original M4A recording")
    output = local(root, output_path)
    if output.suffix.lower() != ".wav" or output.exists():
        raise NarrationError("decoded output must be a new WAV path")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise NarrationError("existing local ffmpeg executable is unavailable")
    output.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n",
                              "-i", str(source), "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", str(output)],
                             capture_output=True, text=True, timeout=300, check=False)
    if process.returncode != 0 or not output.is_file():
        raise NarrationError("local FFmpeg decode failed: " + process.stderr[-1000:])
    params, _ = wav(output)
    receipt = {"source_recording": source_path, "source_recording_sha256": digest(source),
               "decoded_wav": output_path, "decoded_wav_sha256": digest(output),
               "sample_rate": params.framerate, "channels": params.nchannels,
               "samples": params.nframes, "method": "existing_local_ffmpeg_pcm_s16le"}
    local(root, output_path + ".decode-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def verify_receipt(root: Path, receipt: dict[str, Any]) -> None:
    plan_path = checked(root, receipt.get("edit_plan"), receipt.get("edit_plan_sha256"))
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    original, script, params, data, cuts = plan_inputs(root, plan)
    candidate = checked(root, receipt.get("candidate_wav"), receipt.get("candidate_sha256"))
    candidate_params, candidate_data = wav(candidate)
    if (candidate_params.nchannels, candidate_params.sampwidth, candidate_params.framerate) != (
            params.nchannels, params.sampwidth, params.framerate):
        raise NarrationError("candidate WAV format differs from original")
    width = params.nchannels * params.sampwidth
    expected = bytearray()
    cursor = 0
    for cut in [*cuts, {"start_sample": params.nframes, "end_sample": params.nframes}]:
        expected.extend(data[cursor * width:cut["start_sample"] * width])
        cursor = cut["end_sample"]
    if (candidate_data != expected or receipt.get("final_samples") != candidate_params.nframes or
            receipt.get("original_sha256") != digest(original) or
            receipt.get("approved_script_sha256") != digest(script) or receipt.get("cuts") != cuts):
        raise NarrationError("candidate samples or receipt differ from the reviewed cut plan")


def prepare(root: Path, plan_path: str, candidate_path: str) -> dict[str, Any]:
    plan = read_json(root, plan_path)
    original, script, params, data, cuts = plan_inputs(root, plan)
    destination = local(root, candidate_path)
    if destination.exists() or destination == original:
        raise NarrationError("candidate must be a new file; original and existing output are protected")
    width = params.sampwidth * params.nchannels
    spans = []
    kept = bytearray()
    cursor = output_cursor = 0
    for cut in [*cuts, {"start_sample": params.nframes, "end_sample": params.nframes}]:
        start = cut["start_sample"]
        if start > cursor:
            kept.extend(data[cursor * width:start * width])
            spans.append({"source_start_sample": cursor, "source_end_sample": start,
                          "final_start_sample": output_cursor, "final_end_sample": output_cursor + start - cursor})
            output_cursor += start - cursor
        cursor = cut["end_sample"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as target:
        target.setparams(params)
        target.writeframes(bytes(kept))
    receipt = {"schema_version": 1, "edit_plan": plan_path, "edit_plan_sha256": digest(local(root, plan_path)),
               "original_wav": plan["original_wav"], "original_sha256": digest(original),
               "approved_script": plan["approved_script"], "approved_script_sha256": digest(script),
               "candidate_wav": candidate_path, "candidate_sha256": digest(destination),
               "sample_rate": params.framerate, "source_samples": params.nframes,
               "final_samples": output_cursor, "kept_spans": spans, "cuts": cuts,
               "status": "awaiting_listen_and_srt_review"}
    receipt_path = local(root, candidate_path + ".receipt.json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def srt_cues(path: Path) -> tuple[list[tuple[int, int, str]], str]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = [part.strip().splitlines() for part in re.split(r"\r?\n\s*\r?\n", text) if part.strip()]
    cues = []
    last_end = 0
    for i, lines in enumerate(blocks, 1):
        if len(lines) < 3 or lines[0].strip() != str(i):
            raise NarrationError("SRT cues must be numbered consecutively with text")
        match = TIMECODE.fullmatch(lines[1].strip())
        if not match:
            raise NarrationError("invalid SRT timecode")
        numbers = [int(value) for value in match.groups()]
        start = ((numbers[0] * 60 + numbers[1]) * 60 + numbers[2]) * 1000 + numbers[3]
        end = ((numbers[4] * 60 + numbers[5]) * 60 + numbers[6]) * 1000 + numbers[7]
        if start < last_end or end <= start or not "".join(lines[2:]).strip():
            raise NarrationError("SRT cues overlap, are empty or have invalid duration")
        last_end = end
        cues.append((start, end, "".join(lines[2:])))
    if not cues:
        raise NarrationError("SRT has no cues")
    return cues, text


def confirm_audio(root: Path, receipt_path: str, quote: str) -> dict[str, Any]:
    if not isinstance(quote, str) or len(quote.strip()) < 8:
        raise NarrationError("the user's actual final-audio listening confirmation is required")
    receipt = read_json(root, receipt_path)
    verify_receipt(root, receipt)
    confirmation = {"schema_version": 1, "candidate_wav": receipt["candidate_wav"],
                    "candidate_sha256": receipt["candidate_sha256"], "edit_receipt": receipt_path,
                    "edit_receipt_sha256": digest(local(root, receipt_path)), "user_audio_quote": quote.strip()}
    path = local(root, AUDIO_CONFIRMATION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(confirmation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return confirmation


def verify_audio_confirmation(root: Path, receipt_path: str, receipt: dict[str, Any]) -> dict[str, Any]:
    if not local(root, AUDIO_CONFIRMATION).is_file():
        raise NarrationError("final audio needs this candidate's listening confirmation before ASR/SRT")
    confirmation = read_json(root, AUDIO_CONFIRMATION)
    if (confirmation.get("schema_version") != 1 or
            confirmation.get("candidate_wav") != receipt.get("candidate_wav") or
            confirmation.get("candidate_sha256") != receipt.get("candidate_sha256") or
            confirmation.get("edit_receipt") != receipt_path or
            confirmation.get("edit_receipt_sha256") != digest(local(root, receipt_path)) or
            len(str(confirmation.get("user_audio_quote", "")).strip()) < 8):
        raise NarrationError("final audio needs this candidate's listening confirmation before ASR/SRT")
    return confirmation


def comparison(root: Path, receipt_path: str, srt_path: str) -> dict[str, Any]:
    receipt = read_json(root, receipt_path)
    verify_receipt(root, receipt)
    audio = checked(root, receipt.get("candidate_wav"), receipt.get("candidate_sha256"))
    script = checked(root, receipt.get("approved_script"), receipt.get("approved_script_sha256"))
    cues, _ = srt_cues(local(root, srt_path))
    params, _ = wav(audio)
    duration_ms = params.nframes * 1000 / params.framerate
    if cues[-1][1] > duration_ms + 2:
        raise NarrationError("SRT ends beyond final audio samples")
    warnings = ["SRT ends over two seconds before final audio; review tail alignment"] if duration_ms - cues[-1][1] > 2000 else []
    script_text = "".join(script.read_text(encoding="utf-8-sig").split())
    cue_text = "".join("".join(cue[2].split()) for cue in cues)
    diffs = [list(part) for part in difflib.SequenceMatcher(None, script_text, cue_text, autojunk=False).get_opcodes() if part[0] != "equal"]
    identity = {"script_sha256": digest(script), "srt_sha256": digest(local(root, srt_path)),
                "audio_sha256": digest(audio), "differences": diffs}
    return {"difference_digest": hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "differences": diffs, "cue_count": len(cues), "last_cue_end_ms": cues[-1][1],
            "audio_duration_ms": duration_ms, "warnings": warnings, "audio_sha256": identity["audio_sha256"],
            "srt_sha256": identity["srt_sha256"], "script_sha256": identity["script_sha256"]}


def lock_srt(root: Path, receipt_path: str, srt_path: str, reviewed_difference_digest: str,
             audio_quote: str, srt_quote: str) -> dict[str, Any]:
    if len(audio_quote.strip()) < 8 or len(srt_quote.strip()) < 8:
        raise NarrationError("real listening and SRT review quotes are required")
    info = comparison(root, receipt_path, srt_path)
    if info["difference_digest"] != reviewed_difference_digest:
        raise NarrationError("script/SRT difference review does not match these exact files")
    receipt = read_json(root, receipt_path)
    confirmation = verify_audio_confirmation(root, receipt_path, receipt)
    checked(root, receipt.get("original_wav"), receipt.get("original_sha256"))
    checked(root, receipt.get("edit_plan"), receipt.get("edit_plan_sha256"))
    lock = {"schema_version": 1, "original_wav": receipt["original_wav"],
            "original_sha256": receipt["original_sha256"], "edit_plan": receipt["edit_plan"],
            "edit_plan_sha256": receipt["edit_plan_sha256"], "final_audio": receipt["candidate_wav"],
            "edit_receipt_sha256": digest(local(root, receipt_path)),
            "final_audio_sha256": info["audio_sha256"], "approved_script": receipt["approved_script"],
            "approved_script_sha256": info["script_sha256"], "final_srt": srt_path,
            "final_srt_sha256": info["srt_sha256"], "difference_digest": info["difference_digest"],
            "audio_listen_quote": confirmation["user_audio_quote"], "srt_review_quote": srt_quote.strip(),
            "audio_confirmation_sha256": digest(local(root, AUDIO_CONFIRMATION)),
            "srt_alignment_warnings_reviewed": info["warnings"],
            "final_samples": receipt["final_samples"], "sample_rate": receipt["sample_rate"]}
    plan = read_json(root, receipt["edit_plan"])
    if plan.get("source_recording") is not None:
        lock.update({key: plan[key] for key in ("source_recording", "source_recording_sha256",
                                                 "decode_receipt", "decode_receipt_sha256")})
    if audio_quote.strip() != confirmation["user_audio_quote"]:
        raise NarrationError("audio quote differs from the earlier confirmed candidate")
    path = local(root, LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lock


def verify_lock(root: Path, plan: dict[str, Any]) -> list[str]:
    try:
        lock = read_json(root, LOCK)
        if lock.get("schema_version") != 1:
            raise NarrationError("narration lock version missing")
        for path_key, hash_key in (("original_wav", "original_sha256"), ("edit_plan", "edit_plan_sha256"),
                                   ("final_audio", "final_audio_sha256"), ("approved_script", "approved_script_sha256"),
                                   ("final_srt", "final_srt_sha256")):
            checked(root, lock.get(path_key), lock.get(hash_key))
        if lock.get("source_recording") is not None:
            checked(root, lock.get("source_recording"), lock.get("source_recording_sha256"))
            checked(root, lock.get("decode_receipt"), lock.get("decode_receipt_sha256"))
        checked(root, lock["final_audio"] + ".receipt.json", lock.get("edit_receipt_sha256"))
        checked(root, AUDIO_CONFIRMATION, lock.get("audio_confirmation_sha256"))
        confirmation = verify_audio_confirmation(root, lock["final_audio"] + ".receipt.json",
                                                read_json(root, lock["final_audio"] + ".receipt.json"))
        if confirmation.get("user_audio_quote") != lock.get("audio_listen_quote"):
            raise NarrationError("final audio listening confirmation changed")
        if (plan.get("source_script") != lock.get("approved_script") or
                not same_sha(plan.get("source_sha256"), lock.get("approved_script_sha256")) or
                plan.get("audio_source") != lock.get("final_audio") or
                not same_sha(plan.get("audio_sha256"), lock.get("final_audio_sha256")) or
                plan.get("srt_source") != lock.get("final_srt") or
                not same_sha(plan.get("srt_sha256"), lock.get("final_srt_sha256"))):
            raise NarrationError("motion plan differs from confirmed final audio/SRT/script")
        info = comparison(root, lock["final_audio"] + ".receipt.json", lock["final_srt"])
        if info["difference_digest"] != lock.get("difference_digest"):
            raise NarrationError("SRT/script comparison changed")
        if len(str(lock.get("audio_listen_quote", "")).strip()) < 8 or len(str(lock.get("srt_review_quote", "")).strip()) < 8:
            raise NarrationError("audio or SRT review missing")
        return []
    except (NarrationError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [str(exc)]


def asr_status(model_dir: str) -> dict[str, Any]:
    model = Path(model_dir).resolve()
    needed = ("config.json", "model.bin", "tokenizer.json")
    files_ready = Path(model_dir).is_absolute() and model.is_dir() and all((model / name).is_file() for name in needed)
    dependency_ready = importlib.util.find_spec("faster_whisper") is not None
    return {"ready": files_ready and dependency_ready,
            "local_model_dir": str(model),
            "model_files_present": files_ready, "faster_whisper_present": dependency_ready,
            "offline_only": True, "model_load_verified": False, "transcription_claimed": False}


def transcribe_local(root: Path, candidate: str, output_dir: str, model_dir: str) -> dict[str, Any]:
    readiness = asr_status(model_dir)
    if not readiness["ready"]:
        raise NarrationError("local transcriber/model is unavailable; no model download is allowed")
    receipt_path = candidate + ".receipt.json"
    receipt = read_json(root, receipt_path)
    if receipt.get("candidate_wav") != candidate:
        raise NarrationError("candidate does not match its preparation receipt")
    verify_receipt(root, receipt)
    verify_audio_confirmation(root, receipt_path, receipt)
    audio = checked(root, candidate, receipt["candidate_sha256"])
    destination = local(root, output_dir)
    if destination.exists():
        raise NarrationError("ASR output directory must be new to preserve previous transcript")
    # Only a caller-supplied, already present local model directory is used.
    # The optional package is imported after that check and forced offline.
    previous = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(readiness["local_model_dir"], device="cpu", compute_type="int8")
        segments_iter, info = model.transcribe(str(audio), language="zh", word_timestamps=True, vad_filter=True)
        segments = []
        words = []
        for segment in segments_iter:
            segment_words = [{"word": word.word, "start": round(word.start, 3),
                              "end": round(word.end, 3), "probability": round(word.probability, 3)}
                             for word in (segment.words or [])]
            words.extend(segment_words)
            segments.append({"id": segment.id, "start": round(segment.start, 3),
                             "end": round(segment.end, 3), "text": segment.text.strip(), "words": segment_words})
    except Exception as exc:
        raise NarrationError("offline local transcription failed: " + str(exc)) from exc
    finally:
        if previous is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous
    destination.mkdir(parents=True, exist_ok=False)
    transcript = destination / (audio.stem + "_transcript.json")
    transcript.write_text(json.dumps({"segments": segments, "word_timestamps": words, "language": "zh",
                                      "duration_seconds": round(info.duration, 3), "model_dir": readiness["local_model_dir"],
                                      "device": "cpu"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"candidate_wav": candidate, "candidate_sha256": digest(audio),
              "transcript_json": transcript.relative_to(root).as_posix(),
              "transcript_sha256": digest(transcript), "local_model_dir": readiness["local_model_dir"],
              "word_timestamps_present": bool(words),
              "needs_manual_script_and_srt_review": True}
    (destination / "narration-asr-receipt.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("decode-local", "prepare", "confirm-audio", "asr-status", "transcribe-local", "compare", "lock-srt", "verify"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--edit-plan")
    parser.add_argument("--candidate")
    parser.add_argument("--receipt")
    parser.add_argument("--srt")
    parser.add_argument("--difference-digest")
    parser.add_argument("--audio-quote")
    parser.add_argument("--srt-quote")
    parser.add_argument("--motion-plan", default="motion-plan.json")
    parser.add_argument("--model-dir")
    parser.add_argument("--out-dir")
    parser.add_argument("--source")
    parser.add_argument("--source-sha256")
    parser.add_argument("--wav-output")
    parser.add_argument("--user-quote")
    args = parser.parse_args()
    root = Path(args.project).resolve()
    try:
        if args.command == "decode-local":
            result = decode_local(root, args.source, args.source_sha256, args.wav_output)
        elif args.command == "prepare":
            result = prepare(root, args.edit_plan, args.candidate)
        elif args.command == "confirm-audio":
            result = confirm_audio(root, args.receipt, args.user_quote)
        elif args.command == "asr-status":
            result = asr_status(args.model_dir)
        elif args.command == "transcribe-local":
            result = transcribe_local(root, args.candidate, args.out_dir, args.model_dir)
        elif args.command == "compare":
            result = comparison(root, args.receipt, args.srt)
        elif args.command == "lock-srt":
            result = lock_srt(root, args.receipt, args.srt, args.difference_digest, args.audio_quote, args.srt_quote)
        else:
            result = {"passed": not (errors := verify_lock(root, read_json(root, args.motion_plan))), "errors": errors}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("passed", True) else 2
    except (NarrationError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
