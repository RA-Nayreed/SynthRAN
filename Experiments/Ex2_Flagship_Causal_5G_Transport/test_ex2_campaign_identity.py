"""Prevent revised science from silently resuming an earlier physical campaign."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran import experiments


class CampaignIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = {
            "design_version": 2,
            "resource": {"testbed_required": True},
            "study": {"transport_calibration": {"delivery_threshold": 0.98}},
        }
        self.environment = {"deployment_hash": "accepted-deployment", "attachment": {}}
        for target, value in [
            ("RESULTS_ROOT", self.root / "results"),
            ("_ACTIVE_ENDPOINTS", {"ex2": self.root / "active-ex2.json"}),
        ]:
            mocked = patch.object(experiments, target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_same_design_and_deployment_resume(self):
        original = experiments._new_campaign("ex2", self.manifest, self.environment)
        resumed = experiments._campaign_for_qualification("ex2", self.manifest, self.environment)
        self.assertEqual(original, resumed)
        self.assertTrue((original / "design-contract.json").is_file())

    def test_changed_threshold_starts_new_campaign_and_preserves_old(self):
        original = experiments._new_campaign("ex2", self.manifest, self.environment)
        original_bytes = (original / "campaign.json").read_bytes()
        revised = copy.deepcopy(self.manifest)
        revised["study"]["transport_calibration"]["delivery_threshold"] = 0.97
        with self.assertRaisesRegex(ValueError, "different or legacy scientific design"):
            experiments._active_campaign("ex2", self.environment, manifest=revised)
        replacement = experiments._campaign_for_qualification("ex2", revised, self.environment)
        self.assertNotEqual(original, replacement)
        self.assertEqual((original / "campaign.json").read_bytes(), original_bytes)

    def test_legacy_campaign_is_not_reused_after_design_revision(self):
        original = experiments._new_campaign("ex2", self.manifest, self.environment)
        path = original / "campaign.json"
        legacy = json.loads(path.read_text())
        legacy.pop("design_contract_sha256")
        path.write_text(json.dumps(legacy))
        replacement = experiments._campaign_for_qualification("ex2", self.manifest, self.environment)
        self.assertNotEqual(original, replacement)
        self.assertTrue(path.is_file())

    def test_version_and_deployment_are_both_part_of_reuse_contract(self):
        original = experiments._new_campaign("ex2", self.manifest, self.environment)
        revised = {**self.manifest, "design_version": 3}
        second = experiments._campaign_for_qualification("ex2", revised, self.environment)
        third = experiments._campaign_for_qualification(
            "ex2", revised, {**self.environment, "deployment_hash": "another-deployment"}
        )
        self.assertEqual(len({original, second, third}), 3)


if __name__ == "__main__":
    unittest.main()
