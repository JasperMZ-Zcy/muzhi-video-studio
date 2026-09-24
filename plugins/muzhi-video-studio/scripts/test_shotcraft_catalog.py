#!/usr/bin/env python3
"""Independent stdlib tests for the small, pinned Shotcraft reference catalog."""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shotcraft_catalog as catalog  # noqa: E402


class ShotcraftCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = catalog._read_catalog()

    def test_pinned_catalog_and_vendored_cards_validate(self) -> None:
        self.assertEqual(catalog.validate_catalog(self.payload), [])
        self.assertEqual(self.payload["upstream"]["commit"], catalog.REQUIRED_SOURCE_COMMIT)
        self.assertEqual(len(self.payload["shots"]), 6)
        full_index = catalog._read_full_index()
        self.assertEqual(catalog.validate_full_index(full_index), [])
        self.assertEqual(len(full_index["cards"]), 157)
        self.assertEqual(full_index["upstream"]["gallery_style_count"], 214)

    def test_all_cards_stay_private_and_reference_only_until_real_evidence_exists(self) -> None:
        public_release = self.payload.get("release_scope") == "public-source-reference-only"
        for shot in self.payload["shots"]:
            with self.subTest(shot=shot["id"]):
                self.assertEqual(shot["public_export_eligible"], public_release)
                self.assertFalse(shot.get("project_output_approved", False))
                self.assertEqual(shot["implementation_status"], "reference-only")
                self.assertFalse(shot["locally_render_tested"])
                self.assertTrue(shot["implementation_template"])
                self.assertEqual(shot["style_contract"], catalog.STYLE_CONTRACT_ID)
                record = catalog.ROOT / "assets" / "shotcraft" / "asset-records" / f"{shot['id']}.json"
                saved = json.loads(record.read_text(encoding="utf-8"))
                self.assertEqual(saved["public_export_eligible"], public_release)
                self.assertFalse(saved.get("project_output_approved", False))

    def test_search_can_find_low_intensity_reading_card(self) -> None:
        found = catalog.search(self.payload, ["低强度", "逐项"])
        self.assertEqual([shot["id"] for shot in found], ["list-reveal"])

    def test_selection_is_explicitly_non_mutating_and_preserves_order(self) -> None:
        packet = catalog.select(self.payload, ["depth-layer-moves", "timeline-travel"])
        self.assertEqual(packet["selection_type"], "storyboard-reference-only")
        self.assertEqual([shot["id"] for shot in packet["selected"]], ["depth-layer-moves", "timeline-travel"])
        self.assertIn("does not approve", packet["execution_boundary"][0])

    def test_unreviewed_full_card_stays_local_text_reference(self) -> None:
        packet = catalog.select(self.payload, ["basic-3d-scene"])
        selected = packet["selected"][0]
        self.assertEqual(selected["availability"], "local-text-reference")
        self.assertEqual(selected["implementation_status"], "reference-only")
        self.assertFalse(selected["locally_render_tested"])
        self.assertTrue(packet["source_reading_required"][0]["local_text_card"].endswith("basic-3d-scene.md"))

    def test_validate_detects_false_production_claim(self) -> None:
        changed = copy.deepcopy(self.payload)
        changed["shots"][0]["locally_render_tested"] = True
        errors = catalog.validate_catalog(changed)
        self.assertIn("depth-layer-moves: reference-only card cannot be marked render tested", errors)

    def test_style_record_needs_a_human_summary_and_matching_design_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "artifacts").mkdir()
            (project / "design.md").write_text("# 手工确认的纸张、字体和字幕安全区\n", encoding="utf-8")
            design_hash = catalog.hashlib.sha256((project / "design.md").read_bytes()).hexdigest()
            (project / "artifacts" / "shotcraft-style-contract.json").write_text(json.dumps({"design_source": "design.md", "design_sha256": design_hash, "palette": "人工摘录", "font": "人工摘录", "safe_area": "人工摘录", "motion_intensity": "人工摘录"}), encoding="utf-8")
            self.assertTrue(catalog.validate_project_style(project)["passed"])
            self.assertTrue(catalog.select(self.payload, ["list-reveal"], project)["may_apply_to_project"])
            (project / "design.md").write_text("# 已经变更\n", encoding="utf-8")
            self.assertEqual(catalog.validate_project_style(project)["state"], "drift")

    def test_cli_lists_compact_data_cards_without_writing(self) -> None:
        stream = io.StringIO()
        with redirect_stdout(stream):
            exit_code = catalog.run(["list", "--category", "data", "--limit", "3"])
        self.assertEqual(exit_code, 0)
        result = json.loads(stream.getvalue())
        self.assertEqual(result["total_matches"], 13)
        self.assertEqual(result["returned"], 3)
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("summary", result["items"][0])

    def test_chinese_evidence_search_and_selected_read_are_bounded(self) -> None:
        found = catalog.search(self.payload, ["证据"])
        self.assertGreaterEqual(len(found), 3)
        cards = catalog.read_cards(self.payload, ["timeline-travel", "chart-live-moves"])
        self.assertEqual(len(cards), 2)
        self.assertIn("时间轴", cards[0]["text"])
        with self.assertRaises(catalog.CatalogError):
            catalog.read_cards(self.payload, ["timeline-travel", "chart-live-moves", "list-reveal", "basic-3d-scene"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
