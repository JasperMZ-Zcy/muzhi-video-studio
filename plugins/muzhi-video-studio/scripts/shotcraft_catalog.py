#!/usr/bin/env python3
"""Read-only selector and integrity check for the local Shotcraft reference cards.

The module never renders, downloads, installs a CLI, calls a provider, or changes a
project. It only makes the small, pinned catalog searchable for a storyboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "assets" / "shotcraft" / "catalog.json"
DEFAULT_FULL_INDEX = ROOT / "assets" / "shotcraft" / "full-index.json"
REQUIRED_SOURCE_COMMIT = "5f047c7cfe10d6616fe59160a750fcfaea510b2e"
ALLOWED_STATUSES = {"reference-only", "locally_render_tested"}
STYLE_CONTRACT_ID = "project-design-required"
STYLE_RECORD = Path("artifacts") / "shotcraft-style-contract.json"


class CatalogError(ValueError):
    """Raised when the local reference catalog is incomplete or inconsistent."""


def _read_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read catalog: {error}") from error
    if not isinstance(value, dict):
        raise CatalogError("catalog must be a JSON object")
    return value


def _read_full_index(path: Path = DEFAULT_FULL_INDEX) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read full index: {error}") from error
    if not isinstance(value, dict):
        raise CatalogError("full index must be a JSON object")
    return value


def _git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def _entries(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    shots = catalog.get("shots")
    if not isinstance(shots, list):
        raise CatalogError("catalog shots must be a list")
    if not all(isinstance(shot, dict) for shot in shots):
        raise CatalogError("every catalog shot must be an object")
    return shots


def _full_entries(index: dict[str, Any]) -> list[dict[str, Any]]:
    cards = index.get("cards")
    if not isinstance(cards, list) or not all(isinstance(card, dict) for card in cards):
        raise CatalogError("full index cards must be a list of objects")
    return cards


def _all_entries(catalog: dict[str, Any], full_index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Merge the six reviewed local records over all pinned local text cards."""
    index = full_index if full_index is not None else _read_full_index()
    selected = {shot["id"]: shot for shot in _entries(catalog) if isinstance(shot.get("id"), str)}
    merged: list[dict[str, Any]] = []
    for indexed in _full_entries(index):
        identifier = indexed.get("id")
        if not isinstance(identifier, str):
            continue
        entry = dict(indexed)
        reviewed = selected.get(identifier)
        if reviewed is None:
            entry.update(
                {
                    "implementation_status": "reference-only",
                    "locally_render_tested": False,
                    "implementation_template": "none; local text card is an untested mechanism reference",
                    "source_license": "Apache-2.0",
                    "style_contract": STYLE_CONTRACT_ID,
                    "read_before_use": True,
                }
            )
        else:
            entry.update(reviewed)
            # Preserve the full local-text and fixed-preview metadata after the
            # reviewed record adds its stricter reuse conditions.
            for field in ("full_card_path", "local_card_sha256", "styles", "source_raw_url", "availability"):
                entry[field] = indexed[field]
            entry["read_before_use"] = True
        merged.append(entry)
    return merged


