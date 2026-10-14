"""A prepared plan may replace only identical same-trace admission work."""

from __future__ import annotations

import json
import gzip
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign as core


class PrecomputedScheduleTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.trace = self.root / "trace"
        self.trace.mkdir()
        self._write(self.trace / "streaming_trace_manifest.json", {
            "schemaVersion": 2, "kind": "STREAMING_RUNTIME_TRACE",
            "status": "CLOSED", "tracedRows": "trace-digest"})
        (self.trace / "runtime_trace.jsonl").write_text("trace\n")
        (self.trace / "schedule.jsonl").write_text("schedule\n")
        self.graph = self.root / "candidate.jsonl.gz"
        self.scope = self.root / "scope.jsonl"
        self.skeletons = self.root / "skeletons.jsonl.gz"
        for file in (self.graph, self.scope, self.skeletons):
            file.write_text(file.name)
        self.java, self.jar, self.dependencies = (
            self.root / name for name in ("java", "engine.jar", "dependencies.txt"))
        self.java.write_text("java")
        self.jar.write_text("engine")
        self.dependencies.write_text("dependency.jar\n")
        self.scheduler_source = self.root / "ConcolicScheduler.java"
        self.scheduler_source.write_text("source")
        self.woven = self.root / "woven-skeletons.jsonl.gz"
        shutil.copyfile(self.skeletons, self.woven)
        self.weave_file = self.root / "weave.json"
        self.classes = self.root / "classes"
        self.classes.mkdir()
        (self.classes / "native-original-weave-receipt.json").write_text("{}\n")
        self._write(self.weave_file, {"java": str(self.java),
                                      "region_skeletons": str(self.woven),
                                      "output_classes": str(self.classes)})
        self.recorded, self.scheduled = (self.root / name for name in
                                         ("recorded", "scheduled"))
        self.recorded.mkdir()
        self.scheduled.mkdir()
        (self.recorded / "concolic_region_plan.jsonl").write_text("plan\n")
        shutil.copyfile(self.skeletons, self.recorded / "region_skeletons.jsonl")
        (self.scheduled / "execution_task_plan.jsonl").write_text(
            '{"taskId":"task-1"}\n')
        (self.scheduled / "runtime_workflow_schedule_index.json").write_text("{}\n")
        self.config = {
            "case_id": "HDFS-TEST", "target_site": "Guard#u1",
            "target_throw": {"siteId": "Throw#u2",
                             "exceptionClass": "java.io.IOException"},
            "native_weave_config": str(self.weave_file),
            "recording": {"trace_dir": str(self.trace),
                          "test_id": "Test#original", "target_name": "HDFSTEST",
                          "target_occurrence": "actor/region/one",
                          "candidate_graph": str(self.graph),
                          "static_scope_map": str(self.scope),
                          "region_skeletons": str(self.skeletons),
                          "max_jobs": 4,
                          "recorder_jvm_args": ["-Dcausynth.loop.default.bound=3"],
                          "scheduler_jvm_args": ["-Dcausynth.loop.default.bound=3"]},
            "junit": {"class": "Test", "method": "original"},
            "runner": {"mode": "region_state", "zero_vm_java": str(self.java),
                       "main_class": "Runner", "classpath": [str(self.jar)]},
            "budget": {"fault_trials": 2, "seconds": 60,
                       "max_faults_per_trial": 2}, "timeout_seconds": 30}
        target = f"HDFSTEST={self.graph},{self.scope},{self.skeletons},{self.recorded}"
        prefix = [str(self.java), "-Xmx1024m",
                  "-Dcausynth.loop.default.bound=3", "-cp",
                  f"{self.jar}:dependency.jar"]
        self.recorder_command = self.root / "recorder.json"
        self.scheduler_command = self.root / "scheduler.json"
        self._write(self.recorder_command, {"argv": [*prefix,
            "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
            "--trace-dir", str(self.trace), "--test", "Test#original",
            "--target", target, "--target-occurrence", "actor/region/one"]})
        self._write(self.scheduler_command, {"argv": [*prefix,
            "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler",
            "--region-plan", str(self.recorded / "concolic_region_plan.jsonl"),
            "--candidate-graph", str(self.graph), "--static-scope-map",
            str(self.scope), "--output-dir", str(self.scheduled), "--max-jobs",
            "4", "--target-occurrence", "actor/region/one"]})
        self.receipt = self.root / "precomputed.json"

    @staticmethod
    def _write(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, sort_keys=True) + "\n")

    def _pins(self):
        return (patch.object(core, "JAR", self.jar),
                patch.object(core, "DEPENDENCIES", self.dependencies),
                patch.object(core, "_scheduler_source",
                             return_value=self.scheduler_source))

    def _seal(self) -> dict:
        with self._pins()[0], self._pins()[1], self._pins()[2]:
            sealed = core.seal_precomputed_schedule(
                self.config, self.recorded, self.scheduled,
                self.recorder_command, self.scheduler_command, self.receipt)
        self.config["recording"]["precomputed_schedule"] = str(self.receipt)
        return sealed

    def test_precomputed_lineage_equals_recomputed_lineage_without_java(self) -> None:
        self._seal()
        weave = core._load(self.weave_file)
        with self._pins()[0], self._pins()[1], self._pins()[2], patch.object(
                core.subprocess, "run") as run:
            reuse = core._verify_recording_plan(self.config, weave, self.root)
            run.assert_not_called()
            self.config["recording"].pop("precomputed_schedule")

            def derive(argv: list[str], **_kwargs: object) -> None:
                if "CausynthTraceRecorder" in " ".join(argv):
                    destination = Path(argv[argv.index("--target") + 1].split(",")[-1])
                    destination.mkdir(parents=True)
                    for name in ("concolic_region_plan.jsonl", "region_skeletons.jsonl"):
                        shutil.copyfile(self.recorded / name, destination / name)
                else:
                    destination = Path(argv[argv.index("--output-dir") + 1])
                    destination.mkdir(parents=True)
                    for name in ("execution_task_plan.jsonl",
                                 "runtime_workflow_schedule_index.json"):
                        shutil.copyfile(self.scheduled / name, destination / name)

            run.side_effect = derive
            recomputed = core._verify_recording_plan(self.config, weave, self.root)
            self.assertEqual(2, run.call_count)
        reuse.pop("precomputed_schedule_receipt_sha256")
        self.assertEqual(recomputed, reuse)

    def test_compressed_region_plan_seals_and_rechecks_exact_bytes(self) -> None:
        plain = self.recorded / "concolic_region_plan.jsonl"
        compressed = self.recorded / "concolic_region_plan.jsonl.gz"
        compressed.write_bytes(gzip.compress(plain.read_bytes(), mtime=0))
        plain.unlink()
        command = core._load(self.scheduler_command)
        argv = command["argv"]
        argv[argv.index("--region-plan") + 1] = str(compressed)
        self._write(self.scheduler_command, command)
        sealed = self._seal()
        self.assertEqual(core._sha(compressed), sealed["artifacts_sha256"]["region_plan"])
        weave = core._load(self.weave_file)
        with self._pins()[0], self._pins()[1], self._pins()[2]:
            core._verify_recording_plan(self.config, weave, self.root)
            compressed.write_bytes(compressed.read_bytes() + b"changed")
            with self.assertRaises(ValueError):
                core._verify_recording_plan(self.config, weave, self.root)

    def test_mutated_trace_plan_command_or_engine_fails_closed(self) -> None:
        self._seal()
        weave = core._load(self.weave_file)
        for path in (self.trace / "runtime_trace.jsonl",
                     self.recorded / "concolic_region_plan.jsonl",
                     self.scheduler_command, self.jar):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"mutated")
                try:
                    with self._pins()[0], self._pins()[1], self._pins()[2]:
                        with self.assertRaises(ValueError):
                            core._verify_recording_plan(self.config, weave,
                                                        self.root)
                finally:
                    path.write_bytes(original)

    def test_changed_target_selection_rejects_reuse(self) -> None:
        self._seal()
        self.config["recording"]["target_occurrence"] = "other/region"
        with self._pins()[0], self._pins()[1], self._pins()[2]:
            with self.assertRaises(ValueError):
                core._verify_recording_plan(self.config,
                                            core._load(self.weave_file), self.root)

    def test_cached_admission_rechecks_preparation_artifacts(self) -> None:
        self._seal()
        with self._pins()[0], self._pins()[1], self._pins()[2], patch.object(
                core, "verify_existing", return_value={"verified": True}), patch.object(
                core, "dependency_digests", return_value=[]), patch.object(
                core, "_require_exact_resolver_protocol", return_value={
                    "analysis_engine_jar_sha256": "fixture-engine",
                    "capabilities": {"exactRequestedOccurrenceReceiptSchemaVersion": 2}}), patch.object(
                core.subprocess, "run") as run:
            first = core._admit(self.config, self.root)
            second = core._admit(self.config, self.root)
            self.assertEqual(first["origin"], second["origin"])
            run.assert_not_called()
            with (self.scheduled / "execution_task_plan.jsonl").open("a") as file:
                file.write('{"taskId":"another"}\n')
            with self.assertRaises(ValueError):
                core._admit(self.config, self.root)


if __name__ == "__main__":
    unittest.main()
