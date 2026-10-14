"""Native-only 102-row export from one verified queue adoption."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, load_inventory,
)
from .queue import completion, sha
from .results import (_elapsed_basis, _reviewed_exact_closure,
                      _reviewed_wall_timing, export_native_results)


class NativeResultsTest(unittest.TestCase):
    def test_healthy_graph_timeout_is_pinned_but_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root, state_root, results_dir = (root / name for name in
                                                    ("config", "state", "results"))
            config_root.mkdir()
            state_root.mkdir()
            item = next(row for row in load_inventory(DEFAULT_INVENTORY)[0]
                        if row["case_id"] == "HBASE-07")
            selector = item["workload"]["selected_selector"]
            junit_class, junit_method = selector.split("#", 1)
            guard = item["target"]["site_id"].rsplit("#", 1)[0] + "#u10"
            config = root / "case.json"
            config.write_text(json.dumps({
                "junit": {"class": junit_class, "method": junit_method},
                "target_site": guard,
                "target_throw": {"siteId": item["target"]["site_id"],
                                 "exceptionClass": item["target"][
                                     "target_exception"]}}))
            healthy = root / "result.json"
            healthy.write_text(json.dumps({
                "status": "blocked_healthy_native_session",
                "junit_passed": True, "target_exception_triggered": False,
                "faults": [], "strict_injection": False}))
            occurrence = root / "target-occurrence.json"
            occurrence.write_text(json.dumps({
                "test": selector, "checkSiteId": guard,
                "reachedEventCount": 2, "fatalOutcome": False}))
            review = root / "review.json"
            review.write_text(json.dumps({
                "caseId": "HBASE-07",
                "kind": "HBASE07_V4_NO_PLAN_HEALTHY_GRAPH_TERMINAL_REVIEW",
                "status": "blocked_healthy_native_session",
                "failureClass": "original_recorder_timeout_1800s",
                "formalStarted": False, "appliedFaultCount": 0,
                "bugClaim": False, "junitPassed": True,
                "rawTargetCheckCount": 2, "rawTargetThrowCount": 0,
                "junitElapsedSeconds": 80.205,
                "analysisElapsedSeconds": 2100.289,
                "configPath": str(config), "configSha256": sha(config),
                "healthyResultSha256": sha(healthy)}))
            pin = state_root / ".native-queue/admission-notes/HBASE-07.json"
            pin.parent.mkdir(parents=True)
            files = {name: {"path": str(path), "sha256": sha(path)}
                     for name, path in (("review", review), ("config", config),
                                        ("healthy_result", healthy),
                                        ("target_occurrence", occurrence))}
            pin.write_text(json.dumps({
                "schema_version": 1, "case_id": "HBASE-07",
                "status": "blocked_healthy_native_session",
                "inventory_row_sha256": hashlib.sha256(json.dumps(
                    item, sort_keys=True, separators=(",", ":")
                ).encode()).hexdigest(),
                "junit_trials": 1, "fault_trials": 0, **files}))
            output, _ = export_native_results(
                DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, config_root,
                state_root, results_dir)
            document = json.loads(output.read_text())
            row = next(row for row in document["rows"]
                       if row["case_id"] == "HBASE-07")
            self.assertEqual(document["verified_terminal_count"], 0)
            self.assertEqual(row["native_state"],
                             "preparation_healthy_graph_blocked")
            self.assertEqual(row["preparation_junit_trials"], 1)
            self.assertEqual(row["preparation_fault_trials"], 0)
            self.assertFalse(row["native_tested_complete"])
            self.assertIsNone(row["fault_trials"])
            review.write_text(review.read_text() + " ")
            with self.assertRaisesRegex(ValueError,
                                        "native admission review pin changed"):
                export_native_results(DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                                      config_root, state_root, results_dir)

    def test_source_only_eligibility_skip_is_pinned_and_nonterminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root, state_root, results_dir = (root / name for name in
                                                    ("config", "state", "results"))
            config_root.mkdir()
            state_root.mkdir()
            inventory = json.loads(DEFAULT_INVENTORY.read_text())
            item = next(row for row in inventory["cases"]
                        if row["case_id"] == "SOLR-40")
            names = ("processor", "time_test", "base_test", "lucene_annotation",
                     "category_test", "dimensional_test", "create_test",
                     "concurrent_test", "api_test", "alias_test")
            sources = {}
            prior_sources = {}
            for name in names:
                path = root / f"{name}.java"
                path.write_text(f"source {name}\n")
                sources[name] = {"path": str(path), "sha256": sha(path)}
                prior_sources[name] = {"path": path.name, "sha256": sha(path)}
            item["target"]["source_sha256"] = sources["processor"]["sha256"]
            item["workload"]["candidates"][0]["source_sha256"] = sources[
                "time_test"]["sha256"]
            inventory_file = root / "inventory.json"
            inventory_file.write_text(json.dumps(inventory))
            prior = root / "prior-review.json"
            prior.write_text(json.dumps({
                "case_id": "SOLR-40",
                "source_review_status":
                "source_review_no_suitable_test_current_environment",
                "receipt_tier_assessment": {
                    "source_only_no_executable_test_justified_for_unmodified_checkout":
                    True, "permanent_no_test_claim_justified": False},
                "target": {"source_sha256": item["target"]["source_sha256"],
                           "source_line": item["target"]["source_line"]},
                "prior_attempt": {"pilot_target_check_count": 0,
                                  "junit_failures": 1},
                "source_hashes": prior_sources}))
            log = root / "junit-failure.txt"
            log.write_text("@AwaitsFix; Can't create a configset with an "
                           "unauthenticated request\n")
            review = root / "eligibility-review.json"
            review.write_text(json.dumps({
                "schema_version": 1, "case_id": "SOLR-40",
                "status": "no_eligible_original_cluster_test_current_checkout",
                "inventory": {"path": str(inventory_file.resolve()),
                              "sha256": sha(inventory_file),
                              "row_sha256": hashlib.sha256(json.dumps(
                                  item, sort_keys=True, separators=(",", ":")
                                  ).encode()).hexdigest()},
                "selected_original_junit": item["workload"]["selected_selector"],
                "native_queue_junit_trials": 0, "native_queue_fault_trials": 0,
                "target": {"source_path": item["target"]["source_path"],
                           "source_sha256": item["target"]["source_sha256"],
                           "method": item["target"]["function"],
                           "throw_line": item["target"]["source_line"],
                           "exception": item["target"]["target_exception"]},
                "prior_opt_in_junit": {"tests": 1, "failures": 1,
                                       "target_checks": 0, "target_throws": 0},
                "prior_source_review": {"path": str(prior), "sha256": sha(prior)},
                "prior_opt_in_junit_log": {"path": str(log), "sha256": sha(log)},
                "source_files": sources}))
            pin = state_root / ".native-queue/eligibility-notes/SOLR-40.json"
            pin.parent.mkdir(parents=True)
            pin.write_text(json.dumps({
                "schema_version": 1, "case_id": "SOLR-40",
                "status": "no_eligible_original_cluster_test_current_checkout",
                "native_queue_junit_trials": 0, "native_queue_fault_trials": 0,
                "review": {"path": str(review), "sha256": sha(review)}}))
            output, _ = export_native_results(
                inventory_file, DEFAULT_OWNERSHIP, config_root,
                state_root, results_dir)
            document = json.loads(output.read_text())
            row = next(row for row in document["rows"]
                       if row["case_id"] == "SOLR-40")
            self.assertEqual(document["case_count"], 102)
            self.assertEqual(document["verified_terminal_count"], 0)
            self.assertEqual(row["native_state"],
                             "skipped_no_eligible_original_cluster_test")
            self.assertFalse(row["native_tested_complete"])
            self.assertEqual(row["preparation_fault_trials"], 0)
            self.assertIsNone(row["fault_trials"])
            self.assertIsNone(row["completion_receipt_path"])
            copied_inventory = root / "inventory-copy.json"
            copied_inventory.write_bytes(inventory_file.read_bytes())
            copied, _ = export_native_results(
                copied_inventory, DEFAULT_OWNERSHIP, config_root,
                state_root, results_dir)
            self.assertEqual(json.loads(copied.read_text())[
                "verified_terminal_count"], 0)
            (root / "base_test.java").write_text("changed\n")
            with self.assertRaisesRegex(ValueError,
                                        "native eligibility source base_test changed"):
                export_native_results(inventory_file, DEFAULT_OWNERSHIP,
                                      config_root, state_root, results_dir)

    def test_static_timeout_preparation_is_pinned_but_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_root, state_root, results_dir = (root / name for name in
                                                    ("config", "state", "results"))
            config_root.mkdir()
            state_root.mkdir()
            item = next(row for row in load_inventory(DEFAULT_INVENTORY)[0]
                        if row["case_id"] == "HDFS-39")
            source = root / "source-preflight.json"
            source.write_text(json.dumps({
                "schema_version": 1, "case_id": item["case_id"],
                "target_source_sha256": item["target"]["source_sha256"],
                "target_throw_source_line": item["target"]["source_line"],
                "target_exception": item["target"]["target_exception"],
                "original_junit": item["workload"]["selected_selector"]}))
            request = root / "request.json"
            request.write_text(json.dumps({
                "case_id": item["case_id"],
                "inventory_row_sha256": hashlib.sha256(json.dumps(
                    item, sort_keys=True, separators=(",", ":")
                    ).encode()).hexdigest(),
                "original_junit": {"selector": item["workload"][
                    "selected_selector"]},
                "target": {"site_id": item["target"]["site_id"]}}))
            review = root / "static-timeout-review.json"
            review.write_text(json.dumps({
                "schema_version": 1, "case_id": item["case_id"],
                "status": "static_timeout", "exit_code": "1",
                "configured_static_timeout_seconds": 1800,
                "last_observed_stage": "StaticScopeMap.sites/holders",
                "no_weave_manifest": True, "no_junit_run": True,
                "no_fault_trial": True,
                "request_sha256": sha(request)}))
            note = state_root / ".native-queue/preparation-notes/HDFS-39.json"
            note.parent.mkdir(parents=True)
            note.write_text(json.dumps({
                "schema_version": 1, "case_id": item["case_id"],
                "status": "static_timeout", "junit_trials": 0,
                "fault_trials": 0,
                "review": {"path": str(review), "sha256": sha(review)},
                "source_preflight": {"path": str(source),
                                     "sha256": sha(source)},
                "request": {"path": str(request),
                            "sha256": sha(request)}}))
            output, _ = export_native_results(
                DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, config_root,
                state_root, results_dir)
            document = json.loads(output.read_text())
            row = next(row for row in document["rows"]
                       if row["case_id"] == item["case_id"])
            self.assertEqual(document["case_count"], 102)
            self.assertEqual(document["verified_terminal_count"], 0)
            self.assertEqual(row["native_state"], "preparation_static_timeout")
            self.assertFalse(row["native_tested_complete"])
            self.assertEqual(row["preparation_junit_trials"], 0)
            self.assertEqual(row["preparation_fault_trials"], 0)
            self.assertIsNone(row["fault_trials"])
            self.assertIsNone(row["terminal_disposition"])
            review.write_text(review.read_text() + " ")
            with self.assertRaisesRegex(ValueError, "preparation review pin changed"):
                export_native_results(DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                                      config_root, state_root, results_dir)

    def test_exact_closure_review_pins_frozen_plan_and_fault_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "native"
            state = root / "state"
            case_id = "ZOOKEEPER-02"
            trial = native / "trials/r0001"
            (trial / "original-graph/recorded").mkdir(parents=True)
            (trial / "iteration-native").mkdir()
            (trial / "result.json").write_text(json.dumps({
                "strict_injection": True, "native_target_retained": True,
                "fault_in_target_closure": False,
                "target_exception_triggered": False,
                "target_temporal_admitted": False}))
            plan = trial / "original-graph/recorded/concolic_region_plan.jsonl"
            events = trial / "iteration-native/fault-events.jsonl"
            plan.write_text('{"kind":"CONCOLIC_REGION_PLAN"}\n')
            events.write_text('{"kind":"FAULT_APPLIED"}\n')
            report = root / "audit.json"
            report.write_text(json.dumps({
                "kind": "READ_ONLY_REGION_STATE_CLOSURE_AUDIT",
                "campaign": str(native.resolve()), "engineJarSha256": "placeholder",
                "strictTargetRetainedTrials": 1,
                "reportedLastFaultInClosure": 0,
                "correctedLastFaultInClosure": 1,
                "trials": [{"trial": "r0001",
                            "correctedLastFaultInClosure": True,
                            "reportedLastFaultInClosure": False,
                            "targetExceptionTriggered": False,
                            "targetTemporalAdmitted": False,
                            "originalPlanSha256": sha(plan),
                            "faultEventsSha256": sha(events)}]}))
            method, java, engine = (root / "method.py", root / "Ids.java",
                                    root / "engine.jar")
            for path in (method, java, engine):
                path.write_text(path.name)
            document = json.loads(report.read_text())
            document["engineJarSha256"] = sha(engine)
            report.write_text(json.dumps(document))
            index = root / "index.json"
            index.write_text(json.dumps({
                "kind": "READ_ONLY_REGION_STATE_CLOSURE_AUDIT_INDEX",
                "rows": [{"auditPath": str(report),
                          "auditSha256": sha(report),
                          "campaign": str(native.resolve()),
                          "engineJarSha256": sha(engine),
                          "strictTargetRetainedTrials": 1,
                          "reportedLastFaultInClosure": 0,
                          "correctedLastFaultInClosure": 1}]}))
            pin_path = (state / ".native-queue/closure-reviews" /
                        f"{case_id}.json")
            pin_path.parent.mkdir(parents=True)
            pin_path.write_text(json.dumps({
                "schema_version": 1, "case_id": case_id,
                "report_path": str(report), "report_sha256": sha(report),
                "method_path": str(method), "method_sha256": sha(method),
                "id_source_path": str(java), "id_source_sha256": sha(java),
                "engine_jar_path": str(engine),
                "engine_jar_sha256": sha(engine),
                "index_path": str(index), "index_sha256": sha(index),
                "completion_receipt_sha256": "receipt"}))
            self.assertEqual(_reviewed_exact_closure(
                case_id, native, state, 1, 0, "receipt")[0], 1)
            plan.write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "trial changed"):
                _reviewed_exact_closure(case_id, native, state, 1, 0,
                                        "receipt")

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
