#!/usr/bin/env python3
"""Select one video style per project without migrating legacy editorial state."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
CATALOG = PLUGIN / "assets" / "style-catalog.json"
LOCK_NAME = "video-studio-style.json"


class StyleError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def catalog() -> tuple[dict, dict[str, dict]]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or not isinstance(data.get("styles"), list):
        raise StyleError("invalid style catalog")
    styles: dict[str, dict] = {}
    for style in data["styles"]:
        if not isinstance(style, dict) or style.get("status") not in {"production_ready", "trial_only"}:
            raise StyleError("invalid style status")
        ident = style.get("id")
        if not isinstance(ident, str) or not ident or ident in styles:
            raise StyleError("missing or duplicate style ID")
        for key in ("entry", "qualityProfile"):
            value = style.get(key)
            if not isinstance(value, str) or Path(value).is_absolute() or ".." in Path(value).parts:
                raise StyleError("unsafe style resource path")
            target = (PLUGIN / value).resolve()
            if not target.is_file() or not target.is_relative_to(PLUGIN):
                raise StyleError(f"missing style resource: {value}")
        styles[ident] = style
    return data, styles


def project_path(value: str) -> Path:
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise StyleError("project must be an existing directory")
    return path


def lock_path(project: Path) -> Path:
    artifacts = project / "artifacts"
    if artifacts.is_symlink() or (artifacts.exists() and not artifacts.is_dir()):
        raise StyleError("artifacts must be a local directory, not a link or file")
    return artifacts / LOCK_NAME


def has_existing_project_evidence(project: Path) -> bool:
    """An old project without plugin state is still an old project."""
    markers = ("HANDOFF.md", "design.md", "project.json", "storyboard.json",
               "artifacts/editorial-job-card.md", "artifacts/delivery-manifest.json")
    return any((project / marker).exists() for marker in markers)


def read_lock(path: Path) -> dict | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise StyleError("style lock must be a regular file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1 or not isinstance(data.get("style"), str):
        raise StyleError("invalid style lock")
    return data


def atomic_create(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    # Create-only; never silently replace another worker's style decision.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_replace(path: Path, value: dict) -> None:
    body = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, name = tempfile.mkstemp(prefix=".video-style-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_choice(style: str, mode: str, styles: dict[str, dict]) -> None:
    if style not in styles:
        raise StyleError(f"unknown style: {style}")
    if mode not in {"trial", "production"}:
        raise StyleError("mode must be trial or production")
    if mode == "production" and styles[style]["status"] != "production_ready":
        raise StyleError("style is trial-only; dynamic visual and technical acceptance is required first")


def main() -> int:
    parser = argparse.ArgumentParser(description="Video studio style catalog and per-project lock")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    for action in ("status", "select", "revise"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--project", required=True)
        if action != "status":
            cmd.add_argument("--style", required=True)
            cmd.add_argument("--mode", choices=("trial", "production"), required=True)
            cmd.add_argument("--reason", required=True)
        if action == "select":
            kind = cmd.add_mutually_exclusive_group()
            kind.add_argument("--new-project", action="store_true", help="affirm this is a new video project")
            kind.add_argument("--existing-project-reviewed", action="store_true", help="affirm existing assets and locks were reviewed")
    args = parser.parse_args()
    try:
        data, styles = catalog()
        if args.command == "catalog":
            result = {"catalogVersion": data["catalogVersion"], "styles": data["styles"]}
        else:
            project = project_path(args.project)
            path = lock_path(project)
            existing = read_lock(path)
            legacy = (project / "artifacts" / "editorial-plugin-state.json").is_file()
            if args.command == "status":
                if existing:
                    result = {"status": "locked", "lock": existing, "catalogStatus": styles.get(existing["style"], {}).get("status", "missing")}
                elif legacy:
                    result = {"status": "legacy_inferred_no_write", "style": "editorial-illustration", "mode": "production"}
                else:
                    result = {"status": "unselected_requires_project_review" if has_existing_project_evidence(project) else "unselected_new_project_unconfirmed",
                              "available": [item["id"] for item in data["styles"]]}
            else:
                if not args.reason.strip():
                    raise StyleError("selection/revision needs a real project reason")
                validate_choice(args.style, args.mode, styles)
                if legacy and not existing:
                    raise StyleError("legacy editorial project is pinned; continue it without rewriting its style lock")
                if args.command == "select":
                    if existing:
                        if existing["style"] != args.style or existing.get("mode") != args.mode:
                            raise StyleError("style already locked; use revise with a reason, retaining history")
                        result = {"status": "unchanged", "lock": existing}
                    else:
                        if not (args.new_project or args.existing_project_reviewed):
                            raise StyleError("unlocked project needs --new-project or --existing-project-reviewed after reviewing current assets")
                        item = {"schemaVersion": 1, "style": args.style, "mode": args.mode,
                                "catalogVersion": data["catalogVersion"], "selectedAt": now(),
                                "reason": args.reason.strip(),
                                "projectKind": "new" if args.new_project else "existing_reviewed", "history": []}
                        atomic_create(path, item)
                        result = {"status": "selected", "lock": item, "path": str(path)}
                else:
                    if not existing:
                        raise StyleError("no style lock to revise")
                    previous = {"style": existing["style"], "mode": existing.get("mode"),
                                "selectedAt": existing.get("selectedAt"), "reason": existing.get("reason")}
                    updated = {**existing, "style": args.style, "mode": args.mode,
                               "catalogVersion": data["catalogVersion"], "selectedAt": now(),
                               "reason": args.reason.strip(), "history": [*existing.get("history", []), previous]}
                    atomic_replace(path, updated)
                    result = {"status": "revised", "lock": updated, "path": str(path)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (StyleError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
