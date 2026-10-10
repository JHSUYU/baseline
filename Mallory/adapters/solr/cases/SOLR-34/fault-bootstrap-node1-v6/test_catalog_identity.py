"""Actual v5 loaded-agent site IDs and negative controls for the v6 fix."""

import copy
import json
import unittest
from pathlib import Path

import bootstrap_policy as policy
import run_campaign

HERE = Path(__file__).resolve().parent


class LoadedCatalogIdentityTest(unittest.TestCase):
    def setUp(self):
        self.rows = [json.loads(line) for line in
                     (HERE / "loaded-v5-sites.jsonl").read_text().splitlines() if line.strip()]
        self.config = json.loads((HERE / "config-full-node1.json").read_text())

    def test_actual_loaded_agent_has_all_exact_target_ids(self):
        run_campaign.validate_loaded_catalog(self.rows, self.config)
        throws = [row["site"] for row in self.rows if row["type"] == "TARGET_THROW"]
        self.assertEqual([policy.RETHROW, policy.NEW_THROW], throws)

    def test_old_143_throw_one_is_rejected_in_config(self):
        old = copy.deepcopy(self.config)
        old["target"]["throw_site"] = policy.REGION + "@143:throw:1"
        with self.assertRaisesRegex(ValueError, "config target"):
            run_campaign.validate_loaded_catalog(self.rows, old)

    def test_old_143_throw_one_is_rejected_in_catalog(self):
        old = copy.deepcopy(self.rows)
        for row in old:
            if row["site"] == policy.NEW_THROW:
                row["site"] = policy.REGION + "@143:throw:1"
        with self.assertRaisesRegex(ValueError, "exact five IDs"):
            run_campaign.validate_loaded_catalog(old, self.config)

    def test_mixed_loader_or_untyped_door_is_rejected(self):
        wrong_loader = copy.deepcopy(self.rows)
        wrong_loader[0]["class_loader_id"] = "different-loader"
        with self.assertRaisesRegex(ValueError, "loaded target class"):
            run_campaign.validate_loaded_catalog(wrong_loader, self.config)
        untyped = copy.deepcopy(self.rows)
        next(row for row in untyped if row["type"] == "DOOR_OBSERVED")[
            "exception_class"] = "java.io.IOException"
        with self.assertRaisesRegex(ValueError, "loaded target class"):
            run_campaign.validate_loaded_catalog(untyped, self.config)


if __name__ == "__main__":
    unittest.main()
