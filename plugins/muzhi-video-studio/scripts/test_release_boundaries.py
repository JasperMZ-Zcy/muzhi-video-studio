"""Public distribution must not inherit local research, credentials or runtime."""
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


class ReleaseBoundaryTests(unittest.TestCase):
    def test_optional_motion_bridge_is_packaged_with_required_local_dependencies(self):
        for relative in (
            'scripts/agent_motion_bridge.py', 'scripts/motion_plan.py',
            'scripts/style_registry.py', 'assets/style-catalog.json',
            'skills/video-production/references/agent-motion.md',
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        # A Codex cache ends in a version directory, not the plugin name.
        self.assertEqual(manifest['name'], 'muzhi-video-studio')
        self.assertTrue((ROOT / manifest['skills']).is_dir())

    def test_no_external_agent_motion_source_or_private_runtime_is_distributed(self):
        forbidden = {'external', 'reference-library', '.venv', 'node_modules', 'author-video'}
        names = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z',
                                         '--', 'plugins/muzhi-video-studio'], cwd=REPO).decode('utf-8').split('\0')
        for name in (value for value in names if value):
            path = REPO / name
            if not path.is_file():
                continue
            self.assertFalse(set(path.relative_to(ROOT).parts) & forbidden, str(path.relative_to(ROOT)))
            self.assertNotIn(path.suffix.lower(), {'.key', '.pem', '.pfx', '.dpapi', '.onnx', '.safetensors'})

    def test_public_text_has_no_personal_machine_paths_or_literal_service_keys(self):
        pattern = re.compile(
            r'[A-Za-z]:[\\/]+Users[\\/]+(?:Administrator|ADMINI~1)\b'
            r'|\bsk-[A-Za-z0-9_-]{32,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b'
            r'|\bgithub_pat_[A-Za-z0-9_]{40,}\b'
            r'|projects[/\\]video-semantic-' + 'motion-upgrade', re.I)
        names = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'],
                                        cwd=REPO).decode('utf-8').split('\0')
        text_suffixes = {'.md', '.json', '.py', '.ps1', '.yml', '.yaml', '.js', '.cjs', '.mjs',
                         '.ts', '.tsx', '.svg', '.toml'}
        for name in (value for value in names if value):
            path = REPO / name
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            self.assertIsNone(pattern.search(path.read_text(encoding='utf-8-sig')), str(path.relative_to(REPO)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
