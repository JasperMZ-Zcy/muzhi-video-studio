#!/usr/bin/env python3
"""Public-package boundaries for the text-only Shotcraft release."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOTCRAFT = ROOT / "assets" / "shotcraft"


class PublicShotcraftReleaseTests(unittest.TestCase):
    def test_all_released_cards_have_apache_scope_and_four_part_review(self) -> None:
        index = json.loads((SHOTCRAFT / "full-index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["release_scope"], "public-source-reference-only")
        self.assertEqual(index["rights_review"]["status"], "approved-for-public-source-distribution")
        self.assertEqual(len(index["cards"]), 157)
        for card in index["cards"]:
            with self.subTest(card=card["id"]):
                self.assertEqual(card["release_scope"], "apache-2.0-source-text-reference")
                self.assertEqual(card["rights_review"]["status"], "approved-for-public-source-distribution")
                self.assertTrue(card["public_export_eligible"])
                self.assertFalse(card["project_output_approved"])
                self.assertTrue((ROOT / card["full_card_path"]).is_file())

    def test_generic_source_does_not_embed_local_credentials_or_machine_paths(self) -> None:
        forbidden = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+|credentials\.aesgcm|WORKBENCH_SYNC_TOKEN|MINIMAX_API_KEY|WAN_ACCESS_KEY|\.wan[\\/]config", re.I)
        files = [
            SHOTCRAFT / "PUBLIC-REUSE-RECORD.json",
            SHOTCRAFT / "templates" / "knowledge-pilot" / "PUBLIC-REUSE-RECORD.json",
            *sorted((SHOTCRAFT / "templates" / "knowledge-pilot" / "src").glob("*.tsx")),
            SHOTCRAFT / "templates" / "knowledge-pilot" / "render-sample.mjs",
            ROOT / "scripts" / "shotcraft_catalog.py",
            ROOT / "scripts" / "motion_plan.py",
            ROOT / "scripts" / "shotcraft_style.py",
        ]
        for path in files:
            with self.subTest(path=path.name):
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
