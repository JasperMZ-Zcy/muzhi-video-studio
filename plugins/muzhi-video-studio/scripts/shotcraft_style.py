#!/usr/bin/env python3
"""Map an executing assistant's structured design parameters to Shotcraft props.

This deliberately does not parse design.md.  A project assistant must first read the
design and write a complete JSON parameter file.  The adapter then validates those
values, binds them to the current design.md SHA-256, and can create one project-local
JSON payload.  A changed design or an existing different payload is never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
DESIGN_SOURCE = "design.md"
DEFAULT_OUTPUT = Path("style-adapter") / "shotcraft-remotion-style.json"
HEX_THEME_FIELDS = ("paper", "paperDeep", "ink", "inkSoft", "amber", "amberSoft", "rule")
SURFACE_THEME_FIELDS = ("backgroundOverlay", "panelSurface", "promptSurface", "mutedSurface", "shadow")
THEME_FIELDS = HEX_THEME_FIELDS + SURFACE_THEME_FIELDS
REQUIRED_SAFE_AREA_FIELDS = ("width", "height", "left", "right", "top", "bottom", "subtitle_reserve_bottom")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class StyleAdapterError(ValueError):
    """A caller-supplied style contract cannot safely be used."""


class DesignDriftError(StyleAdapterError):
    """The assistant's structured input no longer describes current design.md."""


class OutputExistsError(StyleAdapterError):
    """A new style map would overwrite a project artifact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StyleAdapterError(f"cannot read {label}: {error}") from error
    if not isinstance(value, dict):
        raise StyleAdapterError(f"{label} must be a JSON object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StyleAdapterError(f"{label} must be a non-empty string")
    return value.strip()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StyleAdapterError(f"{label} must be an object")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "a list of strings" if allow_empty else "a non-empty list of strings"
        raise StyleAdapterError(f"{label} must be {requirement}")
    result = [_text(item, f"{label} item") for item in value]
    if len(set(result)) != len(result):
        raise StyleAdapterError(f"{label} must not contain duplicates")
    return result


def _relative_project_path(project: Path, value: str, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise StyleAdapterError(f"{label} must be a project-relative path without '..'")
    resolved_project = project.resolve()
    resolved = (resolved_project / candidate).resolve()
    try:
        resolved.relative_to(resolved_project)
    except ValueError as error:
        raise StyleAdapterError(f"{label} must stay inside the project") from error
    return resolved


def _validate_theme(palette: dict[str, Any], font: dict[str, Any]) -> dict[str, str]:
    missing = [field for field in THEME_FIELDS if field not in palette]
    if missing:
        raise StyleAdapterError("palette is missing PaperInkTheme field(s): " + ", ".join(missing))
    theme: dict[str, str] = {}
    for field in HEX_THEME_FIELDS:
        value = _text(palette[field], f"palette.{field}")
        if not HEX_COLOR.fullmatch(value):
            raise StyleAdapterError(f"palette.{field} must use #RRGGBB")
        theme[field] = value
    for field in SURFACE_THEME_FIELDS:
        theme[field] = _text(palette[field], f"palette.{field}")
    theme["fontFamily"] = _text(font.get("family"), "font.family")
    return theme


def _validate_safe_area(value: Any) -> dict[str, int]:
    source = _object(value, "safe_area")
    missing = [field for field in REQUIRED_SAFE_AREA_FIELDS if field not in source]
    if missing:
        raise StyleAdapterError("safe_area is missing field(s): " + ", ".join(missing))
    result: dict[str, int] = {}
    for field in REQUIRED_SAFE_AREA_FIELDS:
        raw = source[field]
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise StyleAdapterError(f"safe_area.{field} must be a non-negative integer")
        result[field] = raw
    if result["width"] <= 0 or result["height"] <= 0:
        raise StyleAdapterError("safe_area width and height must be positive")
    if result["left"] + result["right"] >= result["width"]:
        raise StyleAdapterError("safe_area left + right must leave readable width")
    if result["top"] + result["bottom"] >= result["height"]:
        raise StyleAdapterError("safe_area top + bottom must leave readable height")
    if result["subtitle_reserve_bottom"] > result["height"] - result["top"]:
        raise StyleAdapterError("safe_area subtitle_reserve_bottom exceeds usable height")
    return result


def _validate_texture(value: Any) -> dict[str, Any]:
    source = _object(value, "texture")
    result: dict[str, Any] = {"kind": _text(source.get("kind"), "texture.kind")}
    if "line_spacing_px" in source:
        spacing = source["line_spacing_px"]
        if not isinstance(spacing, int) or isinstance(spacing, bool) or spacing <= 0:
            raise StyleAdapterError("texture.line_spacing_px must be a positive integer")
        result["line_spacing_px"] = spacing
    return result


def _validate_motion(value: Any) -> dict[str, Any]:
    source = _object(value, "motion")
    intensity = _text(source.get("intensity"), "motion.intensity")
    if intensity not in {"low", "medium", "high"}:
        raise StyleAdapterError("motion.intensity must be low, medium, or high")
    allowed = _string_list(source.get("allowed_mechanisms"), "motion.allowed_mechanisms")
    forbidden = _string_list(source.get("forbidden_mechanisms"), "motion.forbidden_mechanisms", allow_empty=True)
    conflict = sorted(set(allowed).intersection(forbidden))
    if conflict:
        raise StyleAdapterError("motion allowed_mechanisms and forbidden_mechanisms conflict: " + ", ".join(conflict))
    return {
        "intensity": intensity,
        "allowed_mechanisms": allowed,
        "forbidden_mechanisms": forbidden,
    }


def build_style(project: Path | str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structured params and return deterministic Remotion-ready props.

    This function does not write files. It neither reads semantic meaning from
    design.md nor supplies a paper/light/dark fallback for missing fields.
    """
    project_root = Path(project).resolve()
    if not project_root.is_dir():
        raise StyleAdapterError("project must be an existing directory")
    if params.get("schema_version") != SCHEMA_VERSION:
        raise StyleAdapterError(f"schema_version must be {SCHEMA_VERSION}")
    if _text(params.get("design_source"), "design_source") != DESIGN_SOURCE:
        raise StyleAdapterError("design_source must be the project-relative design.md")
    design_path = _relative_project_path(project_root, DESIGN_SOURCE, "design_source")
    if not design_path.is_file():
        raise StyleAdapterError("project design.md is missing")
    expected_hash = _text(params.get("design_sha256"), "design_sha256").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise StyleAdapterError("design_sha256 must be a SHA-256 hex digest")
    actual_hash = _sha256(design_path)
    if actual_hash != expected_hash:
        raise DesignDriftError(
            "design.md SHA-256 differs from structured parameters; refusing to generate or overwrite style output"
        )
    palette = _object(params.get("palette"), "palette")
    font = _object(params.get("font"), "font")
    theme = _validate_theme(palette, font)
    safe_area = _validate_safe_area(params.get("safe_area"))
    texture = _validate_texture(params.get("texture"))
    motion = _validate_motion(params.get("motion"))
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter": "shotcraft_style.py",
        "design_binding": {"source": DESIGN_SOURCE, "sha256": actual_hash},
        "remotion_theme": theme,
        "component_props": {
            "theme": theme,
            "style": {
                "fontFamily": theme["fontFamily"],
                "texture": texture,
                "safeArea": safe_area,
                "motion": motion,
            },
        },
        "execution_boundary": [
            "Structured parameters were supplied by an executing assistant; design.md was not automatically interpreted.",
            "This map changes no project composition, old video, approval, provider, budget, manifest, or render.",
            "A current design_binding SHA-256 is required before use; drift requires a new human-reviewed structured parameter file.",
        ],
    }


