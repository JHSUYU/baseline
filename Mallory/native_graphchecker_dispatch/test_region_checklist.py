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

    def test_binding_pins_inventory_row_native_id_and_config_bytes(self) -> None:
        item = next(row for row in checklist.load_inventory(
            checklist.DEFAULT_INVENTORY)[0] if row["case_id"] == "ZOOKEEPER-07")
        config_root = self.root / "config"
        config_root.mkdir()
        native_config = self.root / "native-config.json"
        native_id = "ZOOKEEPER-07-native-fixture"
        native_config.write_text(json.dumps({
            "case_id": native_id, "runner": {"mode": "region_state"}}) + "\n")
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
        summary = summarize_region_state(
            trace, plan, receipt, events, graph_fixture.scope,
            graph_fixture.graph, graph_fixture.skeletons, fixture.SITE,
            engine_jar=graph_fixture.engine, target_throw=config["target_throw"])
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
        events.write_text(events.read_text().replace("exact-runtime-check",
                                                    "wrong-occurrence"))
        with self.assertRaisesRegex(ValueError, "graph or target receipt changed"):
            checklist._verified_region_summary(trial, result, config,
                                                graph_fixture.engine)

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
