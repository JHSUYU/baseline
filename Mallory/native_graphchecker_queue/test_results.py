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
from .results import _elapsed_basis, _reviewed_wall_timing, export_native_results


class NativeResultsTest(unittest.TestCase):
    def test_reviewed_wall_timing_preserves_distinct_elapsed_basis(self) -> None:
        review = {"timing": {"cumulative_trial_seconds": 1862.14,
                             "campaign_wall_seconds": 2166.528,
                             "static_to_terminal_wall_seconds": 3124.749}}
        self.assertEqual((2166.528, 3124.749),
                         _reviewed_wall_timing(review, 1862.14))
        with self.assertRaisesRegex(ValueError, "wall timing differs"):
            _reviewed_wall_timing(review, 1862.141)

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
            for index, (junit, analysis) in enumerate((
                    (1.0, 1.75), (1.0, 2.0), (1.0, 2.0), (1.0, 3.0))):
                trial = case_root / "trials" / f"r{index:04d}"
                trial.mkdir(parents=True)
                (trial / "result.json").write_text(json.dumps({
                    "elapsed_seconds": junit + analysis,
                    "junit_elapsed_seconds": junit,
                    "analysis_elapsed_seconds": analysis}))
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
            self.assertEqual(completed["elapsed_basis"],
                             "sum_native_trial_elapsed_seconds_including_graph_analysis")
            self.assertTrue(completed["target_throw_observed"])
            self.assertTrue(completed["target_exception_candidate"])
            self.assertIsNone(completed["confirmed_new_bug"])
            self.assertIsNone(completed["strict_in_target_closure_trials"])
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

    def test_coverage_export_pins_original_trial_and_graph_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root, state_root = root / "config", root / "state"
            config_root.mkdir()
            state_root.mkdir()
            cases, _ = load_inventory(DEFAULT_INVENTORY)
            item = next(row for row in cases if row["case_id"] == "HBASE-01")
            case_id = item["case_id"]
            config = config_root / f"{case_id}.json"
            config.write_text(json.dumps({"case_id": case_id}))
            native_root = state_root / case_id
            native_root.mkdir()
            terminal = {"case_id": case_id, "terminal": True,
                        "config_sha256": sha(config)}
            (native_root / "checkpoint.json").write_text(json.dumps(terminal))
            (native_root / "summary.json").write_text(json.dumps(terminal))
            for index, inside in enumerate((False, True, False)):
                trial = native_root / "trials" / f"r{index:04d}"
                trial.mkdir(parents=True)
                (trial / "result.json").write_text(json.dumps({
                    "elapsed_seconds": 1.0, "junit_elapsed_seconds": 0.5,
                    "analysis_elapsed_seconds": 0.5,
                    "strict_injection": index > 0,
                    "native_target_retained": index > 0,
                    "fault_in_target_closure": inside}))
                (trial / "native-summary.json").write_text("{}\n")
            audited = {"terminal_disposition": "tested_no_target_throw",
                       "native_tested_complete": True, "fault_trials": 2,
                       "strict_fault_trials": 2,
                       "target_retained_fault_trials": 2,
                       "strict_target_retained_fault_trials": 2,
                       "strict_in_target_closure_trials": 1,
                       "target_throw_trials": 0, "candidate_trials": 0,
                       "elapsed_seconds": 3.0}
            completion(item, audited, config, state_root,
                       state_root / ".native-queue", config_root=config_root)
            published = export_native_results(
                DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, config_root, state_root,
                root / "results")[0]
            row = next(row for row in json.loads(published.read_text())["rows"]
                       if row["case_id"] == case_id)
            self.assertEqual(row["strict_target_retained_fault_trials"], 2)
            self.assertEqual(row["strict_in_target_closure_trials"], 1)
            self.assertEqual(row["closure_attribution_basis"],
                             "region_state_v1_same_occurrence_proxy; "
                             "causal_target_reachability_unverified")
            self.assertEqual(len(row["evidence_paths"]), 5)
            (native_root / "trials/r0001/native-summary.json").write_text(
                '{"changed": true}\n')
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                export_native_results(DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                                      config_root, state_root, root / "results")

    def test_legacy_native_receipts_identify_junit_only_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, seconds in enumerate((1.25, 1.75)):
                trial = root / "trials" / f"r{index:04d}"
                trial.mkdir(parents=True)
                (trial / "result.json").write_text(json.dumps({
                    "elapsed_seconds": seconds}))
            self.assertEqual(_elapsed_basis(root, 1, 3.0),
                             "sum_native_junit_execution_seconds_legacy")


if __name__ == "__main__":
    unittest.main()