def write_style(project: Path | str, params: Mapping[str, Any], output: str | Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    """Write one new style map, or return already-current without changing bytes."""
    project_root = Path(project).resolve()
    payload = build_style(project_root, params)
    output_path = _relative_project_path(project_root, str(output), "output")
    if output_path.suffix.lower() != ".json":
        raise StyleAdapterError("output must have a .json suffix")
    encoded = _json_bytes(payload)
    if output_path.exists():
        try:
            current = output_path.read_bytes()
        except OSError as error:
            raise StyleAdapterError(f"cannot read existing output: {error}") from error
        if current == encoded:
            return {"state": "already-current", "output": str(output_path), "design_sha256": payload["design_binding"]["sha256"]}
        raise OutputExistsError("refusing to overwrite existing different style output")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".shotcraft-style-", suffix=".json", dir=str(output_path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # A hard link is an atomic create-only commit in the same directory.  Unlike
        # os.replace(), it cannot replace a winner that appeared after the initial
        # exists() check.  The temporary bytes are already flushed and fsynced.
        try:
            os.link(temporary, output_path)
        except FileExistsError as error:
            raise OutputExistsError("refusing to overwrite style output created by another writer") from error
        except OSError as error:
            raise StyleAdapterError(f"cannot atomically create style output: {error}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"state": "written", "output": str(output_path), "design_sha256": payload["design_binding"]["sha256"]}


def _print(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def run(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("validate", "validate JSON and print the style map without writing"), ("write", "write a new project-local style map without overwriting")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--project", required=True, type=Path)
        command.add_argument("--params", required=True, type=Path, help="executing assistant's structured design JSON")
        if name == "write":
            command.add_argument("--output", default=str(DEFAULT_OUTPUT), help="project-relative output JSON path")
    args = parser.parse_args(arguments)
    try:
        params = _read_json(args.params, "structured style parameters")
        if args.command == "validate":
            _print(build_style(args.project, params))
        else:
            _print(write_style(args.project, params, args.output))
    except StyleAdapterError as error:
        _print({"passed": False, "error": str(error), "type": type(error).__name__})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
