"""Fixture-backed native campaign tests; no live system campaign is started."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_feedback.feedback import (
    HERE as FEEDBACK_DIR, _classpath, build, summarize_target_set,
)
from Mallory.native_graphchecker_campaign import campaign as core


class NativeCampaignFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not core.JAR.is_file():
            raise unittest.SkipTest("source-built original GraphChecker engine is absent")
        cls.classes = build(engine_jar=core.JAR)
        cls.classpath = f"{cls.classes}:{_classpath(core.JAR)}"
        subprocess.run(["javac", "-cp", cls.classpath, "-d", str(cls.classes),
                        str(FEEDBACK_DIR / "SyntheticNativeSession.java")],
                       check=True, timeout=120, capture_output=True)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / "seed"
        self._generate(self.seed)
        self.woven = self.root / "woven"
        self.woven.mkdir()
        (self.woven / "native-original-weave-receipt.json").write_text("{}\n")
        self.weave_config = self.root / "weave.json"
        self.weave_config.write_text("{}\n")
        self.config_file = self.root / "case.json"
        self.config = {
            "case_id": "FIXTURE-01", "target_site": "Keys#check#u3",
            "target_throw": {"siteId": "Keys#throw#u4",
                             "exceptionClass": "java.io.IOException"},
            "native_weave_config": str(self.weave_config),
            "recording": {"trace_dir": str(self.seed), "test_id": "fixture",
                          "target_name": "fixture",
                          "max_jobs": 256,
                          "candidate_graph": str(self.seed / "graph.jsonl"),
                          "static_scope_map": str(self.seed / "static_scope_map.jsonl"),
                          "region_skeletons": str(self.seed / "regions.jsonl")},
            "junit": {"class": "UnchangedFixtureTest", "method": "testOperation"},
            "runner": {"zero_vm_java": str(self.root / "vm-java"),
                       "main_class": "UnchangedJUnitRunner", "classpath": []},
            "budget": {"fault_trials": 1, "seconds": 60,
                       "max_faults_per_trial": 2},
            "timeout_seconds": 30,
        }
        self.config_file.write_text(json.dumps(self.config))
        self.admitted = {"weave_config": {"output_classes": str(self.woven)},
                         "weave_receipt": {}, "origin": {
                             "recording_plan_sha256": "fixture"},
                         "zero_vm_sha256": "fixture-zero",
                         "runner_classpath_artifacts": []}

    def _generate(self, iteration: Path) -> None:
        subprocess.run(["java", "-cp", self.classpath,
                        "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                        str(iteration)], check=True, timeout=30, capture_output=True)

    def _executor(self, *, emit_door: bool, applied_identity: str | None = None,
                  throw: bool = False):
        def execute(config, admitted, trial, faults):
            iteration = trial / "iteration-native"
            self._generate(iteration)
            if emit_door:
                summary = summarize_target_set(
                    iteration, config["target_site"], trial / "peek.json",
                    static_scope_map=self.seed / "static_scope_map.jsonl",
                    engine_jar=core.JAR)
                writer = next(item for item in summary["closureMembers"]
                              if item["regionId"] == "R.writer")
                target = summary["targetOccurrenceIds"][0]
                door = {"kind": "FAULT_DOOR", "seq": 1,
                        "siteId": "RPC#getKeys", "node": "nn0",
                        "actorEpochOrdinal": 0,
                        "occurrenceId": writer["occurrenceId"], "ordinal": 1,
                        "exceptionClass": "java.io.IOException"}
                rows = [door]
                if faults:
                    applied = {**door, "kind": "FAULT_APPLIED", "seq": 2,
                               "occurrenceId": (applied_identity or
                                                writer["occurrenceId"])}
                    rows.append(applied)
                    if throw:
                        rows.append({"kind": "TARGET_THROW", "seq": 3,
                                     "siteId": "Keys#throw#u4",
                                     "exceptionClass": "java.io.IOException",
                                     "occurrenceId": target})
                (iteration / "fault-events.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows))
            return {"return_code": 0, "timed_out": False,
                    "elapsed_seconds": 0.01}
        return execute

    def _run(self, executor) -> dict:
        with patch.object(core, "_admit", return_value=self.admitted), patch.object(
                core, "_verify_pins"), patch.object(
                core, "_execute_junit", side_effect=executor):
            return core.run_campaign(self.config_file, self.root / "campaign")

    def test_zero_fault_collects_original_native_session(self) -> None:
        state = self._run(self._executor(emit_door=False))
        self.assertEqual("no_observed_fault_door", state["status"])
        self.assertEqual(0, state["completed_fault_trials"])
        healthy = core._load(self.root / "campaign/trials/r0000/result.json")
        self.assertEqual("healthy_seed", healthy["status"])
        self.assertTrue(healthy["native_target_retained"])
        self.assertEqual(1, len(healthy["native_target_occurrence_ids"]))
        self.assertTrue((self.root /
                         "campaign/trials/r0000/native-summary.json").is_file())

    def test_one_generic_fault_requires_exact_receipt_and_target_retention(self) -> None:
        state = self._run(self._executor(emit_door=True, throw=True))
        self.assertEqual("complete_trial_budget", state["status"])
        self.assertEqual(1, state["completed_fault_trials"])
        self.assertEqual("candidate", state["trials"][0]["status"])
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertTrue(faulted["strict_injection"])
        self.assertTrue(faulted["fault_in_target_closure"])
        self.assertTrue(faulted["native_target_retained"])
        self.assertTrue(faulted["target_exception_triggered"])
        self.assertEqual(0, faulted["native_delta"]["newObservedClosureEdges"])
        self.assertTrue((self.root / "campaign/summary.json").is_file())

    def test_cross_run_selector_binds_fresh_exact_occurrence(self) -> None:
        planned = [{"siteId": "RPC#getKeys", "node": "nn0",
                    "actorEpochOrdinal": 1, "ordinal": 2,
                    "exceptionClass": "java.io.IOException",
                    "sourceOccurrenceId": "healthy-process:old"}]
        door = {"kind": "FAULT_DOOR", "seq": 1,
                "siteId": "RPC#getKeys", "node": "nn0",
                "actorEpochOrdinal": 1, "ordinal": 2,
                "exceptionClass": "java.io.IOException",
                "occurrenceId": "trial-process:fresh"}
        applied = {**door, "kind": "FAULT_APPLIED", "seq": 2}
        self.assertEqual((True, 2), core._strict_faults(planned, [door, applied]))
        wrong_epoch = {**applied, "actorEpochOrdinal": 0}
        self.assertEqual((False, None), core._strict_faults(planned, [door, wrong_epoch]))
        wrong_actor = {**applied, "node": "nn1"}
        self.assertEqual((False, None), core._strict_faults(planned, [door, wrong_actor]))

    def test_wrong_fault_occurrence_is_unmatched_and_never_candidate(self) -> None:
        state = self._run(self._executor(emit_door=True,
                                         applied_identity="wrong-occurrence",
                                         throw=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertEqual("unmatched", faulted["status"])
        self.assertFalse(faulted["strict_injection"])
        self.assertFalse(faulted["target_exception_triggered"])
        self.assertEqual([], state["queue"])

    def test_fault_trial_without_target_is_discarded_even_with_throw_receipt(self) -> None:
        native_targets = core.list_native_targets
        seen = 0

        def targets(*args, **kwargs):
            nonlocal seen
            seen += 1
            return native_targets(*args, **kwargs) if seen == 1 else []

        with patch.object(core, "list_native_targets", side_effect=targets):
            state = self._run(self._executor(emit_door=True, throw=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertEqual("target_lost", faulted["status"])
        self.assertFalse(faulted["native_target_retained"])
        self.assertFalse(faulted["target_exception_triggered"])
        self.assertEqual([], state["queue"])

    def test_resume_accepts_completed_trial_without_duplicate_junit(self) -> None:
        self._run(self._executor(emit_door=True, throw=True))
        checkpoint = self.root / "campaign/checkpoint.json"
        state = core._load(checkpoint)
        state["status"], state["terminal"] = "running", False
        state["trials"], state["completed_fault_trials"] = [], 0
        state["active"] = {"index": 1, "name": "r0001", "faults": core._load(
            self.root / "campaign/trials/r0001/result.json")["faults"]}
        core._atomic(checkpoint, state)
        with patch.object(core, "_admit", return_value=self.admitted), patch.object(
                core, "_verify_pins"), patch.object(core, "_execute_junit") as execute:
            resumed = core.run_campaign(self.config_file, self.root / "campaign")
        execute.assert_not_called()
        self.assertEqual(1, resumed["completed_fault_trials"])
        changed = {**self.admitted, "zero_vm_sha256": "different-vm"}
        with patch.object(core, "_admit", return_value=changed):
            with self.assertRaisesRegex(ValueError, "checkpoint inputs changed"):
                core.run_campaign(self.config_file, self.root / "campaign")

    def test_fresh_runner_preserves_junit_identity_and_woven_class_priority(self) -> None:
        java = self.root / "fake-zero-java"
        java.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path('invocation.json').write_text(json.dumps({"
            "'argv': sys.argv[1:], 'sessions': os.environ.get("
            "'CAUSYNTH_CONCOLIC_SESSIONS'), 'plan': os.environ.get("
            "'MALLORY_NATIVE_FAULT_PLAN')}))\n")
        java.chmod(0o755)
        plan = self.root / "execution_task_plan.jsonl"
        plan.write_text('{"taskId":"recorded-task"}\n')
        library = self.root / "library"
        library.mkdir()
        config = dict(self.config)
        config["runner"] = {**config["runner"], "zero_vm_java": str(java),
                            "classpath": [str(library)]}
        admitted = {"weave_config": {"output_classes": str(self.woven),
                                     "task_plan": str(plan),
                                     "task_id": "recorded-task"}}
        trial = self.root / "fresh-trial"
        trial.mkdir()
        result = core._execute_junit(config, admitted, trial, [])
        self.assertEqual(0, result["return_code"])
        invocation = json.loads((trial / "iteration-native/workdir/invocation.json")
                                .read_text())
        argv = invocation["argv"]
        self.assertIn("-Dcausynth.concolic.task.id=recorded-task", argv)
        self.assertEqual(["UnchangedFixtureTest", "testOperation"], argv[-2:])
        self.assertEqual(str(self.woven), argv[argv.index("-cp") + 1].split(os.pathsep)[0])
        self.assertEqual(str(trial / "iteration-native/sessions"),
                         invocation["sessions"])
        self.assertTrue((trial / "iteration-native/fault-plan.json").is_file())

    def test_resume_reuses_content_pinned_recording_admission(self) -> None:
        for name in ("streaming_trace_manifest.json", "graph.jsonl",
                     "static_scope_map.jsonl", "regions.jsonl"):
            (self.seed / name).write_text('{"fixture":true}\n')
        vm = self.root / "vm-java"
        vm.write_text("fixture-vm\n")
        scheduler = self.root / "ConcolicScheduler.java"
        scheduler.write_text("// pinned fixture source\n")
        self.weave_config.write_text(json.dumps({"output_classes": str(self.woven)}))
        output = self.root / "admission"
        output.mkdir()
        with patch.object(core, "verify_existing", return_value={"verified": True}), patch.object(
                core, "_scheduler_source", return_value=scheduler), patch.object(
                core, "_verify_recording_plan", return_value={"plan": "derived"}) as derive:
            first = core._admit(self.config, output)
            second = core._admit(self.config, output)
            self.assertEqual(first["origin"], second["origin"])
            derive.assert_called_once()
            (self.seed / "graph.jsonl").write_text("changed graph\n")
            with self.assertRaisesRegex(ValueError, "admission inputs changed"):
                core._admit(self.config, output)


if __name__ == "__main__":
    unittest.main()
