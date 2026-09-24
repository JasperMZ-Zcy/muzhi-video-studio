#!/usr/bin/env python3
"""Bounded local MiniMax-H3 V2 adapter; never submits to the cloud MiniMax API.

The existing PowerShell runner owns ComfyUI, model identity, prewarm and resource
guards. This adapter owns project input identity, deduplication and media ingest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from provider_router import status as provider_status


PROVIDER_ID = "local-h3"
PROFILES = {
    "Fast720Seven": (720, 1280, 168),
    "Quality720Seven": (720, 1280, 168),
    "NativeLong": (720, 1280, 158),
}
SHA_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
SAFE_NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")


class AdapterError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_file(project: Path, value: str) -> Path:
    relative = Path(value)
    if not value or relative.is_absolute() or any(part in ("..", "") for part in relative.parts):
        raise AdapterError("input must be a project-relative file")
    path = project / relative
    if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
        raise AdapterError(f"input is missing, linked or unsafe: {value}")
    return path


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AdapterError(f"not a JSON object: {path}")
    return value


def _command(args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)


def _context(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project).resolve(strict=True)
    if not project.is_dir():
        raise AdapterError("project must be an existing directory")
    if not args.shot_id.strip() or not SAFE_NAME_RE.fullmatch(args.shot_id):
        raise AdapterError("shot-id must be a safe 1-64 character identifier")
    image = _project_file(project, args.input_image)
    prompt_file = _project_file(project, args.prompt_file)
    prompt = prompt_file.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise AdapterError("prompt file is empty")
    runner_value = args.runner or os.environ.get("MUZHI_H3_V2_RUNNER", "")
    if not runner_value:
        for ancestor in (project, *project.parents):
            if ancestor.name.lower() == "openmontage":
                candidate = ancestor / "services" / "muzhi-h3-local" / "scripts" / "generate-h3-i2v-v2.ps1"
                if candidate.is_file():
                    runner_value = str(candidate)
                break
    if not runner_value:
        raise AdapterError("V2 runner not found under OpenMontage; specify --runner or MUZHI_H3_V2_RUNNER")
    runner = Path(runner_value).resolve(strict=True)
    if not runner.is_file() or runner.name.lower() != "generate-h3-i2v-v2.ps1":
        raise AdapterError("runner must be the existing generate-h3-i2v-v2.ps1")
    image_hash = _sha256(image)
    prompt_hash = _sha256(prompt_file)
    identity = {
        "project": str(project), "shot_id": args.shot_id, "input_sha256": image_hash,
        "prompt_sha256": prompt_hash, "profile": args.profile, "seed": args.seed,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
    output_name = f"local-h3-{args.shot_id}-{key}"
    return {
        "project": project, "image": image, "prompt_file": prompt_file, "prompt": prompt,
        "runner": runner, "identity": identity, "key": key, "output_name": output_name,
        "runner_sha256": _sha256(runner),
        "attempt": project / "artifacts" / "local-h3" / "attempts" / f"{output_name}.json",
        "delivery": project / "artifacts" / "local-h3" / "deliveries" / f"{output_name}.json",
        "media": project / "artifacts" / "local-h3" / "media" / f"{output_name}.mp4",
    }


def _preflight(args: argparse.Namespace, context: dict[str, Any]) -> dict[str, Any]:
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(context["runner"]),
               "-Profile", args.profile, "-ValidateOnly"]
    if args.ai_root:
        command += ["-AiRoot", args.ai_root]
    if args.hot_root:
        command += ["-HotRoot", args.hot_root]
    result = _command(command, timeout=120)
    if result.returncode != 0:
        raise AdapterError("H3 V2 preflight failed: " + result.stderr[-1000:])
    try:
        preflight = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError("H3 V2 preflight did not return JSON") from exc
    if preflight.get("status") != "ready" or preflight.get("profile") != args.profile:
        raise AdapterError("H3 V2 preflight did not confirm the requested profile")
    ai_root = Path(preflight["aiRoot"]).resolve(strict=True)
    runtime_root = ai_root / "H3_v2_lab_runtime"
    context["runtime_root"] = runtime_root
    context["result_path"] = runtime_root / "outputs" / f"{context['output_name']}.v2-result.json"
    desktop = _command(["powershell.exe", "-NoProfile", "-Command",
                        "[Environment]::GetFolderPath('Desktop')"], timeout=30)
    if desktop.returncode != 0 or not desktop.stdout.strip():
        raise AdapterError("could not resolve the Desktop used by the V2 runner")
    context["preview_root"] = Path(desktop.stdout.strip()) / "牧之远见-视频预览"
    return preflight


def plan(args: argparse.Namespace) -> dict[str, Any]:
    context = _context(args)
    preflight = _preflight(args, context)
    try:
        selection = provider_status(context["project"]).get("selection")
    except Exception as exc:
        raise AdapterError("cannot inspect this project's provider selection") from exc
    route_selected = (isinstance(selection, dict) and selection.get("provider_id") == PROVIDER_ID
                      and selection.get("scope") == "future_unsubmitted")
    return {
        "mode": "plan", "provider_id": PROVIDER_ID, "ready": True,
        "shot_id": args.shot_id, "profile": args.profile, "output_name": context["output_name"],
        "input_sha256": context["identity"]["input_sha256"],
        "prompt_sha256": context["identity"]["prompt_sha256"],
        "preflight": preflight, "route_selected": route_selected, "run_permitted": route_selected,
        "existing_attempt": context["attempt"].exists(),
        "generation_started": False,
    }


def _check_route(project: Path) -> dict[str, Any]:
    try:
        route = provider_status(project)
    except Exception as exc:
        raise AdapterError("cannot verify this project's provider selection") from exc
    selection = route.get("selection")
    if (not isinstance(selection, dict) or selection.get("provider_id") != PROVIDER_ID
            or selection.get("scope") != "future_unsubmitted"):
        raise AdapterError("project provider selection is not local-h3 for future unsubmitted shots")
    return selection


def _media_probe(ffprobe: str, path: Path) -> dict[str, Any]:
    command = [ffprobe, "-v", "error", "-count_frames", "-show_entries",
               "stream=codec_type,width,height,avg_frame_rate,nb_frames,nb_read_frames:format=duration",
               "-of", "json", str(path)]
    try:
        result = _command(command, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError("ffprobe unavailable or timed out; keep original result for recovery") from exc
    if result.returncode != 0:
        raise AdapterError("ffprobe failed: " + result.stderr[-1000:])
    try:
        data = json.loads(result.stdout)
        streams = data["streams"]
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if len(videos) != 1 or audio:
            raise AdapterError("H3 delivery must have exactly one video stream and no audio")
        video = videos[0]
        rate = str(video["avg_frame_rate"])
        numerator, denominator = (int(piece) for piece in rate.split("/"))
        if denominator == 0 or numerator / denominator != 24:
            raise AdapterError("H3 delivery frame rate is not 24 fps")
        frames = int(video.get("nb_read_frames") or video.get("nb_frames"))
        return {"width": int(video["width"]), "height": int(video["height"]),
                "frames": frames, "fps": rate, "duration": float(data["format"]["duration"]), "audio": False}
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise AdapterError("ffprobe returned incomplete media metadata") from exc


def _checked_ffprobe(value: str) -> str:
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise AdapterError("ffprobe path does not exist") from exc
    if not path.is_file() or path.name.lower() not in ("ffprobe.exe", "ffprobe"):
        raise AdapterError("--ffprobe must name an existing ffprobe executable")
    try:
        result = _command([str(path), "-version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError("ffprobe cannot be executed before local H3 generation") from exc
    if result.returncode != 0:
        raise AdapterError("ffprobe -version failed before local H3 generation")
    return str(path)


def _restore_context_from_attempt(context: dict[str, Any], attempt: dict[str, Any]) -> None:
    preflight = attempt.get("preflight")
    if not isinstance(preflight, dict) or not preflight.get("aiRoot"):
        raise AdapterError("prior attempt has no AI root; inspect it manually")
    ai_root = Path(str(preflight["aiRoot"]))
    context["runtime_root"] = ai_root / "H3_v2_lab_runtime"
    context["result_path"] = context["runtime_root"] / "outputs" / f"{context['output_name']}.v2-result.json"
    if context["result_path"].resolve() != Path(str(attempt.get("result_json", ""))).resolve():
        raise AdapterError("prior attempt result path differs from the current identity")
    # Preserve the path spelling already recorded in the first delivery; on
    # Windows a short 8.3 path and its long name can resolve to the same file.
    context["result_path"] = Path(str(attempt["result_json"]))
    context["runtime_root"] = context["result_path"].parent.parent


def _validate_timing(args: argparse.Namespace) -> None:
    values = (args.source_start, args.timeline_start, args.usable_duration)
    if not all(math.isfinite(value) for value in values):
        raise AdapterError("source-start, timeline-start and usable-duration must be finite numbers")
    if args.source_start < 0 or args.timeline_start < 0 or args.usable_duration <= 0:
        raise AdapterError("starts must be non-negative and usable-duration must be positive")
    if args.source_start + args.usable_duration > PROFILES[args.profile][2] / 24 + 1e-9:
        raise AdapterError("requested usable interval exceeds the formal profile duration")


def _verify_result(context: dict[str, Any], args: argparse.Namespace) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    result_path = context["result_path"]
    if not result_path.is_file():
        raise AdapterError(f"V2 result JSON missing; inspect stage logs before retry: {result_path}")
    result = _read_json(result_path)
    if result.get("status") != "success" or result.get("profile") != args.profile:
        raise AdapterError("V2 result is not successful for requested profile")
    source = Path(str(result.get("output", "")))
    if not source.is_file() or source.is_symlink():
        raise AdapterError("V2 result output file is missing or linked")
    if source.parent.resolve() != (context["runtime_root"] / "outputs").resolve():
        raise AdapterError("V2 output is outside the expected runtime outputs directory")
    if source.name != context["output_name"] + ".mp4":
        raise AdapterError("V2 output name differs from this attempt")
    if Path(str(result.get("input", ""))).resolve() != context["image"].resolve():
        raise AdapterError("V2 input path differs from this attempt")
    if not SHA_RE.fullmatch(str(result.get("sha256", ""))):
        raise AdapterError("V2 result has no valid SHA-256")
    actual_hash = _sha256(source)
    if actual_hash != str(result["sha256"]).lower():
        raise AdapterError("V2 output SHA-256 mismatch")
    if result.get("copyHashMatches") is not True:
        raise AdapterError("V2 desktop-copy hash did not match")
    desktop = Path(str(result.get("desktop", "")))
    if not desktop.is_file() or desktop.is_symlink() or desktop.name != context["output_name"] + ".mp4":
        raise AdapterError("V2 desktop copy is missing or has the wrong name")
    if _sha256(desktop) != actual_hash:
        raise AdapterError("V2 desktop copy actual SHA-256 differs from source")
    media = _media_probe(args.ffprobe, source)
    width, height, frames = PROFILES[args.profile]
    expected_duration = frames / 24
    if (media["width"], media["height"], media["frames"]) != (width, height, frames):
        raise AdapterError("V2 output dimensions or frame count differ from the formal profile")
    if abs(media["duration"] - expected_duration) > 0.08:
        raise AdapterError("V2 output duration differs from the formal profile")
    return source, result, media


def _copy_exclusive(source: Path, destination: Path, sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or destination.is_symlink() or _sha256(destination) != sha256:
            raise AdapterError("project media path exists with different content; refusing overwrite")
        return
    created = False
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            created = True
            shutil.copyfileobj(reader, writer, 1024 * 1024)
        if _sha256(destination) != sha256:
            raise AdapterError("project media copy hash mismatch")
    except Exception:
        if created and destination.exists():
            destination.unlink()
        raise


def _ingest(context: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    source, result, media = _verify_result(context, args)
    run_key = result.get("base", {}).get("runKey") if isinstance(result.get("base"), dict) else None
    if not isinstance(run_key, str) or not run_key.strip():
        raise AdapterError("V2 base result has no runKey")
    source_hash = _sha256(source)
    if args.usable_duration <= 0 or args.source_start < 0 or args.timeline_start < 0:
        raise AdapterError("timeline and usable duration must be non-negative, with positive usable duration")
    if args.source_start + args.usable_duration > media["duration"] + 1e-9:
        raise AdapterError("usable duration exceeds probed source duration")
    _copy_exclusive(source, context["media"], source_hash)
    relative_media = context["media"].relative_to(context["project"]).as_posix()
    delivery = {
        "shot_id": args.shot_id, "source_provider": PROVIDER_ID,
        "provider_job_id": run_key,
        "path": relative_media, "sha256": source_hash,
        "duration": media["duration"], "width": media["width"], "height": media["height"],
        "fps": media["fps"], "source_audio_removed": True,
        "source_start": args.source_start, "timeline_start": args.timeline_start,
        "usable_duration": args.usable_duration, "playback_rate": 1,
        "quality_review_status": "not_reviewed",
        "local_h3": {"profile": args.profile, "base_run_key": run_key,
                     "result_json": str(context["result_path"]), "source_output": str(source),
                     "input_sha256": context["identity"]["input_sha256"],
                     "prompt_sha256": context["identity"]["prompt_sha256"],
                     "delivery_method": "optical_flow_extension" if args.profile != "NativeLong" else "native_long"},
    }
    manifest = {"deliveries": [delivery]}
    if context["delivery"].exists():
        existing = _read_json(context["delivery"])
        if existing != manifest:
            raise AdapterError("delivery manifest already exists with different content")
    else:
        _atomic_json(context["delivery"], manifest)
    return {"status": "ingested_pending_visual_review", "provider_id": PROVIDER_ID,
            "shot_id": args.shot_id, "delivery_manifest": str(context["delivery"]),
            "project_media": str(context["media"]), "source_result": str(context["result_path"]),
            "source_sha256": source_hash, "run_key": run_key,
            "quality_review_claimed": False}


def run(args: argparse.Namespace) -> dict[str, Any]:
    context = _context(args)
    _validate_timing(args)
    if not args.accept_local_heavy or not args.authorization_quote.strip():
        raise AdapterError("run requires --accept-local-heavy and the user's actual --authorization-quote")
    approved_hash = args.approved_input_sha256.lower()
    if not SHA_RE.fullmatch(approved_hash) or approved_hash != context["identity"]["input_sha256"]:
        raise AdapterError("approved-input-sha256 must match the current first frame")
    approved_prompt_hash = args.approved_prompt_sha256.lower()
    if not SHA_RE.fullmatch(approved_prompt_hash) or approved_prompt_hash != context["identity"]["prompt_sha256"]:
        raise AdapterError("approved-prompt-sha256 must match the current motion prompt file")
    if context["attempt"].exists():
        attempt = _read_json(context["attempt"])
        if attempt.get("identity") != context["identity"]:
            raise AdapterError("attempt identity changed; refusing reuse")
        _restore_context_from_attempt(context, attempt)
        if context["result_path"].exists():
            try:
                args.ffprobe = _checked_ffprobe(args.ffprobe)
                ingested = _ingest(context, args)
                ingested["reused_existing_result"] = True
                return ingested
            except Exception as exc:
                return {"status": "resume_required", "reason": str(exc), "attempt": str(context["attempt"]),
                        "result_json": str(context["result_path"]), "generation_started": False}
        return {"status": "resume_required", "reason": "prior attempt exists; inspect stage results and logs before retry",
                "attempt": str(context["attempt"]), "result_json": str(context["result_path"]), "generation_started": False}
    # A provider switch governs future unsubmitted shots only. The branch
    # above may inspect and recover the already-submitted H3 attempt, but it
    # cannot reach the generation command below.
    selection = _check_route(context["project"])
    args.ffprobe = _checked_ffprobe(args.ffprobe)
    preflight = _preflight(args, context)
    base_name = f"{context['output_name']}-{args.profile.replace('720Seven', '-720-seven').replace('NativeLong', 'native-long').lower()}-base"
    # The formal runner uses -Force/-y for its output and Desktop copies. Refuse
    # every predictable path before launching it, including the base video.
    output_root = context["runtime_root"] / "outputs"
    collision_paths = [context["result_path"], context["media"], context["delivery"],
                       output_root / f"{context['output_name']}.mp4",
                       output_root / f"{context['output_name']}.optical.tmp.mp4",
                       output_root / f"{base_name}.mp4", output_root / f"{base_name}.result.json",
                       context["preview_root"] / f"{context['output_name']}.mp4",
                       context["preview_root"] / f"{base_name}.mp4"]
    if any(path.exists() for path in collision_paths):
        raise AdapterError("output identity collision; refusing overwrite")
    runtime_root = context["runtime_root"]
    runtime_root.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_root / "local-h3-adapter.lock"
    release_lock = True
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise AdapterError(f"another local H3 adapter run or stale lock exists: {lock_path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "shot_id": args.shot_id, "created_at": datetime.now(timezone.utc).isoformat()}, stream)
        attempt = {"status": "running", "provider_id": PROVIDER_ID, "identity": context["identity"],
                   "runner_sha256": context["runner_sha256"],
                   "output_name": context["output_name"], "result_json": str(context["result_path"]),
                   "authorization_quote": args.authorization_quote, "approved_input_sha256": approved_hash,
                   "approved_prompt_sha256": approved_prompt_hash,
                   "route_selection": selection, "started_at": datetime.now(timezone.utc).isoformat(),
                   "preflight": preflight}
        _atomic_json(context["attempt"], attempt)
        _check_route(context["project"])
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(context["runner"]),
                   "-InputImage", str(context["image"]), "-Prompt", context["prompt"], "-Profile", args.profile,
                   "-Seed", str(args.seed), "-OutputName", context["output_name"]]
        if args.ai_root:
            command += ["-AiRoot", args.ai_root]
        if args.hot_root:
            command += ["-HotRoot", args.hot_root]
        try:
            process = _command(command, timeout=4 * 60 * 60)
        except subprocess.TimeoutExpired:
            release_lock = False
            attempt["status"] = "unknown_after_timeout"
            _atomic_json(context["attempt"], attempt)
            return {"status": "resume_required", "reason": "runner timed out; inspect original process and result before retry",
                    "attempt": str(context["attempt"]), "result_json": str(context["result_path"])}
        attempt["exit_code"] = process.returncode
        attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
        if process.returncode != 0:
            attempt["status"] = "failed_or_partial"
            attempt["stderr_tail"] = process.stderr[-1000:]
            _atomic_json(context["attempt"], attempt)
            return {"status": "resume_required", "reason": "runner failed; inspect stage logs and existing results",
                    "attempt": str(context["attempt"]), "result_json": str(context["result_path"]), "exit_code": process.returncode}
        try:
            ingested = _ingest(context, args)
        except Exception as exc:
            attempt["status"] = "result_needs_review"
            attempt["reason"] = str(exc)
            try:
                _atomic_json(context["attempt"], attempt)
            except Exception as record_exc:
                return {"status": "resume_required", "reason": f"{exc}; attempt update failed: {record_exc}",
                        "attempt": str(context["attempt"]), "result_json": str(context["result_path"]),
                        "generation_started": True}
            return {"status": "resume_required", "reason": str(exc), "attempt": str(context["attempt"]),
                    "result_json": str(context["result_path"]), "generation_started": True}
        attempt["status"] = "ingested_pending_visual_review"
        attempt["delivery_manifest"] = ingested["delivery_manifest"]
        try:
            _atomic_json(context["attempt"], attempt)
        except Exception as exc:
            return {"status": "resume_required", "reason": f"media ingested but attempt update failed: {exc}",
                    "attempt": str(context["attempt"]), "result_json": str(context["result_path"]),
                    "delivery_manifest": ingested["delivery_manifest"], "generation_started": True}
        return ingested
    finally:
        if release_lock:
            lock_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local H3 V2 adapter; plan is read-only, run is an explicit heavy task")
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("plan", "run"):
        item = sub.add_parser(name)
        item.add_argument("--project", required=True)
        item.add_argument("--shot-id", required=True)
        item.add_argument("--input-image", required=True, help="project-relative approved first frame")
        item.add_argument("--prompt-file", required=True, help="project-relative UTF-8 motion prompt")
        item.add_argument("--profile", choices=sorted(PROFILES), required=True)
        item.add_argument("--seed", type=int, required=True)
        item.add_argument("--runner", help="path to the existing formal V2 PowerShell runner")
        item.add_argument("--ai-root", help="optional existing AI root, otherwise runner resolves it")
        item.add_argument("--hot-root", help="optional existing hot-model root, otherwise runner resolves it")
        if name == "run":
            item.add_argument("--accept-local-heavy", action="store_true")
            item.add_argument("--authorization-quote", required=True)
            item.add_argument("--approved-input-sha256", required=True)
            item.add_argument("--approved-prompt-sha256", required=True)
            item.add_argument("--ffprobe", required=True)
            item.add_argument("--source-start", type=float, default=0)
            item.add_argument("--timeline-start", type=float, required=True)
            item.add_argument("--usable-duration", type=float, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = plan(args) if args.mode == "plan" else run(args)
    except (AdapterError, OSError, json.JSONDecodeError) as exc:
        result = {"status": "blocked", "reason": str(exc), "generation_started": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") or result.get("status") == "ingested_pending_visual_review" else 1


if __name__ == "__main__":
    sys.exit(main())
