"""Read-only checks of the four already launched native campaign bindings."""

from __future__ import annotations

import unittest

from .audit import audit


class ExistingCampaignPreflightTest(unittest.TestCase):
    def test_existing_campaigns_have_distinct_native_roots_and_trial_scratch(self) -> None:
        result = audit()
        cases = {row["case_id"]: row for row in result["cases"]}
        self.assertEqual(set(cases), {
            "ZOOKEEPER-07", "HDFS-11", "SOLR-01", "HBASE-02"})
        self.assertEqual(
            {case_id: row["owner"] for case_id, row in cases.items()},
            {"ZOOKEEPER-07": "node0", "HDFS-11": "node0",
             "SOLR-01": "node1", "HBASE-02": "node2"})
        self.assertEqual(len({row["state_path"] for row in cases.values()}), 4)
        self.assertEqual(len({row["first_trial_workdir"] for row in cases.values()}), 4)
        self.assertTrue(all(row["isolated_junit_process_receipts"] > 0
                            for row in cases.values()))
        self.assertTrue(all(row["adopt_now"] is False
                            for row in cases.values()))
        self.assertEqual(result["node0_port_check"]["observed_overlap"], [])

    def test_hdfs_terminal_review_is_preserved_without_quality_upgrade(self) -> None:
        result = audit()
        hdfs = result["hdfs_terminal_review"]
        self.assertEqual(hdfs["status"],
                         "budget_terminal_not_high_quality_complete")
        self.assertEqual(hdfs["strict_target_retained_trials"], 15)
        self.assertEqual(hdfs["target_exception_triggered"], 0)
        self.assertEqual(hdfs["new_closure_edge_families_sum"], 0)


if __name__ == "__main__":
    unittest.main()
