"""REGION_STATE dispatch receipts and immutable inventory binding."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch import checklist
from Mallory.native_graphchecker_feedback.region_state_graph import (
    summarize_region_state,
)
from Mallory.native_graphchecker_feedback import test_region_state_graph as fixture


class RegionChecklistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_elapsed_basis_includes_original_graph_analysis(self) -> None:
        trials = self.root / "trials"
        for name, junit, analysis in (("r0000", 1.0, 1.5),
                                      ("r0001", 2.0, 2.0)):
            directory = trials / name
            directory.mkdir(parents=True)
            (directory / "result.json").write_text(json.dumps({
                "elapsed_seconds": junit + analysis,
                "junit_elapsed_seconds": junit,
                "analysis_elapsed_seconds": analysis,
            }))
        self.assertEqual(
            "sum_native_trial_elapsed_seconds_including_graph_analysis",
            checklist._audited_elapsed_basis(self.root, 1, 6.5))
        result = trials / "r0001/result.json"
        changed = json.loads(result.read_text())
        changed["analysis_elapsed_seconds"] = 1.9
        result.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "breakdown changed"):
            checklist._audited_elapsed_basis(self.root, 1, 6.5)

    def test_fault_membership_uses_original_closure_not_check_occurrence(self) -> None:
        # A causally upstream fault and the check are different occurrences.
        # The old receipt inspector compared those two IDs directly and
        # rejected a valid target-closure fault.
        graph = {"closureOccurrenceIds": ["upstream-fault", "target-check"]}
        self.assertTrue(checklist._last_fault_in_region_closure(
            graph, {"occurrenceId": "upstream-fault"}))
        self.assertFalse(checklist._last_fault_in_region_closure(
            graph, {"occurrenceId": "unrelated-fault"}))
        with self.assertRaisesRegex(ValueError, "target closure is missing"):
            checklist._last_fault_in_region_closure({},
                                                    {"occurrenceId": "upstream-fault"})

    def test_raw_differential_is_audited_separately_from_selected_graph_throw(self) -> None:
        config = {"target_site": "Guard#check", "target_throw": {
            "siteId": "Guard#throw", "exceptionClass": "java.io.IOException"}}
        fault = {"siteId": "RPC#read", "node": "dn", "actorEpochOrdinal": 0,
                 "ordinal": 1, "exceptionClass": "java.io.IOException"}
        door = {**fault, "kind": "FAULT_DOOR", "seq": 1,
                "occurrenceId": "rpc-1"}
        applied = {**door, "kind": "FAULT_APPLIED", "seq": 2}
        check = {"kind": "TARGET_CHECK", "siteId": "Guard#check", "seq": 3,
                 "node": "dn", "actorEpochOrdinal": 0,
                 "occurrenceId": "other-target"}
        thrown = {**check, "kind": "TARGET_THROW", "seq": 4,
                  "siteId": "Guard#throw",
                  "exceptionClass": "java.io.IOException",
                  "actualExceptionClass": "java.io.IOException"}
        events = [door, applied, check, thrown]
        raw = checklist.native._raw_prefix_target_throws(
            [fault], events, config["target_site"], config["target_throw"])
        result = {"faults": [fault], "strict_injection": True,
                  "raw_exact_target_throw_count": 1,
                  "healthy_raw_exact_target_throw_count": 0,
                  "raw_target_throw_observation": raw,
                  "raw_exact_target_throw_after_applied_prefix": True,
                  "raw_target_throw_differential_candidate": True}
        record = {"raw_exact_target_throw_count": 1,
                  "raw_target_throw_differential_candidate": True}
        self.assertEqual((1, True), checklist._audited_raw_target_throw(
            result, record, events, config, 0))
        selected, _, _, _ = checklist.native._region_throw_evidence(
            events, config["target_site"], config["target_throw"], applied,
            {"chosen-target"})
        self.assertEqual([], selected)
        with self.assertRaisesRegex(ValueError, "raw exact target throw count"):
            checklist._audited_raw_target_throw(
                {**result, "raw_exact_target_throw_count": 2}, record,
                events, config, 0)
        with self.assertRaisesRegex(ValueError, "checkpoint raw target"):
            checklist._audited_raw_target_throw(
                result, {**record, "raw_target_throw_differential_candidate": False},
                events, config, 0)

    def test_shared_archive_verifies_unavailable_owner_source(self) -> None:
        source = self.root / "owner-only.java"
        audit = self.root / "identity.json"
        archive = self.root / "shared"
        archive.mkdir()
        copy = archive / "source.java"
        copy.write_text("exact original source\n")
        digest = checklist._sha(copy)
        audit.write_text('{"identity":"pinned"}\n')
        receipt = {
            "schema_version": 1, "case_id": "HDFS-29",
            "audit_path": str(audit), "audit_sha256": checklist._sha(audit),
            "original_path": str(source), "original_sha256": digest,
            "archived_path": str(copy), "archived_sha256": digest,
        }
        (archive / "HDFS-29.json").write_text(json.dumps(receipt))
        self.assertEqual(digest, checklist._archived_source_sha(
            "HDFS-29", audit, source, digest, archive))
        copy.write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "archive differs"):
            checklist._archived_source_sha(
                "HDFS-29", audit, source, digest, archive)

    def test_binding_pins_inventory_row_native_id_and_config_bytes(self) -> None:
        item = next(row for row in checklist.load_inventory(
            checklist.DEFAULT_INVENTORY)[0] if row["case_id"] == "ZOOKEEPER-07")
        config_root = self.root / "config"
        config_root.mkdir()
        native_config = self.root / "native-config.json"
        native_id = "ZOOKEEPER-07-native-fixture"
        native_config.write_text(json.dumps({
            "case_id": native_id, "runner": {"mode": "region_state"},
            "target_throw": {"siteId": item["target"]["site_id"],
                             "exceptionClass": item["target"][
                                 "target_exception"]}}) + "\n")
        native_state = self.root / "native-state"
        native_state.mkdir()
        binding = {
            "schema_version": 1, "mode": "native_region_state_case_binding",
            "inventory_case_id": item["case_id"],
            "inventory_row_sha256": hashlib.sha256(json.dumps(
                item, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "native_case_id": native_id,
            "native_config_path": str(native_config),
            "native_config_sha256": checklist._sha(native_config),
            "native_state_path": str(native_state),
        }
        path = config_root / "ZOOKEEPER-07.json"
        path.write_text(json.dumps(binding) + "\n")
        self.assertEqual((native_config, native_state), checklist._native_case_files(
            item, config_root, self.root / "state"))
        native_config.write_text(native_config.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "binding changed"):
            checklist._native_case_files(item, config_root, self.root / "state")

    def test_original_region_graph_and_exact_target_receipts_are_replayed(self) -> None:
        graph_fixture = fixture.RegionStateGraphTest("runTest")
        graph_fixture.setUp()
        self.addCleanup(graph_fixture.doCleanups)

        def fixture_plan_projection(path, _jar):
            # The synthetic fixture pins occurrence IDs directly; its
            # engine.jar is deliberately not a compiled GraphChecker engine.
            # Replace only Java's plan projection. Both summaries still
            # traverse the real graph and validate the real receipts.
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            plans = rows[1:]
            identifiers = {
                ("exact-runtime-check" if row["regionId"] == fixture.ACTIVATION
                 else "exact-receiver"): row for row in plans}
            return len(rows[0].get("gaps", [])), plans, identifiers

        original = graph_fixture._case("recorded")
        trial = self.root / "r0001"
        iteration = trial / "iteration-native"
        trace = iteration / "trace"
        shutil.copytree(original["trace"], trace)
        events = iteration / "fault-events.jsonl"
        events.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original["events"], events)
        output = trial / "original-graph"
        plan = output / "recorded/concolic_region_plan.jsonl"
        plan.parent.mkdir(parents=True)
        shutil.copy2(original["plan"], plan)
        receipt = output / "target-occurrence.json"
        shutil.copy2(original["receipt"], receipt)
        config = {
            "target_site": fixture.SITE,
            "target_throw": {"siteId": "<example.Keys: void check()>#u8",
                             "exceptionClass": "java.io.IOException"},
            "recording": {"static_scope_map": str(graph_fixture.scope),
                          "candidate_graph": str(graph_fixture.graph),
                          "region_skeletons": str(graph_fixture.skeletons)},
        }
        with patch("Mallory.native_graphchecker_feedback.region_state_graph."
                   "_plan_projection", side_effect=fixture_plan_projection):
            summary = summarize_region_state(
                trace, plan, receipt, events, graph_fixture.scope,
                graph_fixture.graph, graph_fixture.skeletons, fixture.SITE,
                engine_jar=graph_fixture.engine,
                target_throw=config["target_throw"])
            summary["provenance"]["extractor"] = (
                "invoked_original_resolver_and_recorder")
            for path in (trial / "native-summary.json", output / "summary.json"):
                path.write_text(json.dumps(summary) + "\n")
            (trial / "schedule-lineage.json").write_text(json.dumps({
                "source": str(trace / "schedule.jsonl"),
                "source_sha256": checklist._sha(trace / "schedule.jsonl"),
                "destination_sha256": checklist._sha(trace / "schedule.jsonl"),
                "copied": False}) + "\n")
            result = {"native_session_sha256": checklist._sha(
                          trial / "native-summary.json"),
                      "native_target_occurrence_ids": summary[
                          "targetEvidence"]["targetCheckOccurrenceIds"]}
            self.assertEqual(summary, checklist._verified_region_summary(
                trial, result, config, graph_fixture.engine))
            other_engine = self.root / "other-analysis-engine.jar"
            other_engine.write_bytes(b"different engine bytes")
            with self.assertRaisesRegex(
                    ValueError, "original REGION_STATE graph or target receipt changed"):
                checklist._verified_region_summary(trial, result, config,
                                                   other_engine)
            events.write_text(events.read_text().replace("exact-runtime-check",
                                                        "wrong-occurrence"))
            with self.assertRaisesRegex(
                    ValueError, "original Finalizer plan omitted the exact target check"):
                checklist._verified_region_summary(trial, result, config,
                                                    graph_fixture.engine)

    def test_target_absent_summary_preserves_context_boundary_schema(self) -> None:
        trial = self.root / "r0006"
        trace = trial / "iteration-native/trace"
        trace.mkdir(parents=True)
        (trace / "streaming_trace_manifest.json").write_text(json.dumps({
            "schemaVersion": 2, "kind": "STREAMING_RUNTIME_TRACE",
            "status": "CLOSED", "tracedRows": "exact-trace-digest"}) + "\n")
        (trace / "runtime_trace.jsonl").write_text("")
        (trace / "schedule.jsonl").write_text("")
        scope = self.root / "static_scope_map.jsonl"
        graph = self.root / "candidate_dataflow_edges.jsonl.gz"
        skeletons = self.root / "region_skeletons.jsonl.gz"
        for path in (scope, graph, skeletons):
            path.write_bytes(b"pinned static input")
        pins = checklist._closed_inputs(trace, scope, graph, skeletons)
        site = "<example.Target: void check()>#u7"
        summary = {"schemaVersion": 1, "backend": "original_region_state",
                   "targetSiteId": site, "targetReached": False,
                   "targetThrowObserved": False, "status": "target_absent",
                   "nodeFamilies": [], "edgeFamilies": [],
                   "contextBoundaryEdgeFamilies": [],
                   "closureEdgeFamilies": [], "branchOutcomeIds": [],
                   "provenance": pins}
        original = trial / "original-graph"
        original.mkdir()
        saved = trial / "native-summary.json"
        for path in (saved, original / "summary.json"):
            path.write_text(json.dumps(summary) + "\n")
        (trial / "schedule-lineage.json").write_text(json.dumps({
            "source": str(trace / "schedule.jsonl"),
            "source_sha256": checklist._sha(trace / "schedule.jsonl"),
            "destination_sha256": checklist._sha(trace / "schedule.jsonl"),
            "copied": False}) + "\n")
        result = {"native_session_sha256": checklist._sha(saved),
                  "native_target_occurrence_ids": []}
        config = {"target_site": site, "recording": {
            "static_scope_map": str(scope), "candidate_graph": str(graph),
            "region_skeletons": str(skeletons)}}
        self.assertEqual(summary, checklist._verified_region_summary(
            trial, result, config, self.root / "engine.jar"))
        summary["contextBoundaryEdgeFamilies"] = ["unexpected-edge"]
        for path in (saved, original / "summary.json"):
            path.write_text(json.dumps(summary) + "\n")
        result["native_session_sha256"] = checklist._sha(saved)
        with self.assertRaisesRegex(ValueError, "graph or target receipt changed"):
            checklist._verified_region_summary(
                trial, result, config, self.root / "engine.jar")

    def test_alternate_upstream_junit_requires_pinned_source_and_target(self) -> None:
        item = next(row for row in checklist.load_inventory(
            checklist.DEFAULT_INVENTORY)[0] if row["case_id"] == "HDFS-11")
        source_root = self.root / "upstream"
        source = source_root / "test/AlternateTest.java"
        source.parent.mkdir(parents=True)
        source.write_text("@Test void original() { runCluster(); }\n")
        compiled = self.root / "AlternateTest.class"
        compiled.write_bytes(b"original compiled test")
        resolved = self.root / "target-occurrence.json"
        site = item["target"]["site_id"].rsplit("#", 1)[0] + "#u8"
        resolved.write_text(json.dumps({"checkSiteId": site,
                                        "reachedEventCount": 2}) + "\n")
        healthy = self.root / "result.json"
        healthy.write_text(json.dumps({"status": "healthy_seed",
                                       "junit_passed": True,
                                       "native_target_retained": True}) + "\n")
        executed = "example.AlternateTest#original"
        attestation = {
            "case_id": item["case_id"],
            "binding_type": "alternate_unchanged_original_junit",
            "inventory_recorded_selector": item["workload"]["selected_selector"],
            "executed_selector": executed,
            "target_throw_site_id": item["target"]["site_id"],
            "target_site_id": site,
            "healthy_junit_exit_code": 0,
            "healthy_target_reached_event_count": 2,
            "source_root": str(source_root), "source_commit": "original-revision",
            "source_path": str(source), "source_sha256": checklist._sha(source),
            "compiled_test_class_path": str(compiled),
            "compiled_test_class_sha256": checklist._sha(compiled),
            "resolver_receipt_path": str(resolved),
            "resolver_receipt_sha256": checklist._sha(resolved),
            "native_official_healthy_result_path": str(healthy),
            "native_official_healthy_result_sha256": checklist._sha(healthy),
        }
        attestation_path = self.root / "attestation.json"
        attestation_path.write_text(json.dumps(attestation) + "\n")
        binding = self.root / "binding.json"
        binding.write_text(json.dumps({
            "mode": "native_region_state_case_binding",
            "alternate_original_junit": {
                "attestation_path": str(attestation_path),
                "attestation_sha256": checklist._sha(attestation_path)}}) + "\n")
        config = {"junit": {"class": "example.AlternateTest",
                            "method": "original"}, "target_site": site}
        git = [SimpleNamespace(stdout="original-revision\n"),
               SimpleNamespace(stdout="")]
        with patch("Mallory.native_graphchecker_dispatch.checklist.subprocess.run",
                   side_effect=git):
            checklist._verify_alternate_junit(item, binding, config)
        compiled.write_bytes(b"changed compiled test")
        with self.assertRaisesRegex(ValueError, "compiled_test_class_path"):
            checklist._verify_alternate_junit(item, binding, config)


if __name__ == "__main__":
    unittest.main()
