#!/usr/bin/env python3
"""Stdlib tests for the non-rendering Shotcraft structured-style adapter."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shotcraft_style as adapter  # noqa: E402


LIGHT_PALETTE = {
    "paper": "#F4EFE5", "paperDeep": "#E7DED0", "ink": "#25211C", "inkSoft": "#756C60",
    "amber": "#B46D22", "amberSoft": "#E1BE8B", "rule": "#CFC4B3",
    "backgroundOverlay": "rgba(255,255,255,0.12)", "panelSurface": "rgba(255,253,247,0.68)",
    "promptSurface": "rgba(255,253,247,0.78)", "mutedSurface": "rgba(37,33,28,0.06)",
    "shadow": "0 18px 38px rgba(37,33,28,0.10)",
}

DEEP_PALETTE = {
    "paper": "#16130F", "paperDeep": "#292016", "ink": "#F5EBDD", "inkSoft": "#C8B9A4",
    "amber": "#D99038", "amberSoft": "#F0C486", "rule": "#675643",
    "backgroundOverlay": "rgba(255,255,255,0.04)", "panelSurface": "rgba(30,24,17,0.88)",
    "promptSurface": "rgba(42,33,23,0.92)", "mutedSurface": "rgba(245,235,221,0.08)",
    "shadow": "0 20px 44px rgba(0,0,0,0.38)",
}


def make_params(project: Path, palette: dict[str, str]) -> dict[str, object]:
    design_hash = hashlib.sha256((project / "design.md").read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "design_source": "design.md",
        "design_sha256": design_hash,
        "palette": palette,
        "font": {"family": "Noto Sans SC, sans-serif"},
        "texture": {"kind": "paper-lines", "line_spacing_px": 42},
        "safe_area": {"width": 720, "height": 1280, "left": 64, "right": 64, "top": 72, "bottom": 34, "subtitle_reserve_bottom": 170},
        "motion": {"intensity": "low", "allowed_mechanisms": ["layered-parallax", "timeline-cursor", "note-regroup"], "forbidden_mechanisms": ["full-frame-breathing", "strobe"]},
    }


class ShotcraftStyleTests(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory()
        Path(temporary.name, "design.md").write_text("# 明确由执行助手理解的设计\n", encoding="utf-8")
        return temporary

    def test_light_fixture_maps_every_paper_ink_theme_field(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            payload = adapter.build_style(project, make_params(project, LIGHT_PALETTE))
            self.assertEqual(payload["remotion_theme"], {**LIGHT_PALETTE, "fontFamily": "Noto Sans SC, sans-serif"})
            self.assertEqual(payload["component_props"]["theme"], payload["remotion_theme"])
            self.assertEqual(payload["component_props"]["style"]["safeArea"]["left"], 64)

    def test_deep_fixture_is_explicitly_mapped_not_replaced_by_paper_defaults(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            payload = adapter.build_style(project, make_params(project, DEEP_PALETTE))
            self.assertEqual(payload["remotion_theme"]["paper"], "#16130F")
            self.assertEqual(payload["remotion_theme"]["panelSurface"], "rgba(30,24,17,0.88)")
            self.assertEqual(payload["remotion_theme"]["shadow"], "0 20px 44px rgba(0,0,0,0.38)")

    def test_missing_required_surface_is_an_error_not_a_default(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            broken = make_params(project, copy.deepcopy(LIGHT_PALETTE))
            del broken["palette"]["promptSurface"]  # type: ignore[index]
            with self.assertRaisesRegex(adapter.StyleAdapterError, "promptSurface"):
                adapter.build_style(project, broken)

    def test_empty_forbidden_mechanisms_is_a_deliberate_valid_choice(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            params = make_params(project, LIGHT_PALETTE)
            params["motion"]["forbidden_mechanisms"] = []  # type: ignore[index]
            payload = adapter.build_style(project, params)
            self.assertEqual(payload["component_props"]["style"]["motion"]["forbidden_mechanisms"], [])

    def test_motion_lists_cannot_allow_and_forbid_the_same_mechanism(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            params = make_params(project, LIGHT_PALETTE)
            params["motion"]["forbidden_mechanisms"] = ["timeline-cursor"]  # type: ignore[index]
            with self.assertRaisesRegex(adapter.StyleAdapterError, "conflict: timeline-cursor"):
                adapter.build_style(project, params)

    def test_design_drift_does_not_overwrite_existing_output(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            params = make_params(project, LIGHT_PALETTE)
            target = project / "style-adapter" / "shotcraft-remotion-style.json"
            target.parent.mkdir()
            target.write_text('{"preserve":"these bytes"}\n', encoding="utf-8")
            (project / "design.md").write_text("# 已变更设计\n", encoding="utf-8")
            with self.assertRaises(adapter.DesignDriftError):
                adapter.write_style(project, params)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"preserve":"these bytes"}\n')

    def test_existing_different_output_is_never_overwritten(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            target = project / "style-adapter" / "shotcraft-remotion-style.json"
            target.parent.mkdir()
            target.write_text('{"old":true}\n', encoding="utf-8")
            with self.assertRaises(adapter.OutputExistsError):
                adapter.write_style(project, make_params(project, LIGHT_PALETTE))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"old":true}\n')

    def test_competing_writer_cannot_be_replaced_after_precheck(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            target = project / "style-adapter" / "shotcraft-remotion-style.json"

            def competing_link(_source: str | Path, destination: str | Path) -> None:
                Path(destination).write_bytes(b'{"winner":true}\n')
                raise FileExistsError("simulated competing writer")

            with mock.patch.object(adapter.os, "link", side_effect=competing_link):
                with self.assertRaises(adapter.OutputExistsError):
                    adapter.write_style(project, make_params(project, LIGHT_PALETTE))
            self.assertEqual(target.read_bytes(), b'{"winner":true}\n')

    def test_project_paths_cannot_escape(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            with self.assertRaisesRegex(adapter.StyleAdapterError, "project-relative"):
                adapter.write_style(project, make_params(project, LIGHT_PALETTE), "../outside.json")

    def test_write_and_identical_second_write_are_safe(self) -> None:
        with self.make_project() as location:
            project = Path(location)
            params = make_params(project, LIGHT_PALETTE)
            first = adapter.write_style(project, params)
            second = adapter.write_style(project, params)
            self.assertEqual(first["state"], "written")
            self.assertEqual(second["state"], "already-current")
            value = json.loads((project / "style-adapter" / "shotcraft-remotion-style.json").read_text(encoding="utf-8"))
            self.assertEqual(value["design_binding"]["sha256"], params["design_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
