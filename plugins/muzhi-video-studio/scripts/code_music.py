"""Render an authored project score with simple local procedural timbres.

The score supplies every note, beat, section and timbre choice. This script is
not an automatic composer and does not imitate sampled acoustic instruments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import wave
from array import array
from pathlib import Path
from typing import Any

from music_method import status


RATE = 48_000
TIMBRES = {
    "pure": ((1.0, 1.0),),
    "warm_keys": ((1.0, 0.82), (2.0, 0.16), (3.0, 0.05)),
    "soft_pad": ((1.0, 0.72), (1.002, 0.16), (2.0, 0.06)),
    "hollow": ((1.0, 0.28), (2.0, 0.56), (3.0, 0.08)),
}
PITCHES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6,
           "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def local(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("score and output must stay inside the project")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.is_symlink():
        raise ValueError("unsafe project path")
    return path


def hz(note: str) -> float:
    import re
    match = re.fullmatch(r"([A-G]#?)([1-7])", note)
    if not match or match.group(1) not in PITCHES:
        raise ValueError(f"unsupported note: {note}")
    midi = (int(match.group(2)) + 1) * 12 + PITCHES[match.group(1)]
    return 440 * 2 ** ((midi - 69) / 12)


def finite(value: Any, lower: float, upper: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{label} must be between {lower} and {upper}")
    return float(value)


def render(project: str | Path, score_path: str, output_path: str) -> dict[str, Any]:
    root = Path(project).resolve()
    if status(root).get("method") != "code_local":
        raise ValueError("this project has not selected code_local music")
    source = local(root, score_path)
    destination = local(root, output_path)
    if destination.exists() or destination == source:
        raise ValueError("output must be a new WAV file")
    score = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(score, dict) or score.get("schema_version") != 1:
        raise ValueError("score schema_version 1 required")
    bpm = finite(score.get("bpm"), 40, 220, "bpm")
    beats = finite(score.get("total_beats"), 1, 512, "total_beats")
    tail = finite(score.get("tail_seconds"), 0, 4, "tail_seconds")
    duration = beats * 60 / bpm + tail
    if duration > 240:
        raise ValueError("score duration exceeds 240 seconds")
    sections = score.get("sections")
    events = score.get("events")
    if not isinstance(sections, list) or not sections or not isinstance(events, list) or not events:
        raise ValueError("authored sections and note events are required")
    last = 0.0
    for section in sections:
        if not isinstance(section, dict) or not str(section.get("name", "")).strip():
            raise ValueError("each section needs a name")
        start = finite(section.get("start_beat"), 0, beats, "section start")
        end = finite(section.get("end_beat"), 0, beats, "section end")
        finite(section.get("gain"), 0, 1, "section gain")
        if abs(start - last) > 1e-8 or end <= start:
            raise ValueError("sections must cover the score contiguously")
        last = end
    if abs(last - beats) > 1e-8:
        raise ValueError("sections must end at total_beats")
    frames = round(duration * RATE)
    mix = array("f", [0.0]) * frames
    for event in events:
        if not isinstance(event, dict) or event.get("timbre") not in TIMBRES:
            raise ValueError("every event needs a supported procedural timbre")
        freq = hz(event.get("note"))
        start_beat = finite(event.get("start_beat"), 0, beats, "event start")
        length_beats = finite(event.get("duration_beats"), 0.01, beats, "event duration")
        level = finite(event.get("level"), 0.001, 1, "event level")
        if start_beat + length_beats > beats + 1e-8:
            raise ValueError("event extends beyond authored score")
        section = next((item for item in sections if item["start_beat"] <= start_beat < item["end_beat"]), None)
        if section is None:
            raise ValueError("event has no section")
        start = round(start_beat * 60 / bpm * RATE)
        held = length_beats * 60 / bpm
        end = min(frames, start + round((held + min(tail, 0.7)) * RATE))
        partials = TIMBRES[event["timbre"]]
        for index in range(start, end):
            t = (index - start) / RATE
            attack = min(1.0, t / (0.24 if event["timbre"] == "soft_pad" else 0.012))
            release = math.exp(-max(0.0, t - held) / 0.22)
            decay = math.exp(-t / (4.0 if event["timbre"] == "soft_pad" else 1.8))
            tone = sum(weight * math.sin(2 * math.pi * freq * multiple * t) for multiple, weight in partials)
            mix[index] += 0.14 * level * section["gain"] * attack * release * decay * tone
    peak = max(abs(value) for value in mix)
    if peak == 0:
        raise ValueError("score produced silence")
    gain = min(1.0, 0.72 / peak)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(RATE)
        buffer = bytearray()
        for value in mix:
            buffer.extend(struct.pack("<h", round(max(-1, min(1, value * gain)) * 32767)))
        target.writeframes(buffer)
    result = {"score": score_path, "score_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "output": output_path, "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
              "duration_seconds": frames / RATE, "event_count": len(events), "peak_before_gain": peak,
              "timbre_limit": "procedural tones only; no acoustic instrument samples or style guarantee"}
    receipt = local(root, output_path + ".receipt.json")
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("render",))
    parser.add_argument("--project", required=True)
    parser.add_argument("--score", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.project, args.score, args.out), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
