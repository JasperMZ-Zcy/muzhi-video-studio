"""Temporary, offline fixtures for the read-only FredTalk bridge."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("fredtalk_bridge.py")
REQUIRED = (
    "README.md",
    "skills/fred-remotion-output/SKILL.md",
    "skills/fred-remotion-output/DESIGN.md",
    "library/catalog.json",
    "skills/fred-remotion-output/scripts/scene.py",
    "skills/fred-remotion-output/scripts/library_gate.py",
    "skills/fred-remotion-output/scripts/validate_production_gate.py",
    "skills/fred-remotion-output/templates/component-kit/package.json",
)


def call(*args: str, extra_env: dict[str, str] | None = None) -> tuple[int, dict]:
    env = os.environ.copy()
    env.pop("FREDTALK_ROOT", None)
    env.pop("FREDTALK_RENDERER", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    run = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env, check=False)
    return run.returncode, json.loads(run.stdout)


def source(root: Path) -> Path:
    for relative in REQUIRED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    (root / "library/catalog.json").write_text(
        json.dumps({"schemaVersion": 1, "items": [{"id": "one"}, {"id": "two"}]}), encoding="utf-8")
    return root


def renderer(root: Path, packages: tuple[str, ...]) -> Path:
    for name in packages:
        path = root / "node_modules" / name / "package.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": name, "version": "1.2.3"}), encoding="utf-8")
    return root


def locked_project(root: Path, style: str = "fredtalk-native",
                   workflow: str = "fredtalk-native") -> Path:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "video-studio-style.json").write_text(
        json.dumps({"schemaVersion": 1, "style": style, "workflow": workflow}), encoding="utf-8")
    return root


class FredTalkBridgeTests(unittest.TestCase):
    def test_no_root_is_blocked_without_guessing(self) -> None:
        code, value = call("status")
        self.assertEqual(code, 1)
        self.assertEqual(value["status"], "blocked")
        self.assertIn("--root", value["reason"])

    def test_missing_source_file_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = source(Path(temp))
            (root / "skills/fred-remotion-output/scripts/scene.py").unlink()
            code, value = call("status", "--root", str(root))
            self.assertEqual(code, 1)
            self.assertIn("scene.py", value["reason"])

    def test_valid_source_without_renderer_is_planning_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = source(Path(temp))
            code, value = call("status", extra_env={"FREDTALK_ROOT": str(root)})
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "ready_for_planning")
            self.assertEqual(value["renderEnvironment"]["status"], "unchecked")
            catalog_path = root / "library/catalog.json"
            self.assertEqual(value["source"]["catalog"]["itemCount"], 2)
            self.assertEqual(value["source"]["catalog"]["sha256"],
                             hashlib.sha256(catalog_path.read_bytes()).hexdigest())
            self.assertEqual(len(value["source"]["sourcePackageDirectoriesPresent"]), 2)
            self.assertIn("not a count of usable", value["source"]["catalog"]["note"])

    def test_renderer_missing_and_present_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = source(base / "source")
            remotion = renderer(base / "renderer", ("remotion", "react"))
            code, value = call("status", "--root", str(root), "--renderer", str(remotion))
            self.assertEqual(code, 0)
            self.assertEqual(value["renderEnvironment"]["status"], "missing")
            self.assertIsNone(value["renderEnvironment"]["packageVersions"]["typescript"])
            renderer(remotion, ("typescript",))
            code, value = call("status", "--root", str(root),
                               extra_env={"FREDTALK_RENDERER": str(remotion)})
            self.assertEqual(code, 0)
            self.assertEqual(value["renderEnvironment"]["status"], "dependencies_present")
            self.assertIn("FFmpeg", value["renderEnvironment"]["note"])
            (remotion / "node_modules/react/package.json").write_text(
                json.dumps({"name": "another-package", "version": "1.2.3"}), encoding="utf-8")
            code, value = call("status", "--root", str(root), "--renderer", str(remotion))
            self.assertEqual(code, 0)
            self.assertEqual(value["renderEnvironment"]["status"], "missing")

    def test_project_lock_is_read_only_and_wrong_styles_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = source(base / "source")
            project = locked_project(base / "project", style="editorial-illustration")
            lock = project / "artifacts/video-studio-style.json"
            before = lock.read_bytes()
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 1)
            self.assertIn("another style", value["reason"])
            self.assertEqual(lock.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in (project / "artifacts").iterdir()),
                             ["video-studio-style.json"])

    def test_fred_lock_needs_matching_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = source(base / "source")
            project = locked_project(base / "project", workflow="editorial")
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 1)
            self.assertIn("workflow", value["reason"])
            locked_project(project)
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 0)
            self.assertEqual(value["project"]["style"], "fredtalk-native")
            self.assertTrue(value["project"]["readOnly"])

    def test_unselected_project_and_bad_lock_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = source(base / "source")
            project = base / "project"
            project.mkdir()
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 1)
            self.assertIn("no selected", value["reason"])
            lock = locked_project(project) / "artifacts/video-studio-style.json"
            lock.write_text("{", encoding="utf-8")
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 1)
            self.assertEqual(value["status"], "blocked")
            lock.write_text("[]", encoding="utf-8")
            code, value = call("status", "--root", str(root), "--project", str(project))
            self.assertEqual(code, 1)
            self.assertEqual(value["status"], "blocked")

    def test_malformed_catalog_and_schema_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = source(Path(temp))
            catalog = root / "library/catalog.json"
            for body in ("{", "[]", '{"schemaVersion":2,"items":[]}',
                         '{"schemaVersion":1,"items":{}}',
                         '{"schemaVersion":1,"items":[null]}'):
                with self.subTest(body=body):
                    catalog.write_text(body, encoding="utf-8")
                    code, value = call("status", "--root", str(root))
                    self.assertEqual(code, 1)
                    self.assertEqual(value["status"], "blocked")

    def test_invalid_paths_return_blocked_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = source(base / "source")
            file_path = base / "not-a-directory"
            file_path.write_text("x", encoding="utf-8")
            for args in (("--root", str(base / "absent")),
                         ("--root", str(file_path)),
                         ("--root", str(root), "--renderer", str(base / "absent")),
                         ("--root", str(root), "--project", str(file_path))):
                with self.subTest(args=args):
                    code, value = call("status", *args)
                    self.assertEqual(code, 1)
                    self.assertEqual(value["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
