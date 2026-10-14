"""Native-only 102-row export from one verified queue adoption."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, load_inventory,
)
from .queue import completion, sha
from .results import export_native_results


class NativeResultsTest(unittest.TestCase):
    def test_exactly_102_rows_with_one_verified_native_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root = root / "config"
            state_root = root / "state"
            results_dir = root / "data/mallory/native_graphchecker_queue"
            config_root.mkdir()
            state_root.mkdir()
            cases, _ = load_inventory(DEFAULT_INVENTORY)
            item = next(row for row in cases if row["case_id"] == "HBASE-01")
            case_id = item["case_id"]
            config_file = config_root / f"{case_id}.json"
            config_file.write_text(json.dumps({
                "case_id": case_id,
                "junit": {"class": item["workload"]["test_class"],
                          "method": item["workload"]["test_method"]}}))
            case_root = state_root / case_id
            case_root.mkdir()
            terminal = {"case_id": case_id, "terminal": True,
                        "status": "complete_trial_budget",
                        "config_sha256": sha(config_file)}
            (case_root / "checkpoint.json").write_text(json.dumps(terminal))
            (case_root / "summary.json").write_text(json.dumps(terminal))
            row = {"terminal_disposition": "tested_candidate",
                   "native_tested_complete": True,
                   "fault_trials": 3, "strict_fault_trials": 2,
                   "target_retained_fault_trials": 2,
                   "target_throw_trials": 1, "candidate_trials": 1,
                   "elapsed_seconds": 12.75}
            completion(item, row, config_file, state_root,
                       state_root / ".native-queue")

            json_path, tsv_path = export_native_results(
                DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, config_root, state_root,
                results_dir)
            document = json.loads(json_path.read_text())
            self.assertEqual(document["case_count"], 102)
            self.assertEqual(document["verified_terminal_count"], 1)
            self.assertEqual(len(document["rows"]), 102)
            completed = next(row for row in document["rows"]
                             if row["case_id"] == case_id)
            self.assertEqual(completed["target_source_path"],
                             item["target"]["source_path"])
            self.assertEqual(completed["target_line"],
                             item["target"]["source_line"])
            self.assertEqual(completed["target_check_code"],
                             item["target"]["check_code"])
            self.assertEqual(completed["original_junit"],
                             item["workload"]["selected_selector"])
            self.assertEqual(completed["target_class"],
                             "org.apache.hadoop.hbase.client.ConnectionImplementation")
            self.assertTrue(completed["target_method"].startswith(
                "locateRegionInMeta("))
            self.assertEqual(completed["fault_trials"], 3)
            self.assertEqual(completed["elapsed_seconds"], 12.75)
            self.assertTrue(completed["target_throw_observed"])
            self.assertTrue(completed["new_bug_candidate"])
            self.assertEqual(len(completed["evidence_paths"]), 4)
            with tsv_path.open(newline="") as stream:
                tsv_rows = list(csv.DictReader(stream, delimiter="\t"))
            self.assertEqual(len(tsv_rows), 102)
            self.assertEqual(sum(row["native_state"] == "verified_terminal"
                                 for row in tsv_rows), 1)
            first_json = json_path.read_bytes()
            first_tsv = tsv_path.read_bytes()
            export_native_results(DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                                  config_root, state_root, results_dir)
            self.assertEqual(json_path.read_bytes(), first_json)
            self.assertEqual(tsv_path.read_bytes(), first_tsv)


if __name__ == "__main__":
    unittest.main()
