#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from validate_director_storyboard import audio_features, sha256


def digest_payload(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def build_fingerprint(path: Path) -> dict:
    features = [[round(component, 2) for component in block] for block in audio_features(path)]
    window_size = 8
    windows = []
    if len(features) >= window_size:
        for start in range(0, len(features) - window_size + 1):
            windows.append(digest_payload(features[start:start + window_size]))
    elif features:
        windows.append(digest_payload(features))
    return {
        "schema_version": "1.0",
        "audio_path": str(path),
        "asset_sha256": sha256(path),
        "audio_fingerprint": digest_payload(features),
        "audio_window_fingerprints": sorted(set(windows)),
        "feature_block_seconds": 1,
        "window_seconds": min(window_size, len(features)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a coarse re-encode-tolerant BGM fingerprint with rolling windows.")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    path = args.audio.resolve()
    if not path.is_file():
        raise SystemExit(f"audio file missing: {path}")
    result = build_fingerprint(path)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
