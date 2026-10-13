"""Receipt-level tests; no distributed JUnit or original GraphChecker run."""

from __future__ import annotations

import json
import fcntl
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch import checklist as dispatch
from Mallory.native_graphchecker_dispatch import preparation
from Mallory.native_graphchecker_feedback.feedback import _session_digest, delta


class NativeChecklistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_root = self.root / "configs"
        self.state_root = self.root / "states"
        self.config_root.mkdir()
        self.state_root.mkdir()
        self.inventory = dispatch.DEFAULT_INVENTORY
        self.ownership = dispatch.DEFAULT_OWNERSHIP
        cases, _ = dispatch.load_inventory(self.inventory)
        self.item = next(item for item in cases if item["case_id"] == "HBASE-01")
        self.case_id = self.item["case_id"]
        self.case_root = self.state_root / self.case_id
        self.config_path = self.config_root / f"{self.case_id}.json"

    @staticmethod
    def write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n")

    def make_config(self) -> dict:
        static = self.root / "scope.jsonl"
        static.write_text("{}\n")
        woven = self.root / "woven"
        woven.mkdir(exist_ok=True)
        self.write(woven / "native-original-weave-receipt.json",
                   {"mode": "mallory_vendored_original_graphchecker_concolic_weave"})
        task_plan = self.root / "execution_task_plan.jsonl"
        task_plan.write_text('{"taskId":"recorded"}\n')
        weave_config = self.root / "weave.json"
        self.write(weave_config, {"output_classes": str(woven),
                                  "task_plan": str(task_plan)})
        recording = self.root / "recording"
        self.write(recording / "streaming_trace_manifest.json", {"closed": True})
        (self.root / "graph.jsonl").write_text("{}\n")
        (self.root / "regions.jsonl").write_text("{}\n")
        workload = self.item["workload"]
        config = {
            "case_id": self.case_id,
            "target_site": self.item["target"]["site_id"].split("#", 1)[0] + "#u1#1",
            "target_throw": {"siteId": self.item["target"]["site_id"],
                             "exceptionClass": self.item["target"]["target_exception"]},
            "native_weave_config": str(weave_config),
            "recording": {"trace_dir": str(self.root / "recording"),
                          "test_id": workload["selected_selector"],
                          "target_name": "target",
                          "candidate_graph": str(self.root / "graph.jsonl"),
                          "static_scope_map": str(static),
                          "region_skeletons": str(self.root / "regions.jsonl"),
                          "target_occurrence": "fixture:observed-target",
                          "max_jobs": 256},
            "junit": {"class": workload["test_class"],
                      "method": workload["test_method"]},
            "runner": {"zero_vm_java": "/fixture/java", "main_class": "FixtureRunner",
                       "classpath": []},
            "budget": {"fault_trials": 1, "seconds": 60,
                       "max_faults_per_trial": 2},
            "timeout_seconds": 30,
        }
        self.write(self.config_path, config)
        weave = json.loads(weave_config.read_text())
        receipt_path = woven / "native-original-weave-receipt.json"
        origin = {
            "recording_manifest_sha256": dispatch._sha(
                recording / "streaming_trace_manifest.json"),
            "recording_plan_sha256": dispatch._sha(Path(weave["task_plan"])),
            "scheduler_source_sha256": "c" * 64,
            "static_scope_map_sha256": dispatch._sha(static),
        }
        self.write(self.case_root / "recording-admission.json", {
            "schema_version": 1, "origin": origin,
            "recording_fingerprint": {
                "engine_jar_sha256": "a" * 64,
                "static_scope_map_sha256": dispatch._sha(static),
                "candidate_graph_sha256": dispatch._sha(self.root / "graph.jsonl"),
                "region_skeletons_sha256": dispatch._sha(self.root / "regions.jsonl"),
                "trace_tree_sha256": "d" * 64,
                "scheduler_source_sha256": "c" * 64,
                "weave_receipt_sha256": dispatch._sha(receipt_path),
                "weave_config_sha256": dispatch._sha(weave_config),
            },
        })
        attempt = self.case_root / "preparation/attempt-fixture"
        row_sha = hashlib.sha256(json.dumps(self.item, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        request = {"mode": dispatch.PREP_MODE, "case_id": self.case_id,
                   "inventory_row_sha256": row_sha,
                   "target": {"site_id": self.item["target"]["site_id"]},
                   "original_junit": {"class": workload["test_class"],
                                      "method": workload["test_method"]}}
        self.write(attempt / "request.json", request)
        self.write(attempt / "recipe.json", {"fixture": True})
        proof = {"mode": "original_graphchecker_native_adapter",
                 "case_id": self.case_id,
                 "request_sha256": hashlib.sha256(json.dumps(
                     request, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                 "original_cluster_junit_verified": True}
        self.write(attempt / "output/adapter-proof.json", proof)
        self.write(attempt / "output/static-scope-receipt.json", {"fixture": True})
        self.write(attempt / "output/recording-weave-receipt.json", {"fixture": True})
        occurrence = attempt / "output/target-occurrence.json"
        self.write(occurrence, {
            "kind": "MALLORY_OBSERVED_TARGET_OCCURRENCE",
            "test": workload["selected_selector"],
            "checkSiteId": config["target_site"].rsplit("#", 1)[0],
            "selectedOccurrenceAddress": "fixture:observed-target",
            "selectedEventSeq": 17, "selectedCallId": 11,
            "reachedEvents": [{"eventSeq": 17, "callId": 11,
                               "occurrenceAddress": "fixture:observed-target"}],
            "traceManifestSha256": dispatch._sha(
                recording / "streaming_trace_manifest.json"),
            "scopeMapSha256": dispatch._sha(static),
            "candidateGraphSha256": dispatch._sha(self.root / "graph.jsonl"),
            "regionSkeletonsSha256": dispatch._sha(self.root / "regions.jsonl"),
        })
        proof["target_occurrence_receipt_path"] = str(occurrence)
        proof["target_occurrence_receipt_sha256"] = dispatch._sha(occurrence)
        self.write(attempt / "output/adapter-proof.json", proof)
        self.write(attempt / "output/case.json", config)
        recipe_file = self.root / "adapter-recipes.json"
        self.write(recipe_file, {"fixture": True})
        engine_file = self.root / "engine.jar"
        engine_file.write_bytes(b"fixture engine")
        cache_key = "0" * 64
        prep_receipt = {
            "schema_version": 1, "mode": dispatch.PREP_MODE,
            "case_id": self.case_id, "inventory_row_sha256": row_sha,
            "cache_key": cache_key,
            "input_pins": [{"path": str(static), "sha256": dispatch._sha(static),
                            "kind": "file"}],
            "recipe_file_path": str(recipe_file),
            "recipe_file_sha256": dispatch._sha(recipe_file),
            "engine_jar_path": str(engine_file),
            "engine_jar_sha256": dispatch._sha(engine_file),
            "request_path": str(attempt / "request.json"),
            "request_sha256": dispatch._sha(attempt / "request.json"),
            "recipe_snapshot_path": str(attempt / "recipe.json"),
            "recipe_snapshot_sha256": dispatch._sha(attempt / "recipe.json"),
            "adapter_proof_path": str(attempt / "output/adapter-proof.json"),
            "adapter_proof_sha256": dispatch._sha(attempt / "output/adapter-proof.json"),
            "source_config_path": str(attempt / "output/case.json"),
            "config_sha256": dispatch._sha(self.config_path),
            "static_scope_receipt_path": str(attempt / "output/static-scope-receipt.json"),
            "static_scope_receipt_sha256": dispatch._sha(
                attempt / "output/static-scope-receipt.json"),
            "recording_weave_receipt_path": str(
                attempt / "output/recording-weave-receipt.json"),
            "recording_weave_receipt_sha256": dispatch._sha(
                attempt / "output/recording-weave-receipt.json"),
            "target_occurrence_receipt_path": str(occurrence),
            "target_occurrence_receipt_sha256": dispatch._sha(occurrence),
            "recording_admission_sha256": dispatch._sha(
                self.case_root / "recording-admission.json"),
            "native_weave_receipt_sha256": dispatch._sha(receipt_path),
            "original_cluster_junit_verified": True,
        }
        self.write(self.config_path.with_suffix(".prep.json"), prep_receipt)
        self.write(self.case_root / "preparation/state.json", {
            "status": "complete", "cache_key": cache_key,
            "receipt_sha256": hashlib.sha256(json.dumps(
                prep_receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        })
        return config

    def make_trial(self, config: dict, name: str, *, healthy: bool,
                   reached: bool = True, throw: bool = False) -> tuple[dict, dict]:
        trial = self.case_root / "trials" / name
        iteration = trial / "iteration-native"
        session = iteration / "sessions" / "one"
        self.write(session / "manifest.json", {"fixture": name})
        session_sha = _session_digest(iteration)
        faults = [] if healthy else [{
            "siteId": "RPC#door", "node": "nn0", "actorEpochOrdinal": 0,
            "ordinal": 1, "exceptionClass": "java.io.IOException",
            "sourceOccurrenceId": "prior:door"}]
        self.write(iteration / "fault-plan.json", {"faults": faults})
        door = {"kind": "FAULT_DOOR", "seq": 1, "siteId": "RPC#door",
                "node": "nn0", "actorEpochOrdinal": 0, "ordinal": 1,
                "exceptionClass": "java.io.IOException",
                "occurrenceId": "fresh:target"}
        events = [] if healthy else [door, {**door, "kind": "FAULT_APPLIED", "seq": 2}]
        if reached and not healthy:
            events.append({"kind": "TARGET_CHECK", "seq": 3,
                           "siteId": config["target_site"].rsplit("#", 1)[0],
                           "targetAnchorSiteId": config["target_site"],
                           "node": "nn0", "actorEpochOrdinal": 0,
                           "occurrenceId": "fresh:target"})
        if throw and not healthy:
            events.append({"kind": "TARGET_THROW", "seq": 4,
                           "siteId": config["target_throw"]["siteId"],
                           "exceptionClass": config["target_throw"]["exceptionClass"],
                           "occurrenceId": "fresh:target"})
        event_path = iteration / "fault-events.jsonl"
        event_path.write_text("".join(json.dumps(row) + "\n" for row in events))
        result = {
            "schema_version": 1, "case_id": self.case_id, "faults": faults,
            "status": "healthy_seed" if healthy else
                      "candidate" if throw else "checked" if reached else "target_lost",
            "elapsed_seconds": 1.0 if healthy else 2.0,
            "junit_passed": healthy,
            "return_code": 0 if healthy else 1,
            "timed_out": False,
            "strict_injection": not healthy,
            "native_target_retained": reached,
            "target_exception_triggered": bool(throw and reached),
            "fault_in_target_closure": not healthy and reached,
            "target_temporal_admitted": not healthy and reached,
            "target_temporal_reason": (
                "same_occurrence_before_check" if not healthy and reached else
                "no_applied_fault"),
            "target_temporal_evidence": ({
                "faultSeq": 2, "checkSeq": 3,
                "targetOccurrenceId": "fresh:target",
                "targetAnchorSiteId": config["target_site"],
            } if not healthy and reached else None),
            "fault_events_sha256": dispatch._sha(event_path),
            "native_session_sha256": session_sha if reached else None,
            "native_target_occurrence_ids": ["fresh:target"] if reached else [],
            "target_throw_rows": [row for row in events
                                  if row["kind"] == "TARGET_THROW"]
                                 if throw and reached else [],
        }
        if reached:
            target_row = {"occurrenceId": "fresh:target", "reachedAnchor": True,
                          "siteId": config["target_site"]}
            members = [{"occurrenceId": "fresh:target", "family": "nn0|R.target"},
                       {"occurrenceId": "fresh:door", "family": "nn0|R.door"}]
            summary = {
                "schemaVersion": 1, "method": dispatch.NATIVE_METHOD,
                "targetSetMode": True, "targetSiteId": config["target_site"],
                "engineJarSha256": "a" * 64,
                "staticScopeMapSha256": dispatch._sha(
                    Path(config["recording"]["static_scope_map"])),
                "staticScopeBundleSha256": "b" * 64,
                "bridgeSourceSha256": dispatch._sha(
                    dispatch.BASE / "Mallory/native_graphchecker_feedback/NativeFeedbackMain.java"),
                "nativeSessionSha256": session_sha, "maxTasks": 256,
                "targetOccurrenceIds": ["fresh:target"],
                "targetRows": [target_row], "closureMembers": members,
                "targetFamilies": ["nn0|R.target"],
                "targetRegionIds": ["R.target"],
                "perTargetOccurrences": [{
                    "targetOccurrenceId": "fresh:target",
                    "targetSiteId": config["target_site"],
                    "targetNodeName": "nn0",
                    "targetRegionId": "R.target",
                    "targetFamily": "nn0|R.target",
                    "targetRows": [target_row], "closureMembers": members}],
                "observedEdgesWithinClosure": [], "branchCoverage": [],
                "gaps": [], "truncated": [],
            }
            self.write(trial / "native-summary.json", summary)
            if not healthy:
                baseline = json.loads((self.case_root /
                                      "trials/r0000/native-summary.json").read_text())
                result["native_delta"] = delta(baseline, summary)
        self.write(trial / "result.json", result)
        return result, {"name": name, "status": result["status"],
                        "result": f"trials/{name}/result.json",
                        **({} if healthy else {
                            "strict_injection": result["strict_injection"],
                            "native_target_retained": result["native_target_retained"],
                            "target_exception_triggered": result[
                                "target_exception_triggered"],
                            "elapsed_seconds": result["elapsed_seconds"]})}

    def make_complete(self, *, reached: bool = True,
                      throw: bool = False) -> None:
        config = self.make_config()
        _, healthy = self.make_trial(config, "r0000", healthy=True)
        _, faulted = self.make_trial(config, "r0001", healthy=False,
                                     reached=reached, throw=throw)
        weave = json.loads(Path(config["native_weave_config"]).read_text())
        receipt_path = Path(weave["output_classes"]) / "native-original-weave-receipt.json"
        origin = json.loads((self.case_root /
                             "recording-admission.json").read_text())["origin"]
        checkpoint = {
            "schema_version": 1, "case_id": self.case_id,
            "config_sha256": dispatch._sha(self.config_path),
            "budget": config["budget"],
            "weave_receipt_sha256": dispatch._sha(receipt_path),
            "origin": origin, "status": "complete_trial_budget",
            "terminal": True, "healthy": healthy, "trials": [faulted],
            "queue": [], "seen_plan_keys": [], "active": None,
            "completed_fault_trials": 1, "elapsed_seconds": 3.0,
        }
        self.write(self.case_root / "checkpoint.json", checkpoint)
        self.write(self.case_root / "summary.json", {
            key: value for key, value in checkpoint.items()
            if key not in ("queue", "seen_plan_keys", "active")})

    def test_inventory_and_owner_have_exact_102_denominator(self) -> None:
        rows = dispatch.build_checklist(self.inventory, self.ownership,
                                        self.config_root, self.state_root)
        self.assertEqual(102, len(rows))
        self.assertEqual(0, sum(row["native_tested_complete"] for row in rows))
        self.assertEqual("needs_native_preparation", rows[0]["terminal_disposition"])
        self.assertEqual(103, len(dispatch.tsv(rows).splitlines()))

    def test_native_candidate_requires_session_and_exact_throw_receipt(self) -> None:
        self.make_complete(throw=True)
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("tested_candidate", row["terminal_disposition"])
        self.assertTrue(row["native_tested_complete"])
        self.assertEqual(1, row["strict_target_retained_fault_trials"])
        self.assertEqual(1, row["target_throw_trials"])
        self.assertEqual(1, row["candidate_trials"])
        self.assertEqual(3.0, row["elapsed_seconds"])
        self.assertIn("ConnectionImplementation.java", row["target_source_path"])

    def test_preparation_uses_observed_original_target_occurrence(self) -> None:
        config = self.make_config()
        output = self.case_root / "preparation/attempt-fixture/output"
        proof = json.loads((output / "adapter-proof.json").read_text())
        receipt = preparation.verify_target_occurrence(
            proof, config, output, self.item["target"]["site_id"])
        self.assertEqual(17, receipt["selectedEventSeq"])
        config["recording"]["target_occurrence"] = "first"
        with self.assertRaisesRegex(ValueError, "target occurrence"):
            preparation.verify_target_occurrence(
                proof, config, output, self.item["target"]["site_id"])

    def test_zero_retained_fault_trials_is_tested_inconclusive(self) -> None:
        self.make_complete(reached=False)
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("tested_inconclusive", row["terminal_disposition"])
        self.assertEqual(0, row["strict_target_retained_fault_trials"])

    def test_tampered_session_or_fault_receipt_is_never_complete(self) -> None:
        self.make_complete(throw=True)
        session = self.case_root / "trials/r0001/iteration-native/sessions/one/manifest.json"
        session.write_text("changed\n")
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("receipt_error", row["terminal_disposition"])
        self.assertFalse(row["native_tested_complete"])
        self.make_complete(throw=True)
        events = self.case_root / "trials/r0001/iteration-native/fault-events.jsonl"
        events.write_text(events.read_text().replace("fresh:target", "wrong:door", 1))
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("receipt_error", row["terminal_disposition"])

    def test_changed_preparation_scope_or_input_invalidates_terminal(self) -> None:
        self.make_complete(throw=True)
        scope_receipt = self.case_root / "preparation/attempt-fixture/output/static-scope-receipt.json"
        scope_receipt.write_text('{"changed":true}\n')
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("receipt_error", row["terminal_disposition"])

        self.make_complete(throw=True)
        (self.root / "scope.jsonl").write_text('{"changed":true}\n')
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("receipt_error", row["terminal_disposition"])

    def test_post_target_fault_cannot_keep_candidate_label(self) -> None:
        self.make_complete(throw=True)
        events_path = self.case_root / "trials/r0001/iteration-native/fault-events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        check = next(row for row in events if row["kind"] == "TARGET_CHECK")
        door = next(row for row in events if row["kind"] == "FAULT_DOOR")
        applied = next(row for row in events if row["kind"] == "FAULT_APPLIED")
        thrown = next(row for row in events if row["kind"] == "TARGET_THROW")
        check["seq"], door["seq"], applied["seq"], thrown["seq"] = 1, 2, 3, 4
        events_path.write_text("".join(json.dumps(row) + "\n" for row in
                                       (check, door, applied, thrown)))
        result_path = self.case_root / "trials/r0001/result.json"
        result = json.loads(result_path.read_text())
        result["fault_events_sha256"] = dispatch._sha(events_path)
        result["target_throw_rows"] = [thrown]
        self.write(result_path, result)
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("receipt_error", row["terminal_disposition"])
        self.assertIn("temporal", row["reason"])

    def test_cross_occurrence_without_throw_is_review_not_negative(self) -> None:
        self.make_complete()
        events_path = self.case_root / "trials/r0001/iteration-native/fault-events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        for event in events:
            if event["kind"] in ("FAULT_DOOR", "FAULT_APPLIED"):
                event["occurrenceId"] = "fresh:door"
        events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
        result_path = self.case_root / "trials/r0001/result.json"
        result = json.loads(result_path.read_text())
        result.update(status="needs_causal_review",
                      target_temporal_admitted=False,
                      target_temporal_reason="cross_occurrence_order_unproved",
                      target_temporal_evidence=None,
                      fault_events_sha256=dispatch._sha(events_path))
        self.write(result_path, result)
        checkpoint_path = self.case_root / "checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text())
        checkpoint["trials"][0]["status"] = "needs_causal_review"
        self.write(checkpoint_path, checkpoint)
        self.write(self.case_root / "summary.json", {
            key: value for key, value in checkpoint.items()
            if key not in ("queue", "seen_plan_keys", "active")})
        row = dispatch.inspect_case(self.item, "node1", self.config_root,
                                    self.state_root)
        self.assertEqual("tested_no_target_throw", row["terminal_disposition"])
        self.assertEqual(1, row["strict_target_retained_fault_trials"])

    def test_no_cluster_junit_is_terminal_but_not_fuzzed(self) -> None:
        evidence = self.root / "source-review.md"
        evidence.write_text("Reviewed original tests.\n")
        reviews = self.root / "reviews.json"
        self.write(reviews, {"schema_version": 1,
                             "no_eligible_original_cluster_junit": {
                                 self.case_id: {"reason": "No original cluster test reaches target",
                                                "evidence_paths": [str(evidence)]}}})
        rows = dispatch.build_checklist(self.inventory, self.ownership,
                                        self.config_root, self.state_root, reviews)
        row = next(item for item in rows if item["case_id"] == self.case_id)
        self.assertEqual("no_eligible_original_cluster_junit",
                         row["terminal_disposition"])
        self.assertFalse(row["native_tested_complete"])

    def test_run_next_skips_verified_terminal_and_never_reads_old_imports(self) -> None:
        self.make_complete(throw=True)
        with patch.object(dispatch.socket, "gethostname", return_value="node1"):
            invoked = []
            result = dispatch.run_next(self.inventory, self.ownership,
                                       self.config_root, self.state_root,
                                       "node1", runner=lambda *_: invoked.append(True))
        self.assertEqual("no_runnable_native_case", result["status"])
        self.assertEqual([], invoked)
        self.assertEqual("tested_candidate", dispatch.inspect_case(
            self.item, "node1", self.config_root,
            self.state_root)["terminal_disposition"])

    def test_run_next_only_invokes_owned_ready_case_once(self) -> None:
        self.make_config()
        calls = []

        def runner(config: Path, output: Path) -> None:
            calls.append((config, output))
            self.make_complete()

        with patch.object(dispatch.socket, "gethostname", return_value="node1"):
            row = dispatch.run_next(self.inventory, self.ownership,
                                    self.config_root, self.state_root, "node1",
                                    runner=runner)
        self.assertEqual([(self.config_path, self.case_root)], calls)
        self.assertEqual("tested_no_target_throw", row["terminal_disposition"])
        self.assertTrue(row["native_tested_complete"])
        with patch.object(dispatch.socket, "gethostname", return_value="node0"):
            with self.assertRaisesRegex(ValueError, "physical owner host"):
                dispatch.run_next(self.inventory, self.ownership,
                                  self.config_root, self.state_root, "node1",
                                  runner=runner)

    def test_distributed_status_merges_only_owner_receipts(self) -> None:
        all_rows = dispatch.build_checklist(self.inventory, self.ownership,
                                            self.config_root, self.state_root)
        hosts = iter(("node1", "node2"))

        def remote(_argv, **_kwargs):
            host = next(hosts)
            payload = {
                "schema_version": 1,
                "inventory_sha256": dispatch._sha(self.inventory),
                "ownership_sha256": dispatch._sha(self.ownership),
                "dispatcher_source_sha256": dispatch._sha(Path(dispatch.__file__)),
                "rows": [row for row in all_rows if row["owner"] == host],
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload),
                                   stderr="")

        with patch.object(dispatch.socket, "gethostname", return_value="node0"), patch.object(
                dispatch.subprocess, "run", side_effect=remote) as run:
            rows = dispatch.build_distributed_checklist(
                self.inventory, self.ownership, self.config_root,
                self.state_root, ssh_key=self.root / "fake-key")
        self.assertEqual(102, len(rows))
        self.assertEqual(2, run.call_count)
        self.assertEqual([row["case_id"] for row in all_rows],
                         [row["case_id"] for row in rows])

    def test_corrupt_terminal_is_not_rerun(self) -> None:
        self.make_complete(throw=True)
        (self.case_root / "summary.json").unlink()
        with patch.object(dispatch.socket, "gethostname", return_value="node1"):
            invoked = []
            result = dispatch.run_next(self.inventory, self.ownership,
                                       self.config_root, self.state_root,
                                       "node1", runner=lambda *_: invoked.append(True))
        self.assertEqual("no_runnable_native_case", result["status"])
        self.assertEqual([], invoked)
        self.assertEqual("receipt_error", dispatch.inspect_case(
            self.item, "node1", self.config_root,
            self.state_root)["terminal_disposition"])

    def test_orphaned_native_trial_state_is_not_rerun(self) -> None:
        self.make_config()
        self.write(self.case_root / "trials/r0000/result.json", {"orphan": True})
        with patch.object(dispatch.socket, "gethostname", return_value="node1"):
            invoked = []
            result = dispatch.run_next(self.inventory, self.ownership,
                                       self.config_root, self.state_root, "node1",
                                       runner=lambda *_: invoked.append(True))
        self.assertEqual("no_runnable_native_case", result["status"])
        self.assertEqual([], invoked)
        self.assertEqual("receipt_error", dispatch.inspect_case(
            self.item, "node1", self.config_root,
            self.state_root)["terminal_disposition"])

    def test_host_lock_prevents_second_owner_worker(self) -> None:
        self.make_config()
        host_lock = self.state_root / ".host-node1.lock"
        with host_lock.open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(dispatch.socket, "gethostname", return_value="node1"):
                with self.assertRaises(BlockingIOError):
                    dispatch.run_next(self.inventory, self.ownership,
                                      self.config_root, self.state_root, "node1",
                                      runner=lambda *_: self.fail("ran under lock"))


if __name__ == "__main__":
    unittest.main()
