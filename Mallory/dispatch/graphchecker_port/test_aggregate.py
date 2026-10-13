import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from Mallory.dispatch.graphchecker_port.aggregate import (
    DEFAULT_QUALITY_FILE, ReceiptReader, _quality_rows, aggregate, render_tsv,
)
from Mallory.dispatch.graphchecker_port.plan import sha256

INVENTORY = Path(__file__).parents[3] / "Mallory/cases/inventory.json"


class AggregateTest(unittest.TestCase):
    def make_roots(self, root: Path):
        configs = root / "configs"
        states = root / "cases"
        configs.mkdir()
        states.mkdir()
        return configs, states

    def test_102_rows_with_exact_target_and_native_candidate_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            configs, states = self.make_roots(Path(temporary))
            config = configs / "HBASE-01.json"
            config.write_text(json.dumps({"case_id": "HBASE-01", "junit": {
                "class": "org.example.ClusterTest", "method": "testLookup"}}),
                encoding="utf-8")
            digest = sha256(config)
            case = states / "HBASE-01"
            case.mkdir()
            trials = [{"strict_injection": True,
                       "post_fault_target_reached": True,
                       "target_exception_triggered": True,
                       "target_exception_candidate": True},
                      {"strict_injection": False,
                       "post_fault_target_reached": False,
                       "target_exception_triggered": False,
                       "target_exception_candidate": False}]
            checkpoint = {"schema_version": 1, "case_id": "HBASE-01",
                          "config_sha256": digest, "status": "complete_trial_budget",
                          "terminal": True, "completed_fault_trials": 2,
                          "trial_elapsed_seconds": 14.25, "trials": trials}
            summary = {"schema_version": 1, "case_id": "HBASE-01",
                       "config_sha256": digest, "status": "complete_trial_budget",
                       "terminal": True, "completed_fault_trials": 2,
                       "trial_elapsed_seconds": 14.25, "strict_trials": 1,
                       "post_fault_target_trials": 1,
                       "target_exception_triggered_trials": 1,
                       "differential_candidates": 1}
            (case / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            (case / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            rows = aggregate(INVENTORY, configs, states,
                             ReceiptReader(states, remote=False))
            self.assertEqual(102, len(rows))
            by_id = {row["case_id"]: row for row in rows}
            result = by_id["HBASE-01"]
            self.assertEqual("org.apache.hadoop.hbase.client.ConnectionImplementation",
                             result["target_class"])
            self.assertEqual(1106, result["target_line"])
            self.assertTrue(result["target_method"].startswith("locateRegionInMeta("))
            self.assertEqual("org.example.ClusterTest#testLookup", result["junit_workload"])
            self.assertEqual(2, result["completed_fault_trials"])
            self.assertEqual(1, result["strict_post_fault_target_trials"])
            self.assertEqual(14.25, result["elapsed_seconds"])
            self.assertEqual("candidate", result["bug_review_mark"])
            self.assertEqual("unrun", by_id["SOLR-01"]["receipt_status"])
            parsed = list(csv.DictReader(io.StringIO(render_tsv(rows)), delimiter="\t"))
            self.assertEqual(102, len(parsed))
            self.assertEqual("candidate", parsed[0]["bug_review_mark"])
            self.assertEqual("unassessed", result["quality_state"])

            quality = Path(temporary) / "quality.json"
            assessment = {"schema_version": 1, "quality_reviews": [{
                "case_id": "HBASE-01", "state": "budget_finished_preliminary",
                "reason": "Only one of two trials reached the target after a fault.",
                "config_sha256": digest,
                "receipt_status": "complete_trial_budget",
                "completed_fault_trials": 2,
                "evidence_paths": ["cases/HBASE-01/summary.json"]}]}
            quality.write_text(json.dumps(assessment), encoding="utf-8")
            assessed = aggregate(INVENTORY, configs, states,
                                 ReceiptReader(states, remote=False),
                                 quality_path=quality)
            self.assertEqual("budget_finished_preliminary", assessed[0]["quality_state"])
            self.assertIn("Only one", assessed[0]["quality_reason"])
            self.assertEqual("candidate", assessed[0]["bug_review_mark"])
            assessment["quality_reviews"][0]["config_sha256"] = "0" * 64
            quality.write_text(json.dumps(assessment), encoding="utf-8")
            stale = aggregate(INVENTORY, configs, states,
                              ReceiptReader(states, remote=False), quality_path=quality)
            self.assertEqual("unassessed", stale[0]["quality_state"])
            self.assertIn("stale", stale[0]["quality_reason"])

            review = Path(temporary) / "reviews.json"
            review.write_text(json.dumps({"schema_version": 1, "reviews": [{
                "case_id": "HBASE-01", "mark": "confirmed", "reviewer": "source-review",
                "evidence_paths": ["diagnostics/HBASE-01.md"]}]}), encoding="utf-8")
            reviewed = aggregate(INVENTORY, configs, states,
                                 ReceiptReader(states, remote=False), review)
            self.assertEqual("confirmed", reviewed[0]["bug_review_mark"])
            review.write_text(json.dumps({"schema_version": 1, "reviews": [{
                "case_id": "HBASE-02", "mark": "confirmed", "reviewer": "source-review",
                "evidence_paths": ["diagnostics/HBASE-02.md"]}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "without a native candidate"):
                aggregate(INVENTORY, configs, states,
                          ReceiptReader(states, remote=False), review)

    def test_mismatched_summary_and_remote_error_are_not_unrun(self):
        with tempfile.TemporaryDirectory() as temporary:
            configs, states = self.make_roots(Path(temporary))
            case = states / "HBASE-01"
            case.mkdir()
            (case / "checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HBASE-01", "config_sha256": "pinned",
                "status": "complete_queue", "terminal": True,
                "completed_fault_trials": 0, "trial_elapsed_seconds": 1.0,
                "trials": []}), encoding="utf-8")
            (case / "summary.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HBASE-01", "config_sha256": "wrong",
                "status": "complete_queue", "terminal": True}), encoding="utf-8")

            class BrokenRemote(ReceiptReader):
                def read(self, case_id, host):
                    if case_id == "SOLR-01":
                        raise OSError("node2 unavailable")
                    return super().read(case_id, host)

            rows = aggregate(INVENTORY, configs, states,
                             BrokenRemote(states, remote=False))
            by_id = {row["case_id"]: row for row in rows}
            self.assertEqual("receipt_error", by_id["HBASE-01"]["receipt_status"])
            self.assertEqual("receipt_error", by_id["SOLR-01"]["receipt_status"])
            self.assertEqual("unrun", by_id["HBASE-02"]["receipt_status"])

    def test_running_checkpoint_uses_recorded_trial_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            configs, states = self.make_roots(Path(temporary))
            case = states / "HDFS-01"
            case.mkdir()
            (case / "checkpoint.json").write_text(json.dumps({
                "schema_version": 1, "case_id": "HDFS-01", "config_sha256": "pinned",
                "status": "running", "terminal": False,
                "completed_fault_trials": 1, "trial_elapsed_seconds": 2.5,
                "trials": [{"strict_injection": True,
                            "post_fault_target_reached": False,
                            "target_exception_triggered": False,
                            "target_exception_candidate": False}]}), encoding="utf-8")
            rows = aggregate(INVENTORY, configs, states,
                             ReceiptReader(states, remote=False))
            result = next(row for row in rows if row["case_id"] == "HDFS-01")
            self.assertEqual("running", result["receipt_status"])
            self.assertEqual(1, result["strict_trials"])
            self.assertEqual(0, result["post_fault_target_trials"])
            self.assertEqual("none", result["bug_review_mark"])

    def test_zk07_quality_review_is_preliminary_and_pinned(self):
        review = _quality_rows(DEFAULT_QUALITY_FILE)["ZOOKEEPER-07"]
        self.assertEqual("budget_finished_preliminary", review["state"])
        self.assertEqual(64, review["completed_fault_trials"])
        self.assertIn("BufferedReader.readLine", review["reason"])
        self.assertIn("PROGRAM_ORDER", review["reason"])


if __name__ == "__main__":
    unittest.main()
