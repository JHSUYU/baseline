"""Contract tests for inventory-driven original Solr preparation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest

from Mallory.adapters.solr.native_graphchecker_port import prepare_case as prep


class PrepareCaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.classes = self.root / "classes"
        self.test_classes = self.root / "test-classes"
        self.static_output = self.root / "static"
        self.sidecars = self.static_output / "original"
        self.output = self.root / "prepared"
        self.target_class = "org.apache.solr.cloud.SampleController"
        self.test_class = "org.apache.solr.cloud.SampleClusterTest"
        self.target_source = "solr/core/src/java/org/apache/solr/cloud/SampleController.java"
        self.test_source = "solr/core/src/test/org/apache/solr/cloud/SampleClusterTest.java"
        for rel, body in [(self.target_source, b"class SampleController {}\n"),
                          (self.test_source, b"class SampleClusterTest {}\n")]:
            file = self.source / rel
            file.parent.mkdir(parents=True)
            file.write_bytes(body)
        for root, clazz in [(self.classes, self.target_class),
                            (self.test_classes, self.test_class)]:
            file = root / (clazz.replace(".", "/") + ".class")
            file.parent.mkdir(parents=True)
            file.write_bytes(b"compiled-fixture")
        self.row = {
            "case_id": "SOLR-XX", "system": "solr",
            "eligibility": {"may_dispatch_healthy_seed": True},
            "provenance": {"source_commit": "fixture-commit"},
            "target": {"function": self.target_class + ".register(java.lang.String)",
                       "source_path": self.target_source,
                       "source_sha256": prep.sha256(self.source / self.target_source),
                       "source_line": 20,
                       "target_exception": "org.apache.solr.common.SolrException",
                       "runtime_mapping": {"check_sites": [self.target_class +
                                                   "#register(Ljava/lang/String;)V@19:branch:2"],
                                           "throw_site": self.target_class + "#u4"}},
            "workload": {"selected_selector": self.test_class + "#testRun",
                         "test_class": self.test_class, "test_method": "testRun",
                         "test_source_path": self.test_source,
                         "candidates": [{"selector": self.test_class + "#testRun",
                                         "source_path": self.test_source,
                                         "source_sha256": prep.sha256(self.source / self.test_source)}]},
        }
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text(json.dumps({"cases": [self.row]}))
        self.cp = self.root / "ordered-cp.txt"
        self.cp.write_text(str(self.classes) + ":" + str(self.test_classes) + "\n")
        self.static_input = self.root / "static-input.json"
        self.static_input.write_text(json.dumps(prep.static_input(
            self.row, self.classes, prep.read_classpath(self.cp), self.sidecars)))
        self.static_output.mkdir()
        self.sidecars.mkdir()
        for name in prep.SIDECARS:
            (self.sidecars / name).write_bytes(b"original-sidecar-fixture")
        self.branch = "<" + self.target_class + ": void register(java.lang.String)>#u3"
        self.throw = "<" + self.target_class + ": void register(java.lang.String)>#u4"
        self.manifest = {"caseId": "SOLR-XX", "targets": [
            {"kind": "BRANCH", "clazz": self.target_class, "method": "register",
             "line": 19, "siteId": self.branch},
            {"kind": "THROW", "clazz": self.target_class, "method": "register",
             "line": 20, "siteId": self.throw,
             "exceptionClass": "org.apache.solr.common.SolrException"}],
            "doors": [{"siteId": "<org.apache.solr.common.cloud.SolrZkClient: byte[] getData(java.lang.String)>#u7",
                       "exceptionClass": "java.io.IOException"}],
            "regions": [{"regionId": "REGION.1"}], "coverage": [{"siteId": self.branch}]}
        self._manifest()

    def _manifest(self):
        (self.static_output / "weave_manifest.json").write_text(json.dumps(self.manifest))

    def test_scope_uses_one_system_policy_and_original_junit(self):
        row = prep.inventory_row("SOLR-XX", self.inventory)
        self.assertEqual(prep.attest_source(row, self.source)["source_commit"], "fixture-commit")
        scope = prep.static_input(row, self.classes, prep.read_classpath(self.cp), self.sidecars)
        self.assertEqual(scope["target"]["line"], 19)
        self.assertTrue(scope["analysis"]["original_graphchecker_seed"])
        self.assertEqual(scope["analysis"]["io_door_mappings"], prep.SOLR_IO_METHODS)
        self.assertNotIn("#u7", json.dumps(scope))
        (self.source / self.test_source).write_text("modified test\n")
        with self.assertRaisesRegex(ValueError, "original source differs"):
            prep.attest_source(row, self.source)

    def test_static_selects_exact_target_and_typed_doors(self):
        result = prep.validate_static(self.row, self.static_input,
                                      self.static_output, self.sidecars)
        self.assertEqual(result["target_site"], self.branch)
        self.assertEqual(result["target_throw"]["siteId"], self.throw)
        self.assertEqual(result["typed_fault_doors"], 1)
        self.manifest["doors"][0].pop("exceptionClass")
        self._manifest()
        with self.assertRaisesRegex(ValueError, "typed fault doors"):
            prep.validate_static(self.row, self.static_input, self.static_output, self.sidecars)

    def test_static_rejects_changed_compiled_junit_class(self):
        self.assertEqual(prep.validate_static(self.row, self.static_input,
                                              self.static_output, self.sidecars)["typed_fault_doors"], 1)
        compiled = self.test_classes / (self.test_class.replace(".", "/") + ".class")
        compiled.write_bytes(b"changed-compiled-test")
        with self.assertRaisesRegex(ValueError, "compiled target or JUnit class differs"):
            prep.validate_static(self.row, self.static_input, self.static_output, self.sidecars)

    def test_closed_trace_and_unique_original_scheduler_task_required(self):
        trace = self.root / "trace"
        trace.mkdir()
        (trace / "streaming_trace_manifest.json").write_text(json.dumps({"status": "CLOSED"}))
        (trace / "runtime_trace.jsonl").write_text(json.dumps(
            {"event": "BRANCH", "siteId": self.branch}) + "\n")
        self.assertEqual(prep.validate_recording(trace, self.branch)["target_checks"], 1)
        with self.assertRaisesRegex(ValueError, "did not reach"):
            prep.validate_recording(trace, self.throw)
        index = self.root / "index.json"
        plan = self.root / "plan.jsonl"
        index.write_text(json.dumps({"members": [{"role": "TARGET",
                                                  "targetReachGoal": True,
                                                  "taskId": "TASK.1"}]}))
        plan.write_text(json.dumps({"taskId": "TASK.1"}) + "\n")
        self.assertEqual(prep.validate_schedule(index, plan)["target_task_id"], "TASK.1")
        index.write_text(json.dumps({"members": [
            {"role": "TARGET", "targetReachGoal": True, "taskId": "TASK.1"},
            {"role": "TARGET", "targetReachGoal": True, "taskId": "TASK.2"}]}))
        with self.assertRaisesRegex(ValueError, "no unique target task"):
            prep.validate_schedule(index, plan)

    def test_three_phase_preparation_uses_generated_artifacts(self):
        patch = self.root / "protocol.patch"
        patch.write_bytes(b"pinned native Solr protocol patch")
        protocol = self.root / "protocol-receipt.json"
        protocol.write_text(json.dumps({
            "source_commit": "fixture-commit", "patch_sha256": prep.sha256(patch),
            "patched_source_sha256": {
                self.target_source: prep.sha256(self.source / self.target_source)}}))
        mappings = self.root / "communication-mappings.jsonl"
        mappings.write_text('{"kind":"COMMUNICATION_MAPPING"}\n')
        planner = self.root / "planner.jar"
        planner.write_bytes(b"planner")
        deps = self.root / "planner-cp.txt"
        deps.write_text(str(planner))
        java = self.root / "java"
        java.write_text("java fixture")
        scope_out = self.root / "scope-prepared"
        scope = prep.prepare_scope(argparse.Namespace(
            case_id="SOLR-XX", inventory=self.inventory, source=self.source,
            protocol_receipt=protocol, protocol_patch=patch,
            class_tree=self.classes, classpath_file=self.cp,
            output=scope_out, planner_jar=planner, planner_deps=deps,
            java=java, communication_mappings=mappings))
        self.assertEqual(scope["phase"], "static_prepared")
        self.assertEqual(prep.read_json(scope_out / "static-input.json")["target"]["line"], 19)
        adapter = self.root / "fault-adapter.jar"
        adapter.write_bytes(b"adapter")
        engine = self.root / "engine"
        engine_jar = engine / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
        engine_jar.parent.mkdir(parents=True)
        engine_jar.write_bytes(b"engine")
        (engine / "target/native-original-dependencies.txt").write_text(str(planner))
        weave_out = self.root / "weave-prepared"
        adapter_classes = self.root / "adapter-classes"
        runner_file = adapter_classes / (prep.RUNNER.replace(".", "/") + ".class")
        runner_file.parent.mkdir(parents=True)
        runner_file.write_bytes(b"runner")
        runner_cp = self.root / "runner-cp.txt"
        runner_cp.write_text(str(weave_out / "woven") + ":" +
                             str(adapter_classes) + ":" + str(self.test_classes))
        weave = prep.prepare_weave(argparse.Namespace(
            case_id="SOLR-XX", inventory=self.inventory,
            static_input=self.static_input, static_output=self.static_output,
            sidecars=self.sidecars, output=weave_out, java=java,
            source=self.source, protocol_receipt=protocol, protocol_patch=patch,
            runner_classpath_file=runner_cp,
            adapter_jar=adapter, engine_root=engine,
            communication_mappings=mappings, timeout=120, max_jobs=5,
            analysis_heap_mb=8192))
        self.assertEqual(weave["typed_fault_doors"], 1)
        weave_config = prep.read_json(weave_out / "native-weave-config.json")
        self.assertEqual(weave_config["weave_mode"], "region_state")
        self.assertNotIn("task_id", weave_config)
        self.assertEqual(weave_config["communication_mappings"], str(mappings))
        self.assertEqual(weave_config["native_fault_manifest"],
                         str(self.static_output / "weave_manifest.json"))
        healthy_script = (weave_out / "run_healthy_original_junit.sh").read_text()
        self.assertIn(self.test_class, healthy_script)
        self.assertIn("CAUSYNTH_TRACE_OUTPUT_DIR", healthy_script)
        plan_script = (weave_out / "run_original_recorder_scheduler.sh").read_text()
        self.assertIn("CausynthTraceRecorder", plan_script)
        self.assertIn("ConcolicScheduler", plan_script)
        self.assertEqual(plan_script.count("-Xmx8192m"), 2)
        woven = weave_out / "woven"
        woven.mkdir()
        (woven / "native-original-weave-receipt.json").write_text("{}")
        trace = self.root / "trace"
        trace.mkdir()
        (trace / "streaming_trace_manifest.json").write_text(json.dumps({"status": "CLOSED"}))
        (trace / "runtime_trace.jsonl").write_text(json.dumps(
            {"event": "BRANCH", "siteId": self.branch}) + "\n")
        index = self.root / "index.json"
        plan = self.root / "plan.jsonl"
        index.write_text(json.dumps({"members": [{"role": "TARGET",
                                                  "targetReachGoal": True,
                                                  "taskId": "TASK.1"}]}))
        plan.write_text(json.dumps({"taskId": "TASK.1"}) + "\n")
        junit_result = self.root / "junit.stdout.log"
        junit_result.write_text("NATIVE_SOLR_JUNIT_RESULT run=1 failures=0 ignored=0\n")
        campaign_out = self.root / "campaign-prepared"
        campaign_args = argparse.Namespace(
            case_id="SOLR-XX", inventory=self.inventory, source=self.source,
            protocol_receipt=protocol, protocol_patch=patch,
            static_input=self.static_input, static_output=self.static_output,
            sidecars=weave_out / "recording-artifacts", output=campaign_out,
            java=java, engine_root=engine, weave_config=weave_out / "native-weave-config.json",
            trace_dir=trace, junit_result_log=junit_result,
            schedule_index=index, schedule_plan=plan,
            runner_classpath_file=runner_cp, max_jobs=5, analysis_heap_mb=8192,
            trials=3,
            seconds=60, max_faults=2, timeout=30)
        campaign = prep.prepare_campaign(campaign_args)
        self.assertEqual(campaign["target_checks"], 1)
        config = prep.read_json(campaign_out / "campaign-config.json")
        self.assertEqual(config["junit"]["method"], "testRun")
        self.assertEqual(config["budget"]["max_faults_per_trial"], 2)
        self.assertEqual(config["recording"]["graph_analysis_heap_mb"], 8192)
        self.assertEqual(config["target_throw"]["siteId"], self.throw)
        campaign_args.output = self.root / "campaign-no-schedule"
        campaign_args.schedule_index = None
        campaign_args.schedule_plan = None
        campaign_args.admission_mode = "region_state_no_schedule"
        prep.prepare_campaign(campaign_args)
        no_schedule = prep.read_json(campaign_args.output / "campaign-config.json")
        self.assertEqual(no_schedule["recording"]["admission_mode"],
                         "region_state_no_schedule")
        self.assertEqual(no_schedule["target_site"], self.branch)
        self.assertEqual(no_schedule["target_throw"]["siteId"], self.throw)
        self.assertEqual(prep.read_json(campaign_args.output / "preparation-receipt.json")
                         ["schedule"], {"admission_mode": "region_state_no_schedule"})
        campaign_args.schedule_plan = plan
        campaign_args.output = self.root / "campaign-invalid-no-schedule"
        with self.assertRaisesRegex(ValueError, "must not bind a task plan"):
            prep.prepare_campaign(campaign_args)

    def test_existing_solr01_original_artifacts(self):
        root = Path("/proj/silentfailure-PG0/mallory/solr01-native-campaign-v1")
        if not root.is_dir():
            self.skipTest("frozen SOLR-01 receipt is unavailable on this host")
        row = prep.inventory_row("SOLR-01")
        result = prep.validate_static(row, root / "inputs/static-input.json",
                                      root / "inputs", root / "inputs/recording-artifacts")
        self.assertEqual(result["typed_fault_doors"], 32)
        self.assertEqual(result["regions"], 305)
        self.assertEqual(prep.validate_recording(
            root / "inputs/healthy-trace", result["target_site"])["target_checks"], 15)
        self.assertTrue(prep.validate_schedule(
            root / "scheduled-first/runtime_workflow_schedule_index.json",
            root / "scheduled-first/execution_task_plan.jsonl")["target_task_id"].startswith("TASK."))


if __name__ == "__main__":
    unittest.main()
