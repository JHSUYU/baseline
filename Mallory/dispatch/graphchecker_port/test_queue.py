"""Fixture tests for the native GraphChecker queue; no real JUnit is launched."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from Mallory.dispatch.graphchecker_port import queue
from Mallory.dispatch.graphchecker_port.plan import sha256


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rows = []
        for system, count in (("hdfs", 38), ("hbase", 30), ("solr", 21),
                              ("zookeeper", 13)):
            for index in range(1, count + 1):
                case_id = f"{system.upper()}-{index:02d}"
                rows.append({"case_id": case_id, "system": system,
                             "workload": {"selected_selector": "example.Test#test",
                                          "test_class": "example.Test",
                                          "test_method": "test"},
                             "eligibility": {"may_attempt_seed": True,
                                             "may_dispatch_healthy_seed": True}})
        self.inventory = self.root / "inventory.json"
        write(self.inventory, {"schema_version": 1, "cases": rows})
        self.graph_jar = self.root / "graph.jar"
        self.graph_jar.write_bytes(b"fixture analyzer")
        self.script = self.root / "prepare_zk_campaign.py"
        self.script.write_text("# fixture adapter\n", encoding="utf-8")
        self.state_root = self.root / "state"
        self.import_root = self.root / "imports"
        self.manifest = self.root / "lane.json"
        self.document = {
            "schema_version": 1, "host": "node0", "system": "zookeeper",
            "inventory": str(self.inventory),
            "inventory_sha256": sha256(self.inventory),
            "state_root": str(self.state_root),
            "import_root": str(self.import_root),
            "case_ids": ["ZOOKEEPER-07"],
            "adapter_supported_case_ids": ["ZOOKEEPER-07"],
            "pins": {str(self.script): sha256(self.script),
                     str(self.graph_jar): sha256(self.graph_jar)},
            "recipe": {"config_relative": "campaign-config.json",
                       "steps": [{"kind": "zookeeper_prepare",
                                  "argv": ["python3", str(self.script),
                                           "--case-id", "{case_id}",
                                           "--output", "{prep}",
                                           "--graph-jar", str(self.graph_jar)],
                                  "outputs": ["scope/weave_manifest.json",
                                              "scope/static_scope_map.jsonl",
                                              "campaign-config.json"]}]}}
        write(self.manifest, self.document)

    def loaded(self):
        return queue.load_manifest(self.manifest)

    def _fake_prepare(self, command, **kwargs):
        prep = Path(command[command.index("--output") + 1])
        (prep / "scope").mkdir()
        (prep / "scope/weave_manifest.json").write_text("{}\n", encoding="utf-8")
        (prep / "scope/static_scope_map.jsonl").write_text("\n", encoding="utf-8")
        write(prep / "campaign-config.json", {
            "case_id": command[command.index("--case-id") + 1],
            "weave_manifest": str(prep / "scope/weave_manifest.json"),
            "static_scope_map": str(prep / "scope/static_scope_map.jsonl"),
            "graph_jar": str(self.graph_jar)})
        return mock.Mock(returncode=0)

    def test_dry_run_is_read_only_and_original_junit_gated(self):
        document, rows, digest = self.loaded()
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            result = queue.plan(document, rows, digest)
        self.assertEqual("ready_prepare", result["cases"][0]["status"])
        self.assertFalse(self.state_root.exists())
        rows["ZOOKEEPER-07"]["workload"]["selected_selector"] = None
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            result = queue.plan(document, rows, digest)
        self.assertEqual("blocked_no_eligible_original_junit",
                         result["cases"][0]["status"])

    def test_prepare_receipt_and_resume_after_interrupted_preparation(self):
        document, rows, digest = self.loaded()
        case, state_path = queue._case_files(self.state_root, "ZOOKEEPER-07")
        with mock.patch.object(queue.subprocess, "run", side_effect=self._fake_prepare):
            prepared = queue._prepare(document, "ZOOKEEPER-07", case, state_path, digest)
        first = Path(prepared["prep"])
        self.assertTrue((first / "prepare-receipt.json").is_file())
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            status = queue.plan(document, rows, digest)["cases"][0]["status"]
        self.assertEqual("ready_campaign", status)
        prepared["phase"] = "preparing"
        queue._atomic_json(state_path, prepared)
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            status = queue.plan(document, rows, digest)["cases"][0]["status"]
        self.assertEqual("resume_new_prepare_attempt", status)
        with mock.patch.object(queue.subprocess, "run", side_effect=self._fake_prepare):
            replacement = queue._prepare(document, "ZOOKEEPER-07", case,
                                         state_path, digest)
        self.assertNotEqual(first, Path(replacement["prep"]))
        self.assertTrue((first / "prepare-receipt.json").is_file())

    def test_raw_target_check_without_graph_target_blocks_resume(self):
        document, rows, digest = self.loaded()
        case, state_path = queue._case_files(self.state_root, "ZOOKEEPER-07")
        with mock.patch.object(queue.subprocess, "run", side_effect=self._fake_prepare):
            state = queue._prepare(document, "ZOOKEEPER-07", case, state_path, digest)
        campaign = case / "campaigns" / "fixture"
        trial = campaign / "trials/r0000"
        trial.mkdir(parents=True)
        raw = trial / "graphchecker-raw.jsonl.gz"
        with gzip.open(raw, "wb") as stream:
            stream.write(json.dumps({"kind": "TARGET_CHECK", "siteId": "exact-check",
                                     "seq": 12}).encode() + b"\n")
        write(trial / "result.json", {
            "evidence": {"target_reached": False},
            "artifacts": {"raw_trace": {"path": raw.name, "encoding": "gzip",
                                        "sha256": sha256(raw)}}})
        write(campaign / "checkpoint.json", {
            "schema_version": 1, "case_id": "ZOOKEEPER-07", "status": "running",
            "terminal": False, "config_sha256": state["config_sha256"],
            "healthy_target_reached": False,
            "configured_check_sites": ["exact-check"],
            "healthy": {"result": "trials/r0000/result.json"}})
        state.update({"phase": "running", "campaign": str(campaign)})
        queue._atomic_json(state_path, state)
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            status = queue.plan(document, rows, digest)["cases"][0]["status"]
        self.assertEqual("blocked_healthy_target_attribution", status)

    def test_active_job_prevents_preparation(self):
        document, rows, digest = self.loaded()
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[
                {"pid": 7, "command": "other live GraphChecker fuzzer"}]):
            result = queue.run_queue(document, rows, digest)
        self.assertEqual("host_busy", result["outcomes"][0]["status"])
        self.assertFalse((self.state_root / "ZOOKEEPER-07").exists())

    def test_recipe_rejects_hand_selected_io(self):
        self.document["recipe"]["steps"][0]["argv"].extend(
            ["--doors", "allkeys.get:12"])
        write(self.manifest, self.document)
        with self.assertRaisesRegex(ValueError, "I/O or fault sites"):
            self.loaded()

    def test_external_running_is_not_taken_over(self):
        ext = self.root / "external"
        ext.mkdir()
        config = self.root / "external-config.json"
        write(config, {"case_id": "ZOOKEEPER-07"})
        write(ext / "checkpoint.json", {"schema_version": 1,
             "case_id": "ZOOKEEPER-07", "config_sha256": sha256(config),
             "terminal": False, "status": "running"})
        self.document["existing_campaigns"] = {"ZOOKEEPER-07": {
            "config": str(config), "campaign": str(ext)}}
        write(self.manifest, self.document)
        document, rows, digest = self.loaded()
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            result = queue.run_queue(document, rows, digest)
        self.assertEqual("external_running", result["outcomes"][0]["status"])
        self.assertFalse((self.state_root / "ZOOKEEPER-07").exists())

    def test_all_four_adapter_phase_contracts(self):
        recipes = {
            "hdfs": ("HDFS-01", [
                ("hdfs_scope", ["python3", "{script}", "--case-id", "{case_id}",
                                "scope-input", "--out", "{prep}/scope-input.json"]),
                ("scope_planner", ["java", "ScopePlanner", "{prep}/scope-input.json",
                                   "{prep}/scope"]),
                ("hdfs_campaign", ["python3", "{script}", "--case-id", "{case_id}",
                                   "campaign-config", "--out", "{prep}/case.json"])]),
            "hbase": ("HBASE-01", [
                ("hbase_prepare", ["python3", "{script}", "--case-id", "{case_id}",
                                   "--output", "{prep}"])]),
            "solr": ("SOLR-01", [
                ("solr_scope", ["python3", "{script}", "scope", "--case-id",
                                 "{case_id}", "--out", "{prep}"]),
                ("solr_scope_planner", ["{prep}/run_scope.sh"]),
                ("solr_campaign", ["python3", "{script}", "campaign", "--case-id",
                                    "{case_id}", "--out", "{prep}"])]),
            "zookeeper": ("ZOOKEEPER-07", [
                ("zookeeper_prepare", ["python3", "{script}", "--case-id",
                                         "{case_id}", "--output", "{prep}"])])}
        for system, (case_id, phases) in recipes.items():
            with self.subTest(system=system):
                adapter = self.root / system / ("prepare_zk_campaign.py" if
                                               system == "zookeeper" else "prepare_case.py")
                adapter.parent.mkdir(exist_ok=True)
                adapter.write_text("# pinned adapter\n", encoding="utf-8")
                document = dict(self.document)
                document.update({"system": system, "case_ids": [case_id],
                                 "adapter_supported_case_ids": [case_id],
                                 "pins": {str(adapter): sha256(adapter)}})
                document["recipe"] = {"config_relative": "case.json",
                                      "steps": [{"kind": kind,
                                                 "argv": [value.replace("{script}",
                                                                        str(adapter))
                                                          for value in argv],
                                                 "outputs": ["case.json"]}
                                                for kind, argv in phases]}
                write(self.manifest, document)
                self.assertEqual(system, queue.load_manifest(self.manifest)[0]["system"])

    def test_reviewed_hold_preserves_stopped_campaign(self):
        evidence = self.root / "source-review.txt"
        evidence.write_text("raw target reached; graph target absent\n")
        self.document["holds"] = {"ZOOKEEPER-07": {
            "reason": "adapter attribution requires repair",
            "evidence_paths": [str(evidence)]}}
        write(self.manifest, self.document)
        document, rows, digest = self.loaded()
        with mock.patch.object(queue, "_live_graph_jobs", return_value=[]):
            result = queue.run_queue(document, rows, digest)
        self.assertEqual("skip_reviewed_hold", result["outcomes"][0]["status"])
        review = queue._object(self.state_root / "ZOOKEEPER-07/review-result.json")
        self.assertEqual("held_for_adapter_review", review["status"])

    def test_compact_trace_requires_capable_pinned_runtime(self):
        runtime = self.root / "runtime.jar"
        with zipfile.ZipFile(runtime, "w") as archive:
            archive.writestr(queue.COMPACT_CLASS,
                             b"mallory.graphchecker.trace.compact")
        config = {"tool_classpath": [str(runtime)],
                  "runner": {"jvm_args": ["-Xmx2g"]}}
        queue._enable_compact_runtime_trace(config, {str(runtime): sha256(runtime)})
        self.assertIn(queue.COMPACT_PROPERTY, config["runner"]["jvm_args"])
        queue._enable_compact_runtime_trace(config, {str(runtime): sha256(runtime)})
        self.assertEqual(1, config["runner"]["jvm_args"].count(queue.COMPACT_PROPERTY))
        with self.assertRaisesRegex(ValueError, "lacks compact trace"):
            queue._enable_compact_runtime_trace(
                {"tool_classpath": [str(runtime)], "runner": {"jvm_args": []}}, {})


if __name__ == "__main__":
    unittest.main()
