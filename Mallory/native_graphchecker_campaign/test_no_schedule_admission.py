"""Original REGION_STATE admission without an ahead-of-campaign task plan."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign as core


class NoScheduleAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.trace = self.root / "trace"
        self.trace.mkdir()
        (self.trace / "streaming_trace_manifest.json").write_text(json.dumps({
            "schemaVersion": 2, "kind": "STREAMING_RUNTIME_TRACE",
            "status": "CLOSED", "tracedRows": "pinned-row-digest"}))
        (self.trace / "runtime_trace.jsonl").write_text('{"kind":"TEST"}\n')
        (self.trace / "schedule.jsonl").write_text('{"kind":"SCHEDULE"}\n')
        self.scope = self.root / "scope.jsonl"
        self.graph = self.root / "graph.jsonl"
        self.skeletons = self.root / "skeletons.jsonl"
        for path in (self.scope, self.graph, self.skeletons):
            path.write_text(path.name + "\n")
        self.woven = self.root / "woven-skeletons.jsonl"
        self.woven.write_bytes(self.skeletons.read_bytes())
        self.java = self.root / "java"
        self.java.write_text("java")
        self.jar = self.root / "engine.jar"
        self.jar.write_text("engine")
        self.weave_file = self.root / "weave.json"
        self.output_classes = self.root / "classes"
        self.output_classes.mkdir()
        (self.output_classes / "native-original-weave-receipt.json").write_text(
            '{"schema_version":1}\n')
        core._atomic(self.weave_file, {
            "java": str(self.java), "region_skeletons": str(self.woven),
            "output_classes": str(self.output_classes)})
        self.config = {
            "case_id": "HBASE-TEST", "target_site": "Target#u1",
            "target_throw": {"siteId": "Target#u2",
                             "exceptionClass": "java.io.IOException"},
            "native_weave_config": str(self.weave_file),
            "recording": {
                "admission_mode": "region_state_no_schedule",
                "trace_dir": str(self.trace), "test_id": "Test#testMethod",
                "target_name": "target", "candidate_graph": str(self.graph),
                "static_scope_map": str(self.scope),
                "region_skeletons": str(self.skeletons), "max_jobs": 8},
            "junit": {"class": "Test", "method": "testMethod"},
            "runner": {"mode": "region_state", "zero_vm_java": str(self.java),
                       "main_class": "Runner", "classpath": [str(self.jar)]},
            "budget": {"fault_trials": 2, "seconds": 60,
                       "max_faults_per_trial": 2}, "timeout_seconds": 30}

    def test_no_schedule_binds_closed_inputs_without_invoking_planner(self) -> None:
        core._validate_config(self.config)
        weave = core._load(self.weave_file)
        with patch.object(core.subprocess, "run") as run:
            origin = core._verify_recording_plan(self.config, weave, self.root)
        run.assert_not_called()
        self.assertEqual("region_state_no_schedule", origin["admission_mode"])
        self.assertEqual(core._sha(self.scope), origin["static_scope_map_sha256"])
        self.assertNotIn("recording_plan_sha256", origin)
        self.assertEqual(core._sha(self.trace / "runtime_trace.jsonl"),
                         origin["closed_inputs"]["runtimeTraceSha256"])

    def test_cached_admission_resumes_and_rejects_changed_trace(self) -> None:
        with (patch.object(core, "JAR", self.jar),
              patch.object(core, "_scheduler_source", return_value=self.jar),
              patch.object(core, "verify_existing", return_value={"verified": True}),
              patch.object(core, "dependency_digests", return_value=[]),
              patch.object(core.subprocess, "run") as run):
            first = core._admit(self.config, self.root)
            second = core._admit(self.config, self.root)
            self.assertEqual(first["origin"], second["origin"])
            run.assert_not_called()
            (self.trace / "runtime_trace.jsonl").write_text("mutated\n")
            with self.assertRaisesRegex(ValueError, "cached native recording"):
                core._admit(self.config, self.root)

    def test_optional_static_may_map_has_own_pin_and_keeps_seed_digest(self) -> None:
        may = self.root / "static-may.jsonl"
        may.write_text(json.dumps({"kind": "STATIC_SCOPE_SITE",
                                   "role": "TARGET_SITE", "siteId": "Target#u1",
                                   "regionId": "target-region"}) + "\n")
        self.config["recording"].update({
            "static_may_scope_map": str(may),
            "static_may_scope_sha256": core._sha(may),
        })
        core._validate_config(self.config)
        with (patch.object(core, "JAR", self.jar),
              patch.object(core, "_scheduler_source", return_value=self.jar),
              patch.object(core, "verify_existing", return_value={"verified": True}),
              patch.object(core, "dependency_digests", return_value=[])):
            first = core._admit(self.config, self.root)
            self.assertEqual(core._sha(self.scope), first["origin"][
                "static_scope_map_sha256"])
            self.assertEqual(core._sha(may), first["origin"][
                "static_may_scope_sha256"])
            core._verify_pins(self.config, first)
            may.write_text(may.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "static MAY scope SHA-256 mismatch"):
                core._admit(self.config, self.root)
            with self.assertRaisesRegex(ValueError, "static MAY scope map changed"):
                core._verify_pins(self.config, first)

    def test_pinned_analysis_engine_is_separate_from_woven_engine(self) -> None:
        analyzer = self.root / "optimized-analyzer.jar"
        analyzer.write_bytes(b"optimized original region analyzer")
        self.config["recording"].update({
            "analysis_engine_jar": str(analyzer),
            "analysis_engine_sha256": core._sha(analyzer),
        })
        core._validate_config(self.config)
        with (patch.object(core, "JAR", self.jar),
              patch.object(core, "_scheduler_source", return_value=self.jar),
              patch.object(core, "verify_existing", return_value={"verified": True}),
              patch.object(core, "dependency_digests", return_value=[])):
            self.assertEqual(analyzer, core._analysis_engine_jar(self.config))
            core._admit(self.config, self.root)
            admitted = core._load(self.root / "recording-admission.json")
            self.assertEqual(core._sha(self.jar), admitted[
                "recording_fingerprint"]["engine_jar_sha256"])
            self.assertEqual(core._sha(analyzer), admitted[
                "recording_fingerprint"]["analysis_engine_sha256"])
            analyzer.write_bytes(b"mutated analyzer")
            with self.assertRaisesRegex(ValueError, "analysis engine SHA-256 mismatch"):
                core._admit(self.config, self.root)

    def test_analysis_engine_requires_region_mode_and_complete_pin(self) -> None:
        self.assertEqual(core.JAR, core._analysis_engine_jar(self.config))
        self.config["recording"]["analysis_engine_jar"] = str(self.root / "analyzer.jar")
        with self.assertRaisesRegex(ValueError, "analysis engine requires"):
            core._validate_config(self.config)
        self.config["recording"]["analysis_engine_sha256"] = "0" * 64
        self.config["runner"]["mode"] = "concolic"
        with self.assertRaisesRegex(ValueError, "analysis engine requires"):
            core._validate_config(self.config)
        self.config["runner"]["mode"] = "region_state"
        self.config["recording"]["analysis_engine_jar"] = None
        with self.assertRaisesRegex(ValueError, "absolute path"):
            core._validate_config(self.config)
        self.config["recording"]["analysis_engine_jar"] = "relative.jar"
        with self.assertRaisesRegex(ValueError, "absolute path"):
            core._validate_config(self.config)

    def test_no_schedule_rejects_concolic_runner_and_woven_task(self) -> None:
        self.config["runner"]["mode"] = "concolic"
        with self.assertRaisesRegex(ValueError, "requires REGION_STATE"):
            core._validate_config(self.config)
        self.config["runner"]["mode"] = "region_state"
        weave = core._load(self.weave_file)
        weave["task_id"] = "unrelated"
        with self.assertRaisesRegex(ValueError, "carries a concolic task"):
            core._verify_recording_plan(self.config, weave, self.root)

    def test_legacy_scheduled_region_state_still_runs_planner(self) -> None:
        self.config["recording"].pop("admission_mode")
        selected = self.root / "selected.jsonl"
        selected.write_text('{"taskId":"TASK-1"}\n')
        weave = core._load(self.weave_file)
        weave["task_plan"] = str(selected)

        def produce(argv: list[str], **_kwargs: object) -> None:
            if any(item.endswith(".CausynthTraceRecorder") for item in argv):
                output = Path(argv[argv.index("--target") + 1].split("=", 1)[1].split(",")[-1])
                output.mkdir(parents=True)
                (output / "concolic_region_plan.jsonl").write_text("plan\n")
                (output / "region_skeletons.jsonl").write_bytes(
                    self.skeletons.read_bytes())
            else:
                output = Path(argv[argv.index("--output-dir") + 1])
                output.mkdir(parents=True)
                (output / "execution_task_plan.jsonl").write_bytes(
                    selected.read_bytes())
                (output / "runtime_workflow_schedule_index.json").write_text("{}\n")

        with patch.object(core.subprocess, "run", side_effect=produce) as run:
            origin = core._verify_recording_plan(self.config, weave, self.root)
        self.assertEqual(2, run.call_count)
        self.assertEqual(core._sha(selected), origin["recording_plan_sha256"])
        self.assertNotIn("admission_mode", origin)


if __name__ == "__main__":
    unittest.main()
