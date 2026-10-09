"""The full checklist keeps explicit admission reasons for unrun cases."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from Mallory.dispatch.campaign_queue import refresh, sha256


class CampaignQueueTest(unittest.TestCase):
    def test_unrun_and_ineligible_cases_are_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"cases": [
                {"case_id": "HBASE-01", "system": "hbase", "eligibility": {
                    "state": "ready_for_healthy_seed", "may_dispatch_healthy_seed": True}},
                {"case_id": "HBASE-07", "system": "hbase", "eligibility": {
                    "state": "ready_for_healthy_seed", "may_dispatch_healthy_seed": True}},
                {"case_id": "HBASE-11", "system": "hbase", "eligibility": {
                    "state": "no_mapped_cluster_test", "may_dispatch_healthy_seed": False,
                    "mapping_gaps": ["no_source_mapped_cluster_test"]}},
            ]}), encoding="utf-8")
            reference = root / "source-reference.json"
            reference.write_text(json.dumps({"inventory_sha256": sha256(inventory)}),
                                 encoding="utf-8")
            result = refresh(host="node1", inventory_path=inventory,
                             source_reference_path=reference,
                             config_template=str(root / "configs/{case_id}.json"),
                             data_root=root / "data", cohort="v2",
                             output=root / "ready.json", promoted_root=root / "promoted",
                             exclude_cases={"HBASE-01"})
            states = {row["case_id"]: row["state"] for row in result["cases"]}
            self.assertEqual("held_externally", states["HBASE-01"])
            self.assertEqual("healthy_config_missing", states["HBASE-07"])
            self.assertEqual("source_or_workload_ineligible", states["HBASE-11"])
            self.assertEqual(3, len(states))


if __name__ == "__main__":
    unittest.main()
