#!/usr/bin/env python3
"""Independent stdlib tests for project_state.py.

Run with: python scripts/test_project_state.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_state as state  # noqa: E402


class ProjectStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: bytes | str) -> Path:
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return target

    def init(self) -> dict:
        value, created = state.initialize_project(self.root)
        self.assertTrue(created)
        return value

    def test_init_idempotence_and_does_not_touch_project_json(self) -> None:
        original = '{"legacy": true}\n'
        self.write("project.json", original)
        initial = self.init()
        again, created = state.initialize_project(self.root)
        self.assertFalse(created)
        self.assertEqual(initial, again)
        self.assertEqual((self.root / "project.json").read_text(encoding="utf-8"), original)
        self.assertEqual(initial["schema"], 1)
        self.assertEqual(initial["version"], "1.1.0")

    def test_status_inspects_without_claiming_migration(self) -> None:
        self.write("project.json", '{"legacy": true}')
        self.write("job-card.json", '{"title": "old job"}')
        result = state.read_status(self.root)
        self.assertIsNone(result["state"])
        self.assertEqual(result["migration"]["status"], "not_claimed_migrated")
        self.assertFalse((self.root / "artifacts" / state.STATE_FILENAME).exists())
        self.assertTrue(result["migration"]["project_json"]["exists"])
        self.assertEqual(len(result["migration"]["job_cards"]), 1)

    def test_status_reads_real_named_markdown_and_bom_legacy_status_without_defaulting(self) -> None:
        (self.root / "artifacts").mkdir()
        (self.root / "project.json").write_text(
            '{"current":{"status":"scheduled"},"production":{"currentGate":"release"},'
            '"publication":{"status":"queued"},"secret":"do not expose"}',
            encoding="utf-8-sig",
        )
        (self.root / "artifacts" / "editorial-job-card.md").write_text(
            "# 已有视频项目\n\n当前状态: scheduled\n\nA long body is intentionally not returned.", encoding="utf-8-sig"
        )
        (self.root / "HANDOFF.md").write_text("# 交接\n\n阶段: review", encoding="utf-8-sig")
        result = state.read_status(self.root)
        legacy = result["migration"]["project_json"]["selected"]
        self.assertEqual(legacy["current_status"], "scheduled")
        self.assertEqual(legacy["production_current_gate"], "release")
        self.assertEqual(legacy["publication_status"], "queued")
        visible = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("planning", visible)
        self.assertNotIn("do not expose", visible)
        cards = {item["path"]: item for item in result["migration"]["job_cards"]}
        self.assertEqual(cards["artifacts/editorial-job-card.md"]["title"], "已有视频项目")
        self.assertEqual(cards["artifacts/editorial-job-card.md"]["status_hint"], "scheduled")
        self.assertEqual(cards["HANDOFF.md"]["status_hint"], "review")

    def test_lock_approve_and_verify_bind_the_same_hash(self) -> None:
        asset = self.write("media/voice.wav", b"approved audio")
        self.init()
        state.lock_asset(self.root, "voice.main", asset)
        approved = state.approve_asset(self.root, "voice.main", "Approved voice take")
        self.assertFalse(approved["idempotent"])
        verified = state.verify_asset(self.root, "voice.main")
        self.assertTrue(verified["verified"])
        # Same bytes create no duplicate approval or fresh confirmation record.
        repeated = state.approve_asset(self.root, "voice.main", "different repeat quote")
        self.assertTrue(repeated["idempotent"])
        saved = state.read_state(self.root)
        self.assertEqual(len(saved["approvals"]["voice.main"]), 1)

    def test_verify_refuses_hash_drift(self) -> None:
        asset = self.write("media/voice.wav", b"take one")
        self.init()
        state.lock_asset(self.root, "voice.main", asset)
        state.approve_asset(self.root, "voice.main", "Approved")
        asset.write_bytes(b"take two")
        with self.assertRaises(state.HashDriftError):
            state.verify_asset(self.root, "voice.main")

    def test_hash_only_verifies_locked_bytes_without_claiming_approval(self) -> None:
        asset = self.write("media/qc.wav", b"locked but awaiting visual approval")
        self.init()
        state.lock_asset(self.root, "voice.qc", asset)
        with self.assertRaises(state.ApprovalError):
            state.verify_asset(self.root, "voice.qc")

        checked = state.verify_asset(self.root, "voice.qc", require_approval=False)
        self.assertTrue(checked["verified"])
        self.assertFalse(checked["approved"])
        self.assertIsNone(checked["approval"])
        cli_checked = state.run(
            ["verify", "--project", str(self.root), "--key", "voice.qc", "--hash-only"]
        )
        self.assertFalse(cli_checked["approved"])

        asset.write_bytes(b"modified after QC")
        with self.assertRaises(state.HashDriftError):
            state.verify_asset(self.root, "voice.qc", require_approval=False)

    def test_lock_refuses_source_outside_project(self) -> None:
        outside = Path(self.temporary.name) / "outside.wav"
        outside.write_bytes(b"outside")
        self.init()
        with self.assertRaises(state.ValidationError):
            state.lock_asset(self.root, "voice.main", outside)

    def test_scheduled_is_not_published_and_published_requires_real_metadata(self) -> None:
        self.init()
        result = state.set_stage(self.root, "scheduled", quote="Schedule this")
        self.assertEqual(result["state"]["stage"], "scheduled")
        self.assertNotIn("publication", result["state"])
        with self.assertRaises(state.ValidationError):
            state.set_stage(self.root, "published", quote="Publish now")
        published = state.set_stage(
            self.root,
            "published",
            quote="Published after check",
            post_id="post-17",
            platform="Bilibili",
            published_at="2026-09-08T12:00:00Z",
        )
        self.assertEqual(published["state"]["publication"]["post_id"], "post-17")

    def test_published_rejects_non_iso_or_timezone_less_timestamp(self) -> None:
        self.init()
        for invalid in ("tonight", "2026-09-08T12:00:00"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(state.ValidationError):
                    state.set_stage(
                        self.root,
                        "published",
                        quote="Publish now",
                        post_id="post-17",
                        platform="Bilibili",
                        published_at=invalid,
                    )

    def test_cover_impact_is_intentionally_small(self) -> None:
        self.assertEqual(state.plan_change("covers")["affected"], ["covers", "release"])

    def test_overrides_are_project_local_and_sensitive_areas_are_rejected(self) -> None:
        self.init()
        state.set_override(self.root, "project", "visuals.palette", '["cream", "red"]', "Use approved palette")
        state.set_override(
            self.root,
            "revision",
            "captions.max_lines",
            "2",
            "Short captions for this revision",
            revision_id="r-2",
        )
        saved = state.read_state(self.root)
        self.assertIn("visuals.palette", saved["overrides"]["project"])
        self.assertIn("r-2", saved["overrides"]["revisions"])
        self.assertNotIn("captions.max_lines", saved["overrides"]["project"])
        with self.assertRaises(state.ValidationError):
            state.set_override(self.root, "project", "publication.platform", '"x"', "No")
        with self.assertRaises(state.ValidationError):
            state.set_override(self.root, "project", "visuals.rules", '{"token": "x"}', "No")

    def test_project_version_stays_pinned_through_mutations(self) -> None:
        initial = self.init()
        self.write("a.txt", "A")
        state.lock_asset(self.root, "copy", "a.txt")
        state.set_stage(self.root, "review")
        saved = state.read_state(self.root)
        self.assertEqual(saved["version"], initial["version"])
        self.assertEqual(saved["plugin_version"], "1.1.0")

    def test_package_rejects_basename_collision_without_partial_write(self) -> None:
        self.write("one/cover.png", b"one")
        self.write("two/cover.png", b"two")
        destination = Path(self.temporary.name) / "delivery"
        manifest = json.dumps({"files": ["one/cover.png", "two/cover.png"]})
        with self.assertRaises(state.ValidationError):
            state.package_files(self.root, manifest, destination)
        self.assertFalse(destination.exists())

    def test_package_rejects_different_existing_file_without_partial_write(self) -> None:
        self.write("one/cover.png", b"new cover")
        self.write("one/script.txt", b"script")
        destination = Path(self.temporary.name) / "delivery"
        destination.mkdir()
        (destination / "cover.png").write_bytes(b"old cover")
        manifest = json.dumps(["one/cover.png", "one/script.txt"])
        with self.assertRaises(state.ValidationError):
            state.package_files(self.root, manifest, destination)
        self.assertFalse((destination / "script.txt").exists())
        self.assertEqual((destination / "cover.png").read_bytes(), b"old cover")

    def test_package_is_flat_and_rejects_outside_and_secret_paths(self) -> None:
        self.write("renders/preview.mp4", b"video")
        self.write(".env", b"NO")
        destination = Path(self.temporary.name) / "delivery"
        result = state.package_files(self.root, json.dumps(["renders/preview.mp4"]), destination)
        self.assertEqual(result["copied"], ["preview.mp4"])
        self.assertTrue((destination / "preview.mp4").is_file())
        self.assertEqual(result["hashes"]["preview.mp4"], state._sha256(destination / "preview.mp4"))
        with self.assertRaises(state.ValidationError):
            state.package_files(self.root, json.dumps(["../outside.txt"]), Path(self.temporary.name) / "other")
        with self.assertRaises(state.ValidationError):
            state.package_files(self.root, json.dumps([".env"]), Path(self.temporary.name) / "other")

    def test_state_and_package_refuse_reported_symlink_boundaries(self) -> None:
        # This Windows environment does not grant symlink creation permission.
        # Simulating a filesystem-reported link nevertheless tests the bounded
        # path checks deterministically on every supported machine.
        artifacts_link = self.root.resolve() / "artifacts"
        real_is_symlink = Path.is_symlink

        def artifacts_reported_as_link(candidate: Path) -> bool:
            return candidate == artifacts_link or real_is_symlink(candidate)

        with patch.object(state.Path, "is_symlink", new=artifacts_reported_as_link):
            with self.assertRaises(state.ValidationError):
                state.initialize_project(self.root)

        # A package may not use an apparently local path whose parent is
        # reported as a link to another location.
        project_two = Path(self.temporary.name) / "project-two"
        project_two.mkdir()
        (project_two / "asset.txt").write_text("safe", encoding="utf-8")
        output_link = Path(self.temporary.name).resolve() / "output-link"

        def output_parent_reported_as_link(candidate: Path) -> bool:
            return candidate == output_link or real_is_symlink(candidate)

        with patch.object(state.Path, "is_symlink", new=output_parent_reported_as_link):
            with self.assertRaises(state.ValidationError):
                state.package_files(project_two, '["asset.txt"]', output_link / "delivery")

    def test_revision_guard_refuses_stale_writer(self) -> None:
        initial = self.init()
        state.set_stage(self.root, "assets", expected_revision=initial["revision"])
        with self.assertRaises(state.RevisionConflict):
            state.set_stage(self.root, "editing", expected_revision=initial["revision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
