#!/usr/bin/env python3
"""Read-only status for an explicitly supplied, separate FredTalk installation.

This bridge does not run source code, install dependencies, render video, or
select/revise a project's style. File and dependency presence are not quality
acceptance or proof that the rendering toolchain works.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import style_registry


REQUIRED_SOURCE_FILES = (
    "README.md",
    "skills/fred-remotion-output/SKILL.md",
    "skills/fred-remotion-output/DESIGN.md",
    "library/catalog.json",
    "skills/fred-remotion-output/scripts/scene.py",
    "skills/fred-remotion-output/scripts/library_gate.py",
    "skills/fred-remotion-output/scripts/validate_production_gate.py",
    "skills/fred-remotion-output/templates/component-kit/package.json",
)
SOURCE_PACKAGE_DIRECTORIES = (
    "skills/fred-remotion-output",
    "skills/fred-remotion-output/templates/component-kit",
)
RENDER_PACKAGES = ("remotion", "react", "typescript")
STYLE = "fredtalk-native"
WORKFLOW = "fredtalk-native"


class BridgeError(RuntimeError):
    pass


def directory(raw: str, label: str) -> Path:
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise BridgeError(f"{label}: an existing directory is required")
    return path


def regular_file(root: Path, relative: str, label: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise BridgeError(f"{label}: missing, linked, or escaping file: {relative}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise BridgeError(f"{label}: invalid JSON or text encoding: {error}") from error
    if not isinstance(value, dict):
        raise BridgeError(f"{label}: JSON root must be an object")
    return value


def source_status(root: Path) -> dict:
    for relative in REQUIRED_SOURCE_FILES:
        regular_file(root, relative, "FredTalk source")
    for relative in SOURCE_PACKAGE_DIRECTORIES:
        path = root / relative
        if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(root):
            raise BridgeError(f"FredTalk source: missing, linked, or escaping package directory: {relative}")
    catalog_path = root / "library/catalog.json"
    catalog = json_object(catalog_path, "FredTalk catalog")
    if catalog.get("schemaVersion") != 1 or not isinstance(catalog.get("items"), list):
        raise BridgeError("FredTalk catalog: expected schemaVersion 1 and an items array")
    if any(not isinstance(item, dict) for item in catalog["items"]):
        raise BridgeError("FredTalk catalog: every item must be an object")
    return {
        "root": str(root),
        "upstreamSkill": str(root / "skills/fred-remotion-output/SKILL.md"),
        "requiredFilesChecked": list(REQUIRED_SOURCE_FILES),
        "sourcePackageDirectoriesPresent": list(SOURCE_PACKAGE_DIRECTORIES),
        "catalog": {
            "path": "library/catalog.json",
            "sha256": sha256(catalog_path),
            "itemCount": len(catalog["items"]),
            "note": "Item count is an index count, not a count of usable components.",
        },
    }


def renderer_status(renderer: Path | None) -> dict:
    note = "Package presence alone does not verify a browser, FFmpeg, rendering, or visual review."
    if renderer is None:
        return {"status": "unchecked", "note": note}
    packages: dict[str, str | None] = {}
    for name in RENDER_PACKAGES:
        path = renderer / "node_modules" / name / "package.json"
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(renderer):
            packages[name] = None
            continue
        try:
            package = json_object(path, f"renderer package {name}")
        except BridgeError:
            packages[name] = None
            continue
        version = package.get("version")
        packages[name] = version if package.get("name") == name and isinstance(version, str) and version.strip() else None
    return {
        "status": "dependencies_present" if all(packages.values()) else "missing",
        "root": str(renderer),
        "packageVersions": packages,
        "note": note,
    }


def project_status(project: Path | None) -> dict | None:
    if project is None:
        return None
    lock = style_registry.read_lock(style_registry.lock_path(project))
    if lock is None:
        raise BridgeError("project: no selected style lock; this check cannot select a style")
    if lock.get("style") != STYLE:
        raise BridgeError("project: locked to another style; this check cannot change it")
    if lock.get("workflow") != WORKFLOW:
        raise BridgeError("project: FredTalk style lock has a different or missing workflow")
    return {"root": str(project), "style": STYLE, "workflow": WORKFLOW,
            "lock": f"artifacts/{style_registry.LOCK_NAME}", "readOnly": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="check source, optional renderer, and optional project lock")
    status.add_argument("--root", help="external FredTalk source; also FREDTALK_ROOT")
    status.add_argument("--renderer", help="separate Remotion project; also FREDTALK_RENDERER")
    status.add_argument("--project", help="existing video project; read its style lock only")
    args = parser.parse_args(argv)
    try:
        root_raw = args.root or os.environ.get("FREDTALK_ROOT")
        if not root_raw:
            raise BridgeError("FredTalk root is not set; pass --root or FREDTALK_ROOT")
        root = directory(root_raw, "FredTalk root")
        renderer_raw = args.renderer or os.environ.get("FREDTALK_RENDERER")
        renderer = directory(renderer_raw, "renderer") if renderer_raw else None
        project = directory(args.project, "project") if args.project else None
        result = {
            "status": "ready_for_planning",
            "source": source_status(root),
            "renderEnvironment": renderer_status(renderer),
            "boundary": "Read-only source and package check. No install, run, render, style change, review, or publication.",
        }
        if project is not None:
            result["project"] = project_status(project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BridgeError, style_registry.StyleError, OSError, ValueError, TypeError, KeyError,
            AttributeError, UnicodeError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
