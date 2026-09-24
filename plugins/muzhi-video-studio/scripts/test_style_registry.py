from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("style_registry.py")


def call(*args: str) -> tuple[int, dict]:
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    return result.returncode, json.loads(result.stdout)


class StyleRegistryTests(unittest.TestCase):
    def test_catalog_and_available_styles(self) -> None:
        code, value = call("catalog")
        self.assertEqual(code, 0)
        self.assertEqual({entry["id"] for entry in value["styles"]},
                         {"editorial-illustration", "archival-current-collage"})
        with tempfile.TemporaryDirectory() as temp:
            code, value = call("select", "--project", temp, "--style", "archival-current-collage",
                               "--mode", "production", "--reason", "test", "--new-project")
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "selected")
            self.assertTrue((Path(temp) / "artifacts" / "video-studio-style.json").exists())

    def test_select_status_and_revise_preserve_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, value = call("select", "--project", temp, "--style", "archival-current-collage",
                               "--mode", "trial", "--reason", "dynamic sample", "--new-project")
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "selected")
            code, value = call("status", "--project", temp)
            self.assertEqual(code, 0)
            self.assertEqual(value["lock"]["style"], "archival-current-collage")
            code, value = call("select", "--project", temp, "--style", "editorial-illustration",
                               "--mode", "production", "--reason", "silent change", "--new-project")
            self.assertEqual(code, 1)
            code, value = call("revise", "--project", temp, "--style", "editorial-illustration",
                               "--mode", "production", "--reason", "user changed project style")
            self.assertEqual(code, 0)
            self.assertEqual(value["lock"]["history"][0]["style"], "archival-current-collage")

    def test_legacy_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "artifacts"
            artifacts.mkdir()
            (artifacts / "editorial-plugin-state.json").write_text("{}", encoding="utf-8")
            code, value = call("status", "--project", temp)
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "legacy_inferred_no_write")
            self.assertFalse((artifacts / "video-studio-style.json").exists())

    def test_existing_project_without_old_state_requires_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "HANDOFF.md").write_text("old project", encoding="utf-8")
            code, value = call("status", "--project", temp)
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "unselected_requires_project_review")
            code, value = call("select", "--project", temp, "--style", "archival-current-collage",
                               "--mode", "production", "--reason", "must review")
            self.assertEqual(code, 1)
            self.assertEqual(value["status"], "blocked")
            code, value = call("select", "--project", temp, "--style", "archival-current-collage",
                               "--mode", "production", "--reason", "reviewed this existing project",
                               "--existing-project-reviewed")
            self.assertEqual(code, 0)
            self.assertEqual(value["lock"]["projectKind"], "existing_reviewed")


if __name__ == "__main__":
    unittest.main()