def validate_catalog(catalog: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Return deterministic catalog and vendored-card integrity errors."""
    errors: list[str] = []
    source = catalog.get("upstream")
    if not isinstance(source, dict) or source.get("commit") != REQUIRED_SOURCE_COMMIT:
        errors.append("catalog must pin the approved upstream commit")
    if not isinstance(source, dict) or source.get("license") != "Apache-2.0":
        errors.append("catalog must declare the Apache-2.0 upstream license")
    license_path = root / "assets" / "shotcraft" / "LICENSE"
    if not license_path.is_file():
        errors.append("vendored Apache-2.0 license is missing")
    elif not isinstance(source, dict) or _git_blob_sha1(license_path.read_bytes()) != source.get("license_blob_sha1"):
        errors.append("vendored Apache-2.0 license differs from the pinned upstream blob")
    style_contract = catalog.get("style_contract")
    required_style_fields = {"record_path", "required_fields", "precedence", "validation"}
    if not isinstance(style_contract, dict) or not required_style_fields.issubset(style_contract):
        errors.append("catalog must define the project style contract")
    public_release = catalog.get("release_scope") == "public-source-reference-only"
    if public_release:
        review = catalog.get("rights_review")
        if not isinstance(review, dict) or review.get("status") != "approved-for-public-source-distribution":
            errors.append("public catalog must retain its explicit rights review")

    seen: set[str] = set()
    for shot in _entries(catalog):
        shot_id = shot.get("id")
        if not isinstance(shot_id, str) or not shot_id:
            errors.append("shot id must be a non-empty string")
            continue
        if shot_id in seen:
            errors.append(f"duplicate shot id: {shot_id}")
        seen.add(shot_id)
        if shot.get("implementation_status") not in ALLOWED_STATUSES:
            errors.append(f"{shot_id}: invalid implementation_status")
        if not isinstance(shot.get("locally_render_tested"), bool):
            errors.append(f"{shot_id}: locally_render_tested must be boolean")
        if shot.get("implementation_status") == "reference-only" and shot.get("locally_render_tested"):
            errors.append(f"{shot_id}: reference-only card cannot be marked render tested")
        if public_release:
            review = shot.get("rights_review")
            if shot.get("public_export_eligible") is not True or shot.get("project_output_approved") is not False or shot.get("release_scope") != "apache-2.0-source-text-reference" or not isinstance(review, dict) or review.get("status") != "approved-for-public-source-distribution":
                errors.append(f"{shot_id}: public source-text release scope is incomplete")
        elif shot.get("public_export_eligible") is not False:
            errors.append(f"{shot_id}: private catalog records must remain non-public")
        if shot.get("source_license") != "Apache-2.0":
            errors.append(f"{shot_id}: source license is not recorded")
        if not isinstance(shot.get("implementation_template"), str):
            errors.append(f"{shot_id}: implementation_template must be a string")
        if shot.get("style_contract") != STYLE_CONTRACT_ID:
            errors.append(f"{shot_id}: must require the project design style contract")
        card_value = shot.get("vendored_card")
        blob_sha = shot.get("upstream_blob_sha1")
        if not isinstance(card_value, str) or not isinstance(blob_sha, str):
            errors.append(f"{shot_id}: card path or upstream hash is missing")
            continue
        card_path = root / card_value
        if not card_path.is_file():
            errors.append(f"{shot_id}: vendored card is missing")
            continue
        if _git_blob_sha1(card_path.read_bytes()) != blob_sha:
            errors.append(f"{shot_id}: vendored card differs from the pinned upstream blob")
        record_path = root / "assets" / "shotcraft" / "asset-records" / f"{shot_id}.json"
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{shot_id}: asset record is unavailable: {error}")
            continue
        if public_release:
            review = record.get("rights_review") if isinstance(record, dict) else None
            if not isinstance(record, dict) or record.get("public_export_eligible") is not True or record.get("project_output_approved") is not False or record.get("release_scope") != "apache-2.0-source-text-reference" or not isinstance(review, dict) or review.get("status") != "approved-for-public-source-distribution":
                errors.append(f"{shot_id}: public asset record scope is incomplete")
        elif not isinstance(record, dict) or record.get("public_export_eligible") is not False:
            errors.append(f"{shot_id}: private asset record must remain non-public")
        if not isinstance(record, dict) or REQUIRED_SOURCE_COMMIT not in str(record.get("source_project", "")):
            errors.append(f"{shot_id}: asset record does not preserve the pinned source")
    return errors


def validate_full_index(index: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Validate the complete local text index without downloading any media."""
    errors: list[str] = []
    source = index.get("upstream")
    if not isinstance(source, dict) or source.get("commit") != REQUIRED_SOURCE_COMMIT:
        errors.append("full index must pin the approved upstream commit")
        return errors
    if source.get("source_card_count") != 157:
        errors.append("full index must contain the verified 157 source cards")
    if source.get("gallery_style_count") != 214 or source.get("verified_style_count") != 214:
        errors.append("full index must retain the verified 214 gallery styles")
    public_release = index.get("release_scope") == "public-source-reference-only"
    if public_release:
        review = index.get("rights_review")
        if not isinstance(review, dict) or review.get("status") != "approved-for-public-source-distribution":
            errors.append("public full index must retain its explicit rights review")
    seen: set[str] = set()
    style_count = 0
    for entry in _full_entries(index):
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append("full index card id must be a non-empty string")
            continue
        if identifier in seen:
            errors.append(f"duplicate full index card id: {identifier}")
        seen.add(identifier)
        expected = {"category", "summary", "use_cases", "source_card_path", "source_raw_url", "upstream_blob_sha1", "full_card_path", "local_card_sha256"}
        if any(not entry.get(field) for field in expected):
            errors.append(f"{identifier}: complete search/source metadata is missing")
            continue
        if REQUIRED_SOURCE_COMMIT not in str(entry["source_raw_url"]):
            errors.append(f"{identifier}: source URL is not pinned to the approved commit")
        if public_release:
            review = entry.get("rights_review")
            if entry.get("public_export_eligible") is not True or entry.get("project_output_approved") is not False or entry.get("release_scope") != "apache-2.0-source-text-reference" or not isinstance(review, dict) or review.get("status") != "approved-for-public-source-distribution":
                errors.append(f"{identifier}: public release scope or rights review is missing")
        elif entry.get("public_export_eligible") is not False:
            errors.append(f"{identifier}: private source-text card may not claim rendered public-export eligibility")
        card_path = root / str(entry["full_card_path"])
        if not card_path.is_file():
            errors.append(f"{identifier}: full local text card is missing")
        elif hashlib.sha256(card_path.read_bytes()).hexdigest() != entry["local_card_sha256"]:
            errors.append(f"{identifier}: full local text card hash drift")
        styles = entry.get("styles")
        if not isinstance(styles, list):
            errors.append(f"{identifier}: styles must be a list")
        else:
            style_count += len(styles)
            if any(not isinstance(style, dict) or not style.get("key") or not str(style.get("preview_url", "")).startswith("https://vincentwei1021.github.io/video-shotcraft/media/") or style.get("preview_cached") is not False or style.get("preview_provenance") != "live-official-gallery-not-pinned-or-locally-verified" for style in styles):
                errors.append(f"{identifier}: preview metadata must be an explicit official live non-pinned link")
    if len(seen) != 157:
        errors.append("full index does not have exactly 157 unique cards")
    if style_count != 214:
        errors.append("full index style entries do not total 214")
    return errors


def validate_project_style(project: Path | str | None) -> dict[str, Any]:
    """Validate an executing-assistant style record against project design bytes.

    The function intentionally does not parse or claim to understand design.md. It
    checks only that the current executing assistant recorded the six required fields
    and that design.md still matches the recorded SHA-256.
    """
    if project is None:
        return {"passed": False, "state": "not-checked", "reason": "No project supplied; no library style fallback is permitted."}
    project_root = Path(project)
    record_path = project_root / STYLE_RECORD
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {"passed": False, "state": "missing", "project": str(project_root), "reason": f"An executing-assistant {STYLE_RECORD.as_posix()} record is required: {error}"}
    required = {"design_source", "design_sha256", "palette", "font", "safe_area", "motion_intensity"}
    if not isinstance(record, dict) or any(not isinstance(record.get(field), str) or not record[field].strip() for field in required):
        return {"passed": False, "state": "invalid", "project": str(project_root), "reason": "Style record must contain non-empty design_source, design_sha256, palette, font, safe_area, and motion_intensity."}
    source = Path(record["design_source"])
    if source.is_absolute() or ".." in source.parts or source.as_posix() != "design.md":
        return {"passed": False, "state": "invalid", "project": str(project_root), "reason": "Style record design_source must be the project-relative design.md."}
    design_path = project_root / source
    try:
        actual_hash = hashlib.sha256(design_path.read_bytes()).hexdigest()
    except OSError as error:
        return {"passed": False, "state": "missing", "project": str(project_root), "reason": f"Recorded design source is unavailable: {error}"}
    if actual_hash != record["design_sha256"].lower():
        return {"passed": False, "state": "drift", "project": str(project_root), "reason": "design.md changed after the style record. Review only affected planned shots; do not auto-rerender or change approvals.", "actual_design_sha256": actual_hash}
    return {"passed": True, "state": "matched", "project": str(project_root.resolve()), "style_record": STYLE_RECORD.as_posix(), "design_source": "design.md", "design_sha256": actual_hash, "precedence": ["project design.md", "brand-approved style", "motion recipe"]}


def search(catalog: dict[str, Any], terms: Iterable[str], category: str | None = None, full_index: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    words = [term.casefold() for term in terms if term.strip()]
    result: list[dict[str, Any]] = []
    for shot in _all_entries(catalog, full_index):
        if category and shot.get("category") != category:
            continue
        haystack = " ".join(
            [
                str(shot.get("id", "")),
                str(shot.get("title", "")),
                str(shot.get("purpose", "")),
                str(shot.get("search_text", "")),
                " ".join(str(tag) for tag in shot.get("tags", [])),
                " ".join(str(style.get("key", "")) + " " + str(style.get("label", "")) + " " + str(style.get("summary", "")) + " " + str(style.get("use", "")) for style in shot.get("styles", []) if isinstance(style, dict)),
            ]
        ).casefold()
        if all(word in haystack for word in words):
            result.append(shot)
    return result


def select(catalog: dict[str, Any], shot_ids: Iterable[str], project: Path | str | None = None, full_index: dict[str, Any] | None = None) -> dict[str, Any]:
    wanted = list(shot_ids)
    lookup = {shot["id"]: shot for shot in _all_entries(catalog, full_index) if isinstance(shot.get("id"), str)}
    unknown = [shot_id for shot_id in wanted if shot_id not in lookup]
    if unknown:
        raise CatalogError("unknown shot id: " + ", ".join(unknown))
    style_check = validate_project_style(project)
    return {
        "selection_type": "storyboard-reference-only",
        "selected": [lookup[shot_id] for shot_id in wanted],
        "source_reading_required": [
            {
                "id": lookup[shot_id]["id"],
                "local_text_card": lookup[shot_id]["full_card_path"],
                "pinned_source_url": lookup[shot_id]["source_raw_url"],
                "upstream_blob_sha1": lookup[shot_id]["upstream_blob_sha1"],
                "locally_render_tested": lookup[shot_id]["locally_render_tested"],
            }
            for shot_id in wanted
        ],
        "style_validation": style_check,
        "may_apply_to_project": style_check["passed"],
        "execution_boundary": [
            "This packet does not approve a project, render, provider, budget, or publication.",
            "Use only verified project facts; retain the existing voice, subtitle, cover, and quality contracts.",
            "Provider routing stays Google Flow manual, or configured Wan/MiniMax after project-level choice and budget authorization.",
        ],
    }


def read_cards(catalog: dict[str, Any], shot_ids: Iterable[str], full_index: dict[str, Any] | None = None, root: Path = ROOT) -> list[dict[str, Any]]:
    """Return only explicitly selected local text cards; never preloads the full library."""
    wanted = list(shot_ids)
    if not wanted or len(wanted) > 3:
        raise CatalogError("read accepts one to three comma-separated shot ids")
    lookup = {shot["id"]: shot for shot in _all_entries(catalog, full_index) if isinstance(shot.get("id"), str)}
    unknown = [shot_id for shot_id in wanted if shot_id not in lookup]
    if unknown:
        raise CatalogError("unknown shot id: " + ", ".join(unknown))
    result: list[dict[str, Any]] = []
    for shot_id in wanted:
        shot = lookup[shot_id]
        card_path = root / shot["full_card_path"]
        try:
            text = card_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CatalogError(f"cannot read selected local card {shot_id}: {error}") from error
        result.append(
            {
                "id": shot_id,
                "category": shot["category"],
                "local_text_card": shot["full_card_path"],
                "pinned_source_url": shot["source_raw_url"],
                "upstream_blob_sha1": shot["upstream_blob_sha1"],
                "locally_render_tested": shot["locally_render_tested"],
                "text": text,
            }
        )
    return result


def _compact(shot: dict[str, Any]) -> dict[str, Any]:
    styles = [style for style in shot.get("styles", []) if isinstance(style, dict)]
    return {
        "id": shot.get("id"),
        "category": shot.get("category"),
        "summary": shot.get("summary") or shot.get("purpose"),
        "use_cases": shot.get("use_cases") or shot.get("purpose"),
        "energy": shot.get("energy") or shot.get("intensity"),
        "availability": shot.get("availability"),
        "local_text_card": shot.get("full_card_path"),
        "style_keys": [style.get("key") for style in styles[:3]],
    }


def _limited(entries: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    if limit < 0:
        raise CatalogError("limit must be zero or a positive integer")
    returned = entries if limit == 0 else entries[:limit]
    return {
        "total_matches": len(entries),
        "returned": len(returned),
        "limit": limit,
        "items": [_compact(entry) for entry in returned],
        "next_step": "Use select for a storyboard candidate packet, then read --ids for one to three local card texts.",
    }


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run(arguments: list[str] | None = None, catalog_path: Path = DEFAULT_CATALOG) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=catalog_path, help="catalog JSON path; defaults to this plugin's pinned catalog")
    parser.add_argument("--full-index", type=Path, default=DEFAULT_FULL_INDEX, help="complete local fixed-commit card index")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check source, license, records, and vendored cards")
    style = commands.add_parser("validate-style", help="validate the executing-assistant project style record against design.md")
    style.add_argument("--project", required=True, type=Path, help="project root containing design.md and the style record")
    listing = commands.add_parser("list", help="list all cards or one upstream category")
    listing.add_argument("--category", help="camera, data, or ui-entrance")
    listing.add_argument("--limit", type=int, default=12, help="compact results to return; 0 returns every item")
    searching = commands.add_parser("search", help="search Chinese or English tags and purposes")
    searching.add_argument("terms", nargs="+", help="all terms must match")
    searching.add_argument("--category", help="optional upstream category")
    searching.add_argument("--limit", type=int, default=12, help="compact results to return; 0 returns every match")
    selecting = commands.add_parser("select", help="return a non-mutating storyboard candidate packet")
    selecting.add_argument("--ids", required=True, help="comma-separated IDs in intended storyboard order")
    selecting.add_argument("--project", type=Path, help="optional project root; missing style record keeps cards reference-only")
    reading = commands.add_parser("read", help="read one to three explicitly chosen local text cards")
    reading.add_argument("--ids", required=True, help="one to three comma-separated IDs")
    args = parser.parse_args(arguments)
    try:
        catalog = _read_catalog(args.catalog)
        full_index = _read_full_index(args.full_index)
        errors = validate_catalog(catalog, args.catalog.resolve().parents[2]) + validate_full_index(full_index, args.full_index.resolve().parents[2])
        if errors:
            _print({"passed": False, "errors": errors})
            return 1
        if args.command == "validate":
            _print({"passed": True, "reviewed_card_count": len(_entries(catalog)), "full_card_count": len(_full_entries(full_index)), "gallery_style_count": full_index["upstream"]["gallery_style_count"], "mode": "local-text validation; no media was fetched"})
        elif args.command == "validate-style":
            result = validate_project_style(args.project)
            _print(result)
            return 0 if result["passed"] else 1
        elif args.command == "list":
            _print(_limited(search(catalog, [], args.category, full_index), args.limit))
        elif args.command == "search":
            _print(_limited(search(catalog, args.terms, args.category, full_index), args.limit))
        elif args.command == "select":
            _print(select(catalog, [item for item in args.ids.split(",") if item], args.project, full_index))
        else:
            _print(read_cards(catalog, [item for item in args.ids.split(",") if item], full_index))
    except CatalogError as error:
        _print({"passed": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
