"""Queue isolation and durable completion tests without distributed JUnit."""

from __future__ import annotations

import json
import hashlib
import fcntl
import multiprocessing
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, load_inventory, load_ownership,
)
from .queue import (_cached_terminal_inspection, completion, pilot_receipt,
                    run_worker, sha,
                    validate_isolation)


class NativeQueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_root = self.root / "config"
        self.state_root = self.root / "state"
        self.scratch_root = self.root / "scratch"
        self.config_root.mkdir()
        self.state_root.mkdir()
        self.scratch_root.mkdir()
        self.cases, by_id = load_inventory(DEFAULT_INVENTORY)
        self.owners = load_ownership(DEFAULT_OWNERSHIP, set(by_id))
        self.item = next(item for item in self.cases if item["case_id"] == "HBASE-01")
        self.case_id = self.item["case_id"]
        self.config_file = self.config_root / f"{self.case_id}.json"
        self.config = {"runner": {"jvm_args": [
            "-Djava.io.tmpdir={trial_workdir}",
            "-Dtest.build.data.basedirectory={trial_workdir}",
            "-Dhbase.test.port=0"]}}
        self.config_file.write_text(json.dumps(self.config))
        receipt = self.root / "ports.json"
        receipt.write_text(json.dumps({"schema_version": 1, "system": "hbase",
                                       "all_listeners_bind_port_zero": True}))
        self.isolation = self.root / "isolation.json"
        self.profile = {"schema_version": 1, "systems": {"hbase": {
            "ports": {"mode": "ephemeral", "receipt": str(receipt),
                      "evidence": {str(receipt): sha(receipt)}},
            "required_jvm_args": ["-Dhbase.test.port=0"]}}}
        self.isolation.write_text(json.dumps(self.profile))

    def test_ephemeral_requires_receipt_and_isolated_dirs(self) -> None:
        policy = validate_isolation(self.profile, "hbase", self.case_id,
                                    self.config, self.owners, "node1")
        self.assertEqual(policy["mode"], "ephemeral")
        self.config["runner"]["jvm_args"].append("-Dbuild.test.dir=/tmp/shared")
        with self.assertRaisesRegex(ValueError, "isolated tmpdir"):
            validate_isolation(self.profile, "hbase", self.case_id,
                               self.config, self.owners, "node1")
        self.config["runner"]["jvm_args"].pop()
        self.profile["systems"]["hbase"]["ports"].pop("receipt")
        with self.assertRaisesRegex(ValueError, "dynamic-port receipt"):
            validate_isolation(self.profile, "hbase", self.case_id,
                               self.config, self.owners, "node1")

    def test_assigned_ranges_reject_collision(self) -> None:
        ports = self.profile["systems"]["hbase"]["ports"]
        ports.update(mode="assigned", cases={
            "HBASE-01": {"start": 20000, "count": 100,
                         "required_jvm_args": ["-Dhbase.test.port=0"]},
            "HBASE-02": {"start": 20050, "count": 100,
                         "required_jvm_args": ["-Dhbase.test.port=20050"]}})
        with self.assertRaisesRegex(ValueError, "port ranges overlap"):
            validate_isolation(self.profile, "hbase", self.case_id,
                               self.config, self.owners, "node1")

    def test_hdfs_solr_trial_data_properties_and_hbase_random_retry(self) -> None:
        for property_name in ("test.build.data", "solr.log.dir"):
            config = {"runner": {"jvm_args": [
                "-Djava.io.tmpdir={trial_workdir}",
                f"-D{property_name}={{trial_workdir}}",
                "-Dhbase.test.port=0"]}}
            self.assertEqual(validate_isolation(
                {"schema_version": 1, "systems": {"hbase": self.profile[
                    "systems"]["hbase"]}}, "hbase", self.case_id,
                config, self.owners, "node1")["mode"], "ephemeral")
            config["runner"]["jvm_args"][-1] = f"-D{property_name}=/tmp/shared"
            with self.assertRaisesRegex(ValueError, "isolated tmpdir"):
                validate_isolation(self.profile, "hbase", self.case_id,
                                   config, self.owners, "node1")

        source = self.root / "MiniZooKeeperCluster.java"
        source.write_text("pinned source fixture\n")
        receipt = self.root / "review.json"
        receipt.write_text(json.dumps({
            "schema_version": 1, "system": "hbase", "case_id": self.case_id,
            "mode": "source_reviewed_random_retry",
            "zk_random_port_range": [49152, 65279],
            "zk_bind_exception_retry": True,
            "hbase_cluster_default_ports_zero": True,
            "reviewed_source_sha256": {str(source): sha(source)}}))
        ports = self.profile["systems"]["hbase"]["ports"]
        ports.update(mode="random_retry", receipt=str(receipt),
                     evidence={str(source): sha(source), str(receipt): sha(receipt)})
        self.assertEqual(validate_isolation(self.profile, "hbase", self.case_id,
                                            self.config, self.owners,
                                            "node1")["mode"], "random_retry")
        with self.assertRaisesRegex(ValueError, "does not cover this JUnit"):
            validate_isolation(self.profile, "hbase", "HBASE-02",
                               self.config, self.owners, "node1")

    def test_resume_uses_terminal_receipt_without_second_run(self) -> None:
        calls = []

        def inspect(item, owner, config_root, state_root, review=None):
            done = (state_root / item["case_id"] / "summary.json").exists()
            return {"terminal_disposition": "tested_candidate" if done else "ready",
                    "native_tested_complete": done,
                    "fault_trials": 2 if done else 0,
                    "strict_fault_trials": 1 if done else 0,
                    "target_retained_fault_trials": 1 if done else 0,
                    "target_throw_trials": 1 if done else 0,
                    "candidate_trials": 1 if done else 0,
                    "elapsed_seconds": 12.5 if done else 0}

        def runner(config_file, state_root):
            calls.append((config_file, state_root))
            (state_root / "summary.json").write_text('{"terminal":true}\n')
            return {}

        args = dict(host="node1", slot=0, slots=1,
                    inventory=DEFAULT_INVENTORY,
                    ownership_file=DEFAULT_OWNERSHIP,
                    config_root=self.config_root, state_root=self.state_root,
                    scratch_root=self.scratch_root,
                    isolation_file=self.isolation, only_case=self.case_id,
                    min_memory_gib=0, min_state_gib=0,
                    min_scratch_gib=0, runner=runner)
        with patch("Mallory.native_graphchecker_queue.queue.physical_host"), patch(
                "Mallory.native_graphchecker_queue.queue.inspect_case", side_effect=inspect):
            first = run_worker(**args)
            second = run_worker(**args)
        self.assertEqual(first["completed"], 1)
        self.assertEqual(second["completed"], 0)
        self.assertEqual(len(calls), 1)
        receipt = json.loads((self.state_root / ".native-queue/completions" /
                              f"{self.case_id}.json").read_text())
        self.assertTrue(receipt["bug_candidate"])
        self.assertEqual(receipt["fault_trials"], 2)
        self.assertEqual(receipt["target_site"], self.item["target"]["site_id"])
        self.assertEqual(len(list((self.state_root / ".native-queue/attempts" /
                                   self.case_id).glob("*.json"))), 1)

    def test_pilot_receipt_seeds_terminal_cache_and_rejects_changed_summary(self) -> None:
        self.config["case_id"] = self.case_id
        self.config_file.write_text(json.dumps(self.config))
        native_root = self.state_root / self.case_id
        native_root.mkdir()
        checkpoint = {"case_id": self.case_id, "config_sha256": sha(self.config_file),
                      "terminal": True, "status": "complete_trial_budget"}
        (native_root / "checkpoint.json").write_text(json.dumps(checkpoint))
        (native_root / "summary.json").write_text(json.dumps(checkpoint))
        row = {"terminal_disposition": "tested_no_target_throw",
               "native_tested_complete": True, "fault_trials": 1,
               "strict_fault_trials": 1, "target_retained_fault_trials": 1,
               "target_throw_trials": 0, "candidate_trials": 0,
               "elapsed_seconds": 1.0}
        completion(self.item, row, self.config_file, self.state_root,
                   self.state_root / ".native-queue")
        pilot = self.root / "pilot.json"
        pilot.write_text(json.dumps({
            "schema_version": 1, "passed": True, "case_id": self.case_id,
            "host": "node1", "inventory_sha256": sha(DEFAULT_INVENTORY),
            "ownership_sha256": sha(DEFAULT_OWNERSHIP),
            "isolation_sha256": sha(self.isolation),
            "config_sha256": sha(self.config_file),
            "summary_sha256": sha(native_root / "summary.json")}))
        with patch("Mallory.native_graphchecker_queue.queue.physical_host"), patch(
                "Mallory.native_graphchecker_queue.queue.inspect_case",
                side_effect=AssertionError("terminal JUnit was re-audited")):
            pilot_receipt(pilot, DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                          self.config_root, self.state_root, self.cases,
                          self.owners, self.isolation)
            result = run_worker(
                host="node1", slot=0, slots=1, inventory=DEFAULT_INVENTORY,
                ownership_file=DEFAULT_OWNERSHIP,
                config_root=self.config_root, state_root=self.state_root,
                scratch_root=self.scratch_root, isolation_file=self.isolation,
                results_dir=self.root / "native-results",
                only_case=self.case_id, min_memory_gib=0, min_state_gib=0,
                min_scratch_gib=0,
                runner=lambda *_: self.fail("terminal campaign was rerun"))
            self.assertEqual(result["completed"], 0)
        published = json.loads((self.root / "native-results" /
                                "native-102-results.json").read_text())
        self.assertEqual(published["verified_terminal_count"], 1)
        cache = json.loads((self.state_root / ".native-queue/audits" /
                            f"{self.case_id}.json").read_text())
        self.assertEqual(cache["basis"], "pinned_pilot_and_completion_receipts")
        self.assertEqual(cache["fingerprint"]["checkpoint_sha256"],
                         sha(native_root / "checkpoint.json"))
        (native_root / "summary.json").write_text(json.dumps({**checkpoint,
                                                               "changed": True}))
        with self.assertRaisesRegex(ValueError, "pilot evidence changed"):
            pilot_receipt(pilot, DEFAULT_INVENTORY, DEFAULT_OWNERSHIP,
                          self.config_root, self.state_root, self.cases,
                          self.owners, self.isolation)

    def test_terminal_cache_invalidates_on_checkpoint_summary_or_config_change(self) -> None:
        self.config["case_id"] = self.case_id
        self.config_file.write_text(json.dumps(self.config))
        native_root = self.state_root / self.case_id
        native_root.mkdir()
        state = {"case_id": self.case_id, "terminal": True,
                 "config_sha256": sha(self.config_file)}
        checkpoint = native_root / "checkpoint.json"
        summary = native_root / "summary.json"
        checkpoint.write_text(json.dumps(state))
        summary.write_text(json.dumps(state))
        row = {"terminal_disposition": "tested_no_target_throw",
               "native_tested_complete": True}
        with patch("Mallory.native_graphchecker_queue.queue.inspect_case",
                   return_value=row) as inspect:
            for _ in range(2):
                self.assertEqual(_cached_terminal_inspection(
                    self.item, "node1", self.config_root, self.state_root), row)
            self.assertEqual(inspect.call_count, 1)
            checkpoint.write_text(json.dumps({**state, "checkpoint_edit": 1}))
            _cached_terminal_inspection(self.item, "node1", self.config_root,
                                        self.state_root)
            self.assertEqual(inspect.call_count, 2)
            summary.write_text(json.dumps({**state, "summary_edit": 1}))
            _cached_terminal_inspection(self.item, "node1", self.config_root,
                                        self.state_root)
            self.assertEqual(inspect.call_count, 3)
            self.config_file.write_text(json.dumps({**self.config, "config_edit": 1}))
            _cached_terminal_inspection(self.item, "node1", self.config_root,
                                        self.state_root)
            self.assertEqual(inspect.call_count, 4)

    def test_bound_region_campaign_skips_live_lock_and_adopts_native_root(self) -> None:
        native_config = self.root / "immutable-native-config.json"
        native_root = self.root / "immutable-native-state"
        native_root.mkdir()
        native = {"case_id": self.case_id + "-native-fixture",
                  "runner": {"mode": "region_state",
                             "jvm_args": self.config["runner"]["jvm_args"]},
                  "junit": {"class": "OriginalTest", "method": "testOriginal"}}
        native_config.write_text(json.dumps(native) + "\n")
        row_sha = hashlib.sha256(json.dumps(
            self.item, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.config_file.write_text(json.dumps({
            "schema_version": 1, "mode": "native_region_state_case_binding",
            "inventory_case_id": self.case_id,
            "inventory_row_sha256": row_sha,
            "native_case_id": native["case_id"],
            "native_config_path": str(native_config),
            "native_config_sha256": sha(native_config),
            "native_state_path": str(native_root)}) + "\n")
        calls = []

        def inspect(*_args):
            done = (native_root / "summary.json").exists()
            return {"terminal_disposition": "tested_no_target_throw" if done else
                    "resumable", "native_tested_complete": done,
                    "fault_trials": 1, "strict_fault_trials": 1,
                    "target_retained_fault_trials": 1,
                    "target_throw_trials": 0, "candidate_trials": 0,
                    "elapsed_seconds": 3.0}

        def runner(config_file, root):
            calls.append((config_file, root))
            (root / "summary.json").write_text('{"terminal":true}\n')
            return {}

        args = dict(host="node1", slot=0, slots=1,
                    inventory=DEFAULT_INVENTORY,
                    ownership_file=DEFAULT_OWNERSHIP,
                    config_root=self.config_root, state_root=self.state_root,
                    scratch_root=self.scratch_root,
                    isolation_file=self.isolation, only_case=self.case_id,
                    min_memory_gib=0, min_state_gib=0,
                    min_scratch_gib=0, runner=runner)
        with (native_root / ".campaign.lock").open("a+") as lock, patch(
                "Mallory.native_graphchecker_queue.queue.physical_host"), patch(
                "Mallory.native_graphchecker_queue.queue.inspect_case",
                side_effect=inspect):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(0, run_worker(**args)["completed"])
            self.assertEqual([], calls)
            fcntl.flock(lock, fcntl.LOCK_UN)
            self.assertEqual(1, run_worker(**args)["completed"])
        self.assertEqual([(native_config, native_root)], calls)
        receipt = json.loads((self.state_root / ".native-queue/completions" /
                              f"{self.case_id}.json").read_text())
        self.assertEqual(native["case_id"], receipt["native_case_id"])
        self.assertEqual(sha(self.config_file), receipt["binding_sha256"])
        self.assertEqual(str(native_root / "summary.json"), receipt["summary_path"])

    def test_bind_collision_never_publishes_completion(self) -> None:
        case_root = self.state_root / self.case_id
        log = case_root / "trials/r0000/stderr.log"
        log.parent.mkdir(parents=True)
        log.write_text("java.net.BindException: Address already in use\n")
        (case_root / "summary.json").write_text('{"terminal":true}\n')
        row = {"terminal_disposition": "tested_candidate",
               "native_tested_complete": True, "fault_trials": 1,
               "strict_fault_trials": 1, "target_retained_fault_trials": 1,
               "target_throw_trials": 1, "candidate_trials": 1,
               "elapsed_seconds": 4.0}
        queue_root = self.state_root / ".native-queue"
        with self.assertRaisesRegex(ValueError, "port collision"):
            completion(self.item, row, self.config_file, self.state_root,
                       queue_root)
        self.assertFalse((queue_root / "completions" /
                          f"{self.case_id}.json").exists())
        self.assertTrue((queue_root / "invalid-overlap" /
                         f"{self.case_id}.json").exists())

    def test_two_workers_isolate_and_resume_distinct_cases(self) -> None:
        second_id = "HBASE-02"
        second_config = self.config_root / f"{second_id}.json"
        second_config.write_text(json.dumps({"runner": {"jvm_args": [
            "-Djava.io.tmpdir={trial_workdir}",
            "-Dtest.build.data.basedirectory={trial_workdir}",
            "-Dhbase.test.port=20100"]}}))
        self.config["runner"]["jvm_args"][-1] = "-Dhbase.test.port=20000"
        self.config_file.write_text(json.dumps(self.config))
        policy = self.profile["systems"]["hbase"]
        policy["required_jvm_args"] = []
        policy["ports"] = {"mode": "assigned",
                           "evidence": policy["ports"]["evidence"],
                           "cases": {
                               self.case_id: {
                                   "start": 20000, "count": 100,
                                   "required_jvm_args": ["-Dhbase.test.port=20000"]},
                               second_id: {
                                   "start": 20100, "count": 100,
                                   "required_jvm_args": ["-Dhbase.test.port=20100"]}}}
        self.isolation.write_text(json.dumps(self.profile))

        def inspect(item, owner, config_root, state_root, review=None):
            case_id = item["case_id"]
            if case_id not in (self.case_id, second_id):
                return {"terminal_disposition": "needs_native_preparation"}
            root = state_root / case_id
            done = (root / "summary.json").exists()
            phase = ("tested_no_target_throw" if done else "resumable" if
                     (root / "checkpoint.json").exists() else "ready")
            return {"terminal_disposition": phase,
                    "native_tested_complete": done,
                    "fault_trials": 1 if done else 0,
                    "strict_fault_trials": 1 if done else 0,
                    "target_retained_fault_trials": 1 if done else 0,
                    "target_throw_trials": 0, "candidate_trials": 0,
                    "elapsed_seconds": 1.0 if done else 0}

        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(2)
        events = context.Queue()

        def first_runner(config_file, root):
            case_id = config_file.stem
            args = json.loads(config_file.read_text())["runner"]["jvm_args"]
            port = next(arg for arg in args if arg.startswith("-Dhbase.test.port="))
            workdir = root / "trials/r0000/iteration-native/workdir"
            workdir.mkdir(parents=True)
            (root / "checkpoint.json").write_text('{"terminal":false}\n')
            events.put(("start", case_id, os.environ["TMPDIR"],
                        str(workdir), port))
            barrier.wait(timeout=5)
            if case_id == second_id:
                time.sleep(0.5)
                raise RuntimeError("synthetic interrupted campaign")
            time.sleep(0.1)
            (root / "checkpoint.json").write_text('{"terminal":true}\n')
            (root / "summary.json").write_text('{"terminal":true}\n')
            events.put(("finish", case_id))

        args = dict(host="node1", slots=2,
                    inventory=DEFAULT_INVENTORY,
                    ownership_file=DEFAULT_OWNERSHIP,
                    config_root=self.config_root, state_root=self.state_root,
                    scratch_root=self.scratch_root,
                    isolation_file=self.isolation,
                    min_memory_gib=0, min_state_gib=0,
                    min_scratch_gib=0)

        def worker(slot):
            try:
                run_worker(slot=slot, runner=first_runner, **args)
            except RuntimeError as failure:
                events.put(("interrupted", str(failure)))

        with patch("Mallory.native_graphchecker_queue.queue.physical_host"), patch(
                "Mallory.native_graphchecker_queue.queue.inspect_case", side_effect=inspect):
            workers = [context.Process(target=worker, args=(slot,))
                       for slot in (0, 1)]
            for process in workers:
                process.start()
            for process in workers:
                process.join(timeout=10)
            self.assertEqual([process.exitcode for process in workers], [0, 0])
            seen = [events.get(timeout=1) for _ in range(4)]
            starts = {event[1]: event for event in seen if event[0] == "start"}
            self.assertEqual(set(starts), {self.case_id, second_id})
            self.assertNotEqual(starts[self.case_id][2], starts[second_id][2])
            self.assertNotEqual(starts[self.case_id][3], starts[second_id][3])
            self.assertEqual(starts[self.case_id][4], "-Dhbase.test.port=20000")
            self.assertEqual(starts[second_id][4], "-Dhbase.test.port=20100")
            self.assertTrue((self.state_root / self.case_id /
                             "checkpoint.json").exists())
            self.assertTrue((self.state_root / second_id /
                             "checkpoint.json").exists())
            self.assertFalse((self.state_root / second_id /
                              "summary.json").exists())

            resumed = []

            def resume_runner(config_file, root):
                resumed.append(config_file.stem)
                (root / "checkpoint.json").write_text('{"terminal":true}\n')
                (root / "summary.json").write_text('{"terminal":true}\n')

            result = run_worker(slot=0, slots=2, runner=resume_runner, **{
                key: value for key, value in args.items() if key != "slots"})
        self.assertEqual(resumed, [second_id])
        self.assertEqual(result["cases"], [second_id])
        receipts = self.state_root / ".native-queue/completions"
        self.assertTrue((receipts / f"{self.case_id}.json").exists())
        self.assertTrue((receipts / f"{second_id}.json").exists())

    def test_two_resumptions_use_distinct_pinned_engine_processes(self) -> None:
        case_ids = ("HBASE-01", "HBASE-02")
        starts = self.root / "starts"
        starts.mkdir()
        script = self.root / "fake_native_campaign.py"
        script.write_text(
            "import json, os, pathlib, sys, time\n"
            "config = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
            "root = pathlib.Path(sys.argv[2])\n"
            "assert os.environ['MALLORY_NATIVE_ENGINE_ROOT'] == "
            "config['expected_engine_root']\n"
            "start = pathlib.Path(config['start_dir']) / config['case_id']\n"
            "start.write_text(os.environ['MALLORY_NATIVE_ENGINE_ROOT'] + "
            "'\\n' + os.environ['TMPDIR'])\n"
            "deadline = time.monotonic() + 8\n"
            "while len(list(start.parent.iterdir())) < 2:\n"
            "    assert time.monotonic() < deadline\n"
            "    time.sleep(.02)\n"
            "(root / 'checkpoint.json').write_text('{\"terminal\":true}\\n')\n"
            "(root / 'summary.json').write_text('{\"terminal\":true}\\n')\n"
            "print(json.dumps({'case_id': config['case_id'], 'status': 'complete'}))\n")
        policy = self.profile["systems"]["hbase"]
        policy["required_jvm_args"] = []
        policy["ports"] = {"mode": "assigned",
                           "evidence": policy["ports"]["evidence"],
                           "cases": {case_id: {
                               "start": 21000 + 100 * slot, "count": 100,
                               "required_jvm_args": [
                                   f"-Dhbase.test.port={21000 + 100 * slot}"]}
                               for slot, case_id in enumerate(case_ids)}}
        self.isolation.write_text(json.dumps(self.profile))
        for slot, case_id in enumerate(case_ids):
            engine = self.root / f"engine-{slot}"
            target = engine / "target"
            target.mkdir(parents=True)
            jar = target / "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
            jar.write_bytes(f"engine-{slot}".encode())
            output = self.root / f"woven-{slot}"
            output.mkdir()
            (output / "native-original-weave-receipt.json").write_text(
                json.dumps({"engine_jar": str(jar),
                            "engine_jar_sha256": sha(jar)}))
            weave = self.root / f"weave-{slot}.json"
            weave.write_text(json.dumps({"output_classes": str(output)}))
            (self.config_root / f"{case_id}.json").write_text(json.dumps({
                "case_id": case_id, "native_weave_config": str(weave),
                "expected_engine_root": str(engine), "start_dir": str(starts),
                "runner": {"jvm_args": [
                    "-Djava.io.tmpdir={trial_workdir}",
                    "-Dbuild.test.dir={trial_workdir}",
                    f"-Dhbase.test.port={21000 + 100 * slot}"]},
                "junit": {"class": "OriginalTest", "method": "testOriginal"}}))
            native_root = self.state_root / case_id
            native_root.mkdir()
            (native_root / "checkpoint.json").write_text('{"terminal":false}\n')

        def inspect(item, owner, config_root, state_root, review=None):
            done = (state_root / item["case_id"] / "summary.json").exists()
            return {"terminal_disposition": "tested_no_target_throw" if done
                    else "resumable", "native_tested_complete": done,
                    "fault_trials": 1 if done else 0,
                    "strict_fault_trials": 1 if done else 0,
                    "target_retained_fault_trials": 1 if done else 0,
                    "target_throw_trials": 0, "candidate_trials": 0,
                    "elapsed_seconds": 1.0 if done else 0}

        args = dict(host="node1", slots=2, inventory=DEFAULT_INVENTORY,
                    ownership_file=DEFAULT_OWNERSHIP,
                    config_root=self.config_root, state_root=self.state_root,
                    scratch_root=self.scratch_root,
                    isolation_file=self.isolation,
                    min_memory_gib=0, min_state_gib=0,
                    min_scratch_gib=0)
        context = multiprocessing.get_context("fork")

        def worker(slot, case_id):
            run_worker(slot=slot, only_case=case_id, **args)

        command = lambda config_file, root: [
            sys.executable, str(script), str(config_file), str(root)]
        with patch("Mallory.native_graphchecker_queue.queue.physical_host"), patch(
                "Mallory.native_graphchecker_queue.queue.inspect_case",
                side_effect=inspect), patch(
                "Mallory.native_graphchecker_queue.queue._pinned_campaign_command",
                side_effect=command):
            processes = [context.Process(target=worker, args=(slot, case_id))
                         for slot, case_id in enumerate(case_ids)]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=15)
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            for slot, case_id in enumerate(case_ids):
                observed = (starts / case_id).read_text().splitlines()
                self.assertEqual(observed[0], str(self.root / f"engine-{slot}"))
                self.assertEqual(observed[1], str(self.scratch_root / case_id))
                self.assertTrue((self.state_root / ".native-queue/completions" /
                                 f"{case_id}.json").exists())
                self.assertEqual(run_worker(slot=slot, only_case=case_id,
                                            **args)["completed"], 0)
            self.assertEqual(len(list(starts.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
