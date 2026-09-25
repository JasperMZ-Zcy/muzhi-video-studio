"""Windows junction boundary regression without requiring junction privileges."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generation_ledger
import project_state
import provider_router
import style_registry


class ArtifactsBoundaryTests(unittest.TestCase):
    def test_project_state_directories_reject_reported_junction(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "project"
            artifacts = project / "artifacts"
            artifacts.mkdir(parents=True)
            original = getattr(Path, "is_junction", lambda self: False)

            def reported_junction(candidate):
                return candidate == artifacts or original(candidate)

            with patch.object(Path, "is_junction", new=reported_junction, create=True):
                with self.assertRaises(style_registry.StyleError):
                    style_registry.lock_path(project)
                with self.assertRaises(project_state.ValidationError):
                    project_state._state_dir(project)
                with self.assertRaises(generation_ledger.ValidationError):
                    generation_ledger._state_dir(project)
                with self.assertRaises(provider_router.RouterError):
                    provider_router._state_path(project)


if __name__ == "__main__":
    unittest.main()
