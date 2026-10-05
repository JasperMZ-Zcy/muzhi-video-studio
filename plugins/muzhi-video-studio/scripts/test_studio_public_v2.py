"""Portable studio example and public-only resource boundary."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import motion_plan
import production_runner
import resource_handoff


PLUGIN = Path(__file__).resolve().parents[1]
EXAMPLE = PLUGIN / "assets/examples/studio-authored-minimal"


class PublicStudioV2Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "new-user-example"
        shutil.copytree(EXAMPLE, self.project)
        self.plan = json.loads((self.project / "motion-plan.json").read_text(encoding="utf-8"))

    def test_only_public_sources_are_registered(self):
        self.assertEqual(set(resource_handoff.SOURCES),
                         {"shotcraft", "shotcraft_pilot", "semantic_action"})
        self.assertEqual(resource_handoff.read(["semantic_action:CountParticleFill"])[0]["indexed_hash_matches"], True)
        self.assertEqual(resource_handoff.read(["semantic_action:SceneCoordinate"])[0]["learning_evidence"]["execution_level"],
                         "adaptable_private_code_helper")

    def test_minimal_example_is_plan_only_with_real_public_search(self):
        self.assertTrue(motion_plan.validate(self.plan, self.project)["passed"])
        self.assertEqual(self.plan["segments"][0]["library_searches"][0],
                         resource_handoff.search_receipt(["条件", "待定"], per_source=1))
        result = production_runner.check_stage(self.project, "preview", workflow="studio")
        self.assertTrue(result["passed"])
        self.assertEqual(result["completion_state"], "plan_only")
        self.assertFalse(result["actual_media_ready"])
        self.assertFalse(result["delivery_ready"])
        self.assertTrue(result["resource_preflight"][0]["ready_for_handoff"])

    def test_fabricated_search_and_silent_v1_do_not_pass_new_plan(self):
        fake = copy.deepcopy(self.plan)
        fake["segments"][0]["library_searches"][0]["results"][0]["id"] = "shotcraft:not-a-result"
        self.assertFalse(motion_plan.validate(fake, self.project)["passed"])
        old = copy.deepcopy(self.plan)
        old["semantic_contract_version"] = 1
        self.assertFalse(motion_plan.validate(old, self.project)["passed"])

    def test_all_original_styles_have_bounded_notes_not_media_identity(self):
        addon = json.loads((PLUGIN / "assets/shotcraft/pinned-code-study.json").read_text(encoding="utf-8"))
        observations = [observation for card in addon["cards"].values()
                        for observation in card["bounded_gallery_observations"]]
        self.assertEqual(len(addon["cards"]), 157)
        self.assertEqual(len({observation["style_id"] for observation in observations}), 214)
        self.assertEqual(len(observations), 247)
        self.assertTrue(all(observation["same_version_source_media_verified"] is False
                            and "record_path" not in observation for observation in observations))


if __name__ == "__main__":
    unittest.main()
