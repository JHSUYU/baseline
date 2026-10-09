import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
import subprocess
import sys
import shutil

try:
    from . import scheduler
except ImportError:
    import scheduler


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.json"
        self.hosts = self.root / "hosts.json"
        self.hosts.write_text(json.dumps({"hosts": [
            {"name": "node0", "kind": "local", "slots": 2}
        ]}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_promotion_can_pin_verified_core_release(self):
        from Mallory.dispatch import core_release
        from Mallory.dispatch.promote import _calibration_causal_audit

        repo = Path(__file__).resolve().parents[2]
        manifest_path = core_release.build(repo, self.root / "releases")
        manifest = core_release.verify(manifest_path)
        cal = self.root / "calibration"
        cal.mkdir()
        result_path = cal / "result.json"
        result_path.write_text("{}\n", encoding="utf-8")
        names = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")
        expected = {name: manifest["files"][f"Mallory/core/{name}"] for name in names}
        audit = {
            "schema_version": 1, "audit_kind": "offline_causal_quality",
            "case_id": "HDFS-08", "terminal_status": "calibration_complete",
            "campaign_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "core_source_sha256": expected, "trial_count": 1,
            "archive_integrity_valid": True, "guidance_consistent": True,
            "report_gate_passed": True,
        }
        audit_path = cal / "offline-causal-audit.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        receipt = _calibration_causal_audit(cal, {"case_id": "HDFS-08"}, manifest_path)
        self.assertEqual(manifest["release_id"], receipt["core_release_id"])
        self.assertEqual(expected, receipt["core_source_sha256"])
        audit["core_source_sha256"] = {**expected, "feedback.py": "0" * 64}
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fixed-core healthy causal audit"):
            _calibration_causal_audit(cal, {"case_id": "HDFS-08"}, manifest_path)
        audit["core_source_sha256"] = expected
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        (manifest_path.parent / "Mallory/core/feedback.py").write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "core release file hashes differ"):
            _calibration_causal_audit(cal, {"case_id": "HDFS-08"}, manifest_path)

    def run_scheduler(self, *extra):
        return scheduler.main([
            "--manifest", str(self.manifest), "--hosts-file", str(self.hosts),
            "--state-root", str(self.root / "state"),
            "--scratch-root", str(self.root / "scratch"),
            "--build-root", str(self.root / "build"),
            "--hold-file", str(self.root / "holds.json"),
            "--heartbeat-seconds", "0.05", "--lease-seconds", "2",
            "--remote-reserve-gib", "0.001", "--remote-case-gib", "0.001",
            *extra,
        ])

    def test_runs_two_cases_and_resume_skips_completed_attempts(self):
        self.manifest.write_text(json.dumps({
            "cases": [{"case_id": "HDFS-01"}, {"case_id": "SOLR-02"}],
            "default_command": ["python3", "-c",
                                "from pathlib import Path; import os; Path(os.environ['MALLORY_SCRATCH'], 'ran').write_text('ok')"],
        }), encoding="utf-8")
        self.assertEqual(0, self.run_scheduler())
        for case in ("HDFS-01", "SOLR-02"):
            case_dir = self.root / "state/cases" / case
            result = json.loads((case_dir / "result.json").read_text())
            self.assertEqual("command_succeeded", result["status"])
            self.assertEqual("node0", result["host"])
            self.assertEqual(1, len(list((case_dir / "attempts").iterdir())))
            self.assertTrue(next((self.root / "scratch" / case).iterdir()).joinpath("ran").exists())
        self.assertEqual(0, self.run_scheduler())
        for case in ("HDFS-01", "SOLR-02"):
            self.assertEqual(1, len(list((self.root / "state/cases" / case / "attempts").iterdir())))

    def test_recovers_worker_receipt_left_after_coordinator_crash(self):
        self.manifest.write_text(json.dumps({"cases": [{"case_id": "HBASE-03"}],
                                             "default_command": ["true"]}), encoding="utf-8")
        case_dir = self.root / "state/cases/HBASE-03"
        attempt = case_dir / "attempts/a1"
        attempt.mkdir(parents=True)
        receipt = {"case_id": "HBASE-03", "attempt_id": "a1", "host": "node0",
                   "status": "command_succeeded", "exit_code": 0}
        (attempt / "exit.json").write_text(json.dumps(receipt), encoding="utf-8")
        (case_dir / "lease.json").write_text(json.dumps({"attempt_id": "a1", "host": "node0",
                                                        "expires_at": 0, "coordinator_pid": 999999,
                                                        "coordinator_host": "node0"}), encoding="utf-8")
        self.assertEqual(0, self.run_scheduler())
        self.assertEqual(receipt, json.loads((case_dir / "result.json").read_text()))
        self.assertEqual(1, len(list((case_dir / "attempts").iterdir())))

    def test_live_worker_lock_keeps_case_pending_without_duplicate(self):
        case_dir = self.root / "state/cases/HBASE-04"
        case_dir.mkdir(parents=True)
        with (case_dir / "worker.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual("running", scheduler.classify_case(case_dir, False))

    def test_lane_lock_serializes_workers_from_separate_coordinators(self):
        from Mallory.dispatch.worker import atomic_json
        lane = self.root / "lanes/solr-lane2.lock"
        lane.parent.mkdir()
        marker = self.root / "active.marker"
        collisions = self.root / "collisions.marker"
        program = ("import pathlib,time; m=pathlib.Path(%r); c=pathlib.Path(%r); "
                   "c.write_text('collision') if m.exists() else None; "
                   "m.write_text('active'); time.sleep(.25); m.unlink()") % (str(marker), str(collisions))
        jobs = []
        for case_id in ("SOLR-01", "SOLR-02"):
            attempt = self.root / case_id
            attempt.mkdir()
            spec = attempt / "spec.json"
            atomic_json(spec, {"attempt_dir": str(attempt), "case_id": case_id,
                               "attempt_id": case_id, "host": "node2",
                               "worker_lock": str(attempt / "worker.lock"),
                               "lane_id": "solr-lane2", "lane_lock": str(lane),
                               "command": [sys.executable, "-c", program],
                               "cwd": str(self.root), "environment": {},
                               "timeout_seconds": 5})
            jobs.append(subprocess.Popen([sys.executable, "-m", "Mallory.dispatch.worker",
                                          str(spec)]))
        for job in jobs:
            self.assertEqual(0, job.wait(timeout=5))
        self.assertFalse(collisions.exists())
        for case_id in ("SOLR-01", "SOLR-02"):
            receipt = json.loads((self.root / case_id / "exit.json").read_text())
            self.assertEqual("solr-lane2", receipt["lane_id"])
            self.assertEqual("command_succeeded", receipt["status"])

    def test_solr_lane_configs_are_immutable_and_keep_adapter_inputs(self):
        from Mallory.dispatch.prepare_solr_lane import generate
        source = self.root / "adapter/SOLR-01"
        source.mkdir(parents=True)
        original = {"case_id": "SOLR-01", "system": "solr",
                    "cwd": "/tmp/solr-lane1",
                    "source_equivalent_root": "/tmp/solr-lane1",
                    "command": ["python3", "/tmp/run_pilot.py", "SOLR-01"]}
        (source / "config.json").write_text(json.dumps(original))
        output = self.root / "lane-configs"
        lane = Path("/tmp/solr-lane2")
        manifest = generate(source.parent, output, lane)
        self.assertEqual(manifest, generate(source.parent, output, lane))
        transformed = json.loads((output / "SOLR-01.json").read_text())
        self.assertEqual(str(lane), transformed["cwd"])
        self.assertEqual(["--source", str(lane)], transformed["command"][-2:])
        self.assertEqual(original, json.loads((source / "config.json").read_text()))
        original["command"].append("--timeout")
        (source / "config.json").write_text(json.dumps(original))
        with self.assertRaises(RuntimeError):
            generate(source.parent, output, lane)

    def test_selected_stage_cannot_escape_mallory_or_include_cache(self):
        from Mallory.dispatch.stage import selected_files
        repo = self.root / "repo"
        dispatch = repo / "Mallory/dispatch"
        cache = dispatch / "__pycache__"
        cache.mkdir(parents=True)
        (dispatch / "scheduler.py").write_text("source")
        (cache / "scheduler.pyc").write_bytes(b"cache")
        self.assertEqual([dispatch / "scheduler.py"],
                         selected_files(repo, [Path("Mallory/dispatch")]))
        with self.assertRaises(ValueError):
            selected_files(repo, [Path("../outside")])

    def test_claim_is_exclusive_across_coordinators(self):
        case_dir = self.root / "state/cases/HBASE-05"
        host = {"name": "node0", "kind": "local", "slots": 1}
        first = scheduler.claim(case_dir, host, 10, False)
        self.assertIsNotNone(first)
        self.assertIsNone(scheduler.claim(case_dir, host, 10, False))

    def test_remote_missing_key_is_unavailable(self):
        host = {"name": "node1", "kind": "ssh", "address": "nobody@node1", "slots": 1}
        available, reason = scheduler.probe_host(host, self.root / "missing-key", [self.root])
        self.assertFalse(available)
        self.assertIn("key missing", reason)

    def test_local_shard_admission_observes_disk_reserve(self):
        host = {"name": "node1", "kind": "local", "slots": 1}
        free = shutil.disk_usage(self.root).free
        available, reason = scheduler.probe_host(host, self.root / "unused", [self.root],
                                                 min_free_bytes=free + 1)
        self.assertFalse(available)
        self.assertIn("below", reason)

    def test_launcher_can_plan_separate_lane_without_staging(self):
        from Mallory.dispatch.launch import main as launch_main, scheduler_argv
        command = scheduler_argv("node1", "calibration", "v4",
                                 "Mallory/adapters/solr/cases/{case_id}/config-v4-lane2.json",
                                 "solr-lane2")
        self.assertEqual(["--lane-id", "solr-lane2"], command[-2:])
        self.assertEqual(0, launch_main(["--hosts", "node1", "--phase", "calibration",
                                         "--cohort", "v4", "--lane-id", "solr-lane2",
                                         "--skip-stage"]))

    def test_zero_exit_without_terminal_case_result_is_retried(self):
        marker = self.root / "scientific/HDFS-05/result.json"
        self.manifest.write_text(json.dumps({
            "cases": [{"case_id": "HDFS-05"}],
            "default_command": ["true"],
            "default_completion_file": str(marker),
        }), encoding="utf-8")
        self.assertEqual(0, self.run_scheduler())
        case_dir = self.root / "state/cases/HDFS-05"
        self.assertEqual("result_missing", json.loads((case_dir / "result.json").read_text())["status"])
        self.assertEqual(0, self.run_scheduler())
        self.assertEqual(2, len(list((case_dir / "attempts").iterdir())))

    def test_terminal_case_result_is_scientifically_recorded(self):
        marker = self.root / "scientific/SOLR-05/result.json"
        command = ["python3", "-c", "import json,pathlib,os; p=pathlib.Path(%r); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps({'case_id':'SOLR-05','status':'budget_exhausted','last_dispatch_attempt_id':os.environ['MALLORY_ATTEMPT_ID']}))" % str(marker)]
        self.manifest.write_text(json.dumps({
            "cases": [{"case_id": "SOLR-05"}], "default_command": command,
            "default_completion_file": str(marker),
        }), encoding="utf-8")
        self.assertEqual(0, self.run_scheduler())
        case_dir = self.root / "state/cases/SOLR-05"
        result = json.loads((case_dir / "result.json").read_text())
        self.assertEqual("command_succeeded", result["status"])
        self.assertTrue(result["scientific_completed"])
        self.assertEqual("budget_exhausted", result["scientific_result_status"])
        self.assertEqual(0, self.run_scheduler())
        self.assertEqual(1, len(list((case_dir / "attempts").iterdir())))

    def test_selection_checks_and_dry_run_have_no_state(self):
        self.manifest.write_text(json.dumps({"checks": [{"case_id": "ZOOKEEPER-01"}],
                                             "default_command": ["echo", "{case_id}"]}), encoding="utf-8")
        self.assertEqual(0, self.run_scheduler("--dry-run"))
        self.assertFalse((self.root / "state").exists())

    def test_original_102_shards_are_disjoint_and_immutable(self):
        from Mallory.dispatch.shard import generate
        selection = Path(__file__).resolve().parents[2] / "data/crashfuzz/selection102.json"
        out = self.root / "shards"
        first = generate(selection, out)
        self.assertEqual({"node0": 38, "node1": 30, "node2": 34}, first["counts"])
        self.assertEqual(102, len(first["owner"]))
        self.assertEqual("system_owner_v2", first["shard_algorithm"])
        self.assertEqual(first, generate(selection, out))
        changed = json.loads((out / "node1.json").read_text())
        changed["cases"].pop()
        (out / "node1.json").write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            generate(selection, out)

    def test_collector_admits_only_matching_terminal_attempt(self):
        from Mallory.dispatch.collect import REMOTE_SCAN
        root = self.root / "mallory"
        case_dir = root / "cases/HDFS-01"
        dispatch_dir = root / "dispatch/node1/campaign/cases/HDFS-01"
        attempt = "a-123"
        (dispatch_dir / f"attempts/{attempt}").mkdir(parents=True)
        case_dir.mkdir(parents=True)
        result_path = case_dir / "result.json"
        result_path.write_text(json.dumps({
            "case_id": "HDFS-01", "status": "budget_exhausted",
            "last_dispatch_attempt_id": attempt,
            "evidence_archive": {"sha256": "a" * 64}}), encoding="utf-8")
        (dispatch_dir / "result.json").write_text(json.dumps({
            "case_id": "HDFS-01", "status": "command_succeeded",
            "scientific_completed": True, "attempt_id": attempt}), encoding="utf-8")
        (dispatch_dir / f"attempts/{attempt}/exit.json").write_text(json.dumps({
            "case_id": "HDFS-01", "attempt_id": attempt, "host": "node1"}), encoding="utf-8")
        (dispatch_dir / f"attempts/{attempt}/spec.json").write_text(json.dumps({
            "case_id": "HDFS-01", "attempt_id": attempt, "host": "node1"}), encoding="utf-8")
        command = [sys.executable, "-c", REMOTE_SCAN, str(root), "node1", ""]
        missing_audit = json.loads(subprocess.run(command, input='["HDFS-01"]',
                                                  text=True, capture_output=True, check=True).stdout)
        self.assertEqual([], missing_audit)
        (case_dir / "offline-causal-audit.json").write_text(json.dumps({
            "campaign_result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "report_gate_passed": True}), encoding="utf-8")
        found = json.loads(subprocess.run(command, input='["HDFS-01"]',
                                          text=True, capture_output=True, check=True).stdout)
        self.assertEqual(1, len(found))
        self.assertEqual(attempt, found[0]["attempt_id"])
        self.assertIn(f"dispatch/node1/campaign/cases/HDFS-01/attempts/{attempt}/spec.json",
                      found[0]["files"])
        (case_dir / "result.json").write_text(json.dumps({
            "case_id": "HDFS-01", "status": "budget_exhausted",
            "last_dispatch_attempt_id": "different"}), encoding="utf-8")
        rejected = json.loads(subprocess.run(command, input='["HDFS-01"]',
                                             text=True, capture_output=True, check=True).stdout)
        self.assertEqual([], rejected)

    def test_versioned_collector_reads_only_v2_paths(self):
        from Mallory.dispatch.collect import REMOTE_SCAN
        root = self.root / "mallory"
        case = root / "calibration_v2/SOLR-01"
        dispatch = root / "dispatch/node2-v2/calibration/cases/SOLR-01"
        attempt = "v2-attempt"
        (dispatch / f"attempts/{attempt}").mkdir(parents=True)
        case.mkdir(parents=True)
        (case / "result.json").write_text(json.dumps({
            "case_id": "SOLR-01", "status": "calibration_complete",
            "last_dispatch_attempt_id": attempt}), encoding="utf-8")
        (dispatch / "result.json").write_text(json.dumps({
            "case_id": "SOLR-01", "status": "command_succeeded",
            "scientific_completed": True, "attempt_id": attempt}), encoding="utf-8")
        (dispatch / f"attempts/{attempt}/exit.json").write_text(json.dumps({
            "case_id": "SOLR-01", "attempt_id": attempt, "host": "node2"}), encoding="utf-8")
        (dispatch / f"attempts/{attempt}/spec.json").write_text(json.dumps({
            "case_id": "SOLR-01", "attempt_id": attempt, "host": "node2"}), encoding="utf-8")
        command = [sys.executable, "-c", REMOTE_SCAN, str(root), "node2", "v2"]
        found = json.loads(subprocess.run(command, input='["SOLR-01"]',
                                          text=True, capture_output=True, check=True).stdout)
        self.assertEqual(1, len(found))
        self.assertIn("calibration_v2/SOLR-01/result.json", found[0]["files"])

    def test_terminal_archive_is_lossless_and_reusable(self):
        from Mallory.dispatch.archive import ensure
        from Mallory.dispatch.verify_sources import sha256_file
        root = self.root / "mallory"
        case = root / "calibration/HDFS-02"
        trial = case / "trials/r0000"
        trial.mkdir(parents=True)
        (case / "result.json").write_text(json.dumps({
            "case_id": "HDFS-02", "status": "calibration_complete"}), encoding="utf-8")
        (case / "config.json").write_text("config", encoding="utf-8")
        (trial / "events.jsonl.gz").write_bytes(b"event evidence")
        first = ensure(root, "calibration", "HDFS-02", reserve_bytes=1)
        archive = root / first["archive_relative"]
        self.assertEqual(first["archive_sha256"], sha256_file(archive))
        with tarfile.open(archive, "r:gz") as packed:
            self.assertEqual({"result.json", "config.json", "trials/r0000/events.jsonl.gz"},
                             set(packed.getnames()))
        self.assertEqual(first, ensure(root, "calibration", "HDFS-02", reserve_bytes=1))

    def test_archive_serializes_builds_and_refuses_lost_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        from Mallory.dispatch.archive import ensure
        root = self.root / "mallory"
        case = root / "cases/HBASE-07"
        case.mkdir(parents=True)
        result = case / "result.json"
        result.write_text(json.dumps({
            "case_id": "HBASE-07", "status": "budget_exhausted"}), encoding="utf-8")
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(
                lambda _: ensure(root, "campaign", "HBASE-07", reserve_bytes=1),
                range(2)))
        self.assertEqual(receipts[0], receipts[1])
        (root / receipts[0]["archive_relative"]).unlink()
        summary = json.loads(result.read_text(encoding="utf-8"))
        summary["evidence_archive"] = {"sha256": receipts[0]["archive_sha256"]}
        result.write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "missing evidence"):
            ensure(root, "campaign", "HBASE-07", reserve_bytes=1)

    def test_attestation_failure_is_terminal_archivable(self):
        from Mallory.dispatch.archive import ensure
        root = self.root / "mallory"
        case = root / "calibration/SOLR-03"
        case.mkdir(parents=True)
        (case / "result.json").write_text(json.dumps({
            "case_id": "SOLR-03", "status": "healthy_attestation_failed"}), encoding="utf-8")
        response = ensure(root, "calibration", "SOLR-03", reserve_bytes=1)
        self.assertTrue((root / response["archive_relative"]).is_file())

    def test_v2_archive_preserves_v1(self):
        from Mallory.dispatch.archive import ensure
        root = self.root / "mallory"
        for directory, status in (("calibration", "healthy_seed_invalid"),
                                  ("calibration_v2", "calibration_complete")):
            case = root / directory / "SOLR-04"
            case.mkdir(parents=True)
            (case / "result.json").write_text(json.dumps({
                "case_id": "SOLR-04", "status": status}), encoding="utf-8")
        first = ensure(root, "calibration", "SOLR-04", reserve_bytes=1)
        second = ensure(root, "calibration", "SOLR-04", reserve_bytes=1, cohort="v2")
        self.assertNotEqual(first["archive_relative"], second["archive_relative"])
        self.assertTrue((root / first["archive_relative"]).is_file())
        self.assertTrue((root / second["archive_relative"]).is_file())

    def test_promoter_pins_healthy_catalog_without_fault_trial(self):
        from Mallory.dispatch.promote import promote
        from Mallory.dispatch.verify_sources import sha256_file
        source = self.root / "source"
        source.mkdir()
        (source / "target.java").write_text("target", encoding="utf-8")
        (source / "test.java").write_text("test", encoding="utf-8")
        row = {"case_id": "HDFS-09", "system": "hdfs",
               "provenance": {"source_root": str(source), "source_commit": "pinned"},
               "target": {"source_path": "target.java",
                          "source_sha256": sha256_file(source / "target.java")},
               "workload": {"test_source_path": "test.java", "candidates": [
                   {"source_path": "test.java", "source_sha256": sha256_file(source / "test.java")}]}}
        config = {"case_id": "HDFS-09", "system": "hdfs", "calibration_only": True,
                  "target": {"check_sites": ["C#m@10:branch:1"],
                             "throw_site": "C#m@11:throw:1"}}
        config_path = self.root / "HDFS-09.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        cal = self.root / "calibration/HDFS-09"
        trial = cal / "trials/r0000"
        trial.mkdir(parents=True)
        (cal / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (cal / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "status": "calibration_complete",
            "calibration_only": True, "healthy_seed_valid": True,
            "fault_trials_completed": 0, "healthy_eligible_doors": 1,
            "target_binding": {"nodes": ["nn0"]},
            "trials": [{"status": "observed"}]}), encoding="utf-8")
        (trial / "sites.jsonl").write_text("catalog", encoding="utf-8")
        stdout = b"Tests run: 1, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS\n"
        (trial / "stdout.log").write_bytes(stdout)
        (trial / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "trial_id": 0, "plan": [],
            "return_code": 0, "timed_out": False,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stdout_evidence": {"raw_path": "stdout.log", "raw_sha256":
                                hashlib.sha256(stdout).hexdigest(), "raw_bytes": len(stdout)},
            "site_catalog_sha256": sha256_file(trial / "sites.jsonl"),
            "site_catalog_validation": {"valid": True, "reason": "ok",
                "missing_check_sites": [], "missing_throw_site": None,
                "duplicate_target_sites": [],
                "observed_target_class_sha256": "a" * 64,
                "target_class_loader_ids": ["loader0"]},
            "feedback": {"status": "observed", "target_reached": True,
                "target_threw": False, "target_exception_candidate": False,
                "target_instances": [{"node": "nn0"}],
                "doors": [{"site": "door"}], "eligible_doors_before_target": 1}}),
            encoding="utf-8")
        from Mallory.core import audit as audit_module
        current_core = {name: sha256_file(Path(audit_module.__file__).parent / name)
                        for name in ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
        (cal / "offline-causal-audit.json").write_text(json.dumps({
            "schema_version": 1, "audit_kind": "offline_causal_quality",
            "case_id": "HDFS-09", "terminal_status": "calibration_complete",
            "campaign_result_sha256": sha256_file(cal / "result.json"),
            "core_source_sha256": current_core, "trial_count": 1,
            "archive_integrity_valid": True, "guidance_consistent": True,
            "report_gate_passed": True}), encoding="utf-8")
        promoted = promote(config_path, cal, self.root / "promoted.json", row,
                           {"roots": {str(source): {"digest": "pinned"}}})
        promoted_config = json.loads(promoted.read_text())
        self.assertEqual("a" * 64, promoted_config["expected_target_class_sha256"])
        self.assertTrue(promoted_config["auto_promote_if_healthy"])
        self.assertFalse(promoted_config["calibration_only"])
        self.assertEqual("runtime_attested", promoted_config["mapping"]["status"])
        self.assertEqual(1, promoted_config["calibration_attestation"]["healthy_junit"]["tests_run"])
        self.assertEqual(current_core, promoted_config["calibration_attestation"]
                         ["healthy_causal_audit"]["core_source_sha256"])

    def test_promotion_junit_gate_checks_hashes_and_actual_test_count(self):
        from Mallory.dispatch.promote import _test_attestation
        trial_dir = self.root / "trial"
        trial_dir.mkdir()

        def evidence(name, content):
            payload = content.encode()
            (trial_dir / name).write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            return {"raw_path": name, "raw_sha256": digest, "raw_bytes": len(payload)}, digest

        for system, stream, content, count in (
            ("hdfs", "stdout", "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS", 1),
            ("zookeeper", "stdout", "Tests run: 2, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS", 2),
            ("hbase", "stderr", "MALLORY_JUNIT found=1 succeeded=1 failed=0", 1),
            ("solr", "stdout", json.dumps({"case_id": "SOLR-01", "exit_code": 0,
                                                "junit": {"run": 2, "failures": 0, "ignored": 0}}), 2),
        ):
            receipt, digest = evidence(f"{system}.log", content)
            trial = {"return_code": 0, "timed_out": False,
                     f"{stream}_sha256": digest, f"{stream}_evidence": receipt}
            self.assertEqual(count, _test_attestation(system, trial_dir, trial, "SOLR-01")["tests_run"])
            (trial_dir / f"{system}.log").write_text(content + " changed")
            with self.assertRaisesRegex(ValueError, "evidence hash differs"):
                _test_attestation(system, trial_dir, trial, "SOLR-01")
        zero, digest = evidence("zero.log", "Tests run: 0, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS")
        with self.assertRaisesRegex(ValueError, "no passing selected JUnit test"):
            _test_attestation("hdfs", trial_dir, {"return_code": 0, "timed_out": False,
                              "stdout_sha256": digest, "stdout_evidence": zero}, "HDFS-11")

    def test_campaign_evidence_materialization_preserves_bound_summary(self):
        from Mallory.dispatch.archive import ensure
        from Mallory.dispatch.collect import materialize_campaign_evidence
        root = self.root / "mallory"
        case = root / "cases/HDFS-01"
        trial = case / "trials/r0000"
        trial.mkdir(parents=True)
        original = {"case_id": "HDFS-01", "status": "budget_exhausted"}
        (case / "result.json").write_text(json.dumps(original), encoding="utf-8")
        (case / "config.json").write_text("config", encoding="utf-8")
        (trial / "events.jsonl.gz").write_bytes(b"compressed")
        receipt = ensure(root, "campaign", "HDFS-01", reserve_bytes=1)
        shutil.rmtree(trial)
        (case / "config.json").unlink()
        original["evidence_archive"] = {"sha256": receipt["archive_sha256"]}
        (case / "result.json").write_text(json.dumps(original), encoding="utf-8")
        materialize_campaign_evidence(case, root / receipt["archive_relative"],
                                      root / receipt["manifest_relative"])
        self.assertEqual(b"compressed", (trial / "events.jsonl.gz").read_bytes())
        self.assertIn("evidence_archive", json.loads((case / "result.json").read_text()))

    def test_scratch_compaction_rehydrates_exact_archived_bytes(self):
        from Mallory.dispatch.archive import ensure
        from Mallory.dispatch.collect import materialize_campaign_evidence
        from Mallory.dispatch.compact import compact_case
        root = self.root / "mallory"
        case = root / "cases/HDFS-09"
        scratch = case / "trials/r0000/scratch/subdir/log.1"
        scratch.parent.mkdir(parents=True)
        payload = b"recoverable scratch" * 128
        scratch.write_bytes(payload)
        (case / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "status": "budget_exhausted"}))
        archived = ensure(root, "campaign", "HDFS-09", reserve_bytes=1)
        summary = json.loads((case / "result.json").read_text())
        summary["evidence_archive"] = {
            "path": archived["archive_relative"],
            "sha256": archived["archive_sha256"],
            "manifest_path": archived["manifest_relative"],
            "manifest_sha256": archived["manifest_sha256"]}
        (case / "result.json").write_text(json.dumps(summary))
        (case / "offline-causal-audit.json").write_text(json.dumps({
            "case_id": "HDFS-09", "campaign_result_sha256": hashlib.sha256(
                (case / "result.json").read_bytes()).hexdigest()}))
        compacted = compact_case(root, "HDFS-09", min_bytes=1)
        self.assertEqual(len(payload), compacted["reclaimed_bytes"])
        self.assertFalse(scratch.exists())
        self.assertEqual(archived["archive_sha256"], ensure(
            root, "campaign", "HDFS-09", reserve_bytes=1)["archive_sha256"])
        materialize_campaign_evidence(case, root / archived["archive_relative"],
                                      root / archived["manifest_relative"])
        self.assertEqual(payload, scratch.read_bytes())

    def test_core_release_is_immutable_and_worker_rechecks_files(self):
        from Mallory.dispatch.core_release import CORE_FILES, build, verify
        source_repo = self.root / "repo"
        core = source_repo / "Mallory/core"
        core.mkdir(parents=True)
        for name in CORE_FILES:
            (core / name).write_text("# " + name + "\n", encoding="utf-8")
        manifest = build(source_repo, self.root / "releases")
        first = verify(manifest)
        self.assertEqual(manifest, build(source_repo, self.root / "releases"))
        self.assertEqual(64, len(first["release_id"]))
        (manifest.parent / "Mallory/core/events.py").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "file hashes differ"):
            verify(manifest)

    def test_collected_attempt_provenance_binds_spec_and_release(self):
        from Mallory.dispatch.collect import attempt_provenance
        from Mallory.dispatch.core_release import CORE_FILES, build, verify
        source_repo = self.root / "repo"
        core = source_repo / "Mallory/core"
        core.mkdir(parents=True)
        for name in CORE_FILES:
            (core / name).write_text("# " + name + "\n", encoding="utf-8")
        manifest = build(source_repo, self.root / "releases")
        release_id = verify(manifest)["release_id"]
        spec_path = self.root / "spec.json"
        spec = {"case_id": "HDFS-07", "attempt_id": "a1", "host": "node0",
                "core_release_id": release_id,
                "core_release_manifest": str(manifest),
                "case_config_sha256": "config-hash"}
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        receipt = attempt_provenance(spec_path, "HDFS-07", "a1", "node0", release_id)
        self.assertEqual(hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                         receipt["spec_sha256"])
        self.assertEqual(release_id, receipt["core_release_id"])
        with self.assertRaisesRegex(RuntimeError, "worker specification differs"):
            attempt_provenance(spec_path, "HDFS-07", "a2", "node0", release_id)
        with self.assertRaisesRegex(RuntimeError, "core release differs"):
            attempt_provenance(spec_path, "HDFS-07", "a1", "node0", "wrong")

    def test_lane_handoff_requires_observed_path_doors_and_pinned_config(self):
        from Mallory.dispatch.lane_handoff import ready_cases
        inventory = self.root / "inventory.json"
        reference = self.root / "reference.json"
        audit = self.root / "audit.json"
        config = self.root / "promoted.json"
        manifest = self.root / "ready.json"
        calibration_result = self.root / "result.json"
        calibration_result.write_text(json.dumps({"case_id": "HDFS-09",
                                                  "status": "calibration_complete"}))
        calibration_sha = hashlib.sha256(calibration_result.read_bytes()).hexdigest()
        core_hashes = {f"Mallory/core/{name}": name for name in (
            "audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
        audit_hashes = {name: name for name in (
            "audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
        inventory.write_text(json.dumps({"cases": [{
            "case_id": "HDFS-09", "system": "hdfs"}]}))
        reference.write_text(json.dumps({"inventory_sha256": hashlib.sha256(
            inventory.read_bytes()).hexdigest()}))
        audit.write_text(json.dumps({"case_id": "HDFS-09", "report_gate_passed": True,
                                     "healthy_closure_proven": True,
                                     "healthy_observed_path_doors": 1,
                                     "campaign_result_sha256": calibration_sha,
                                     "core_source_sha256": audit_hashes}))
        config.write_text(json.dumps({
            "case_id": "HDFS-09", "system": "hdfs", "calibration_only": False,
            "mapping": {"status": "runtime_attested"},
            "budget": {"trials": 80, "seconds": 3600},
            "calibration_attestation": {"healthy_causal_audit": {
                "path": str(audit), "sha256": hashlib.sha256(audit.read_bytes()).hexdigest()}}}))
        manifest.write_text(json.dumps({
            "schema_version": 1, "host": "node0",
            "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
            "source_reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
            "cases": [{"case_id": "HDFS-09", "state": "ready", "core_release_id": "release",
                       "calibration_sha256": calibration_sha,
                       "promoted_config": str(config),
                       "promoted_sha256": hashlib.sha256(config.read_bytes()).hexdigest()}]}))
        self.assertEqual(["HDFS-09"], [row["case_id"] for row in ready_cases(
            manifest, inventory, reference, "release", "node0", [], set(),
            core_hashes)])
        audit.write_text(json.dumps({"case_id": "HDFS-09", "report_gate_passed": True,
                                     "healthy_closure_proven": True,
                                     "healthy_observed_path_doors": 0,
                                     "campaign_result_sha256": calibration_sha,
                                     "core_source_sha256": audit_hashes}))
        config_data = json.loads(config.read_text())
        config_data["calibration_attestation"]["healthy_causal_audit"]["sha256"] = (
            hashlib.sha256(audit.read_bytes()).hexdigest())
        config.write_text(json.dumps(config_data))
        manifest_data = json.loads(manifest.read_text())
        manifest_data["cases"][0]["promoted_sha256"] = hashlib.sha256(
            config.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(manifest_data))
        with self.assertRaisesRegex(ValueError, "not promotable"):
            ready_cases(manifest, inventory, reference, "release", "node0", [], set(),
                        core_hashes)

    def test_campaign_queue_requires_matching_terminal_attempt(self):
        from Mallory.dispatch.campaign_queue import terminal_seed
        calibration = self.root / "calibration/HDFS-09"
        dispatch = self.root / "dispatch/HDFS-09"
        attempt = "attempt-1"
        calibration.mkdir(parents=True)
        (dispatch / "attempts" / attempt).mkdir(parents=True)
        (dispatch / "attempts" / attempt / "exit.json").write_text("{}")
        (calibration / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "status": "calibration_complete",
            "last_dispatch_attempt_id": attempt}))
        (dispatch / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "scientific_completed": True,
            "scientific_result_status": "calibration_complete",
            "status": "command_succeeded", "attempt_id": attempt}))
        _, state = terminal_seed(calibration, dispatch, "HDFS-09")
        self.assertEqual("eligible_for_promotion", state)
        (dispatch / "result.json").write_text(json.dumps({
            "case_id": "HDFS-09", "scientific_completed": True,
            "scientific_result_status": "calibration_complete",
            "status": "command_succeeded", "attempt_id": "different"}))
        _, state = terminal_seed(calibration, dispatch, "HDFS-09")
        self.assertEqual("dispatch_receipt_mismatch", state)

    def test_local_finalizer_requires_terminal_scientific_receipt(self):
        from Mallory.dispatch.finalize_local import terminal_receipt
        case = self.root / "cases/HDFS-07"
        dispatch = self.root / "dispatch/campaign/cases/HDFS-07"
        attempt = "a1"
        case.mkdir(parents=True)
        (dispatch / "attempts" / attempt).mkdir(parents=True)
        (dispatch / "attempts" / attempt / "exit.json").write_text("{}")
        (case / "result.json").write_text(json.dumps({
            "case_id": "HDFS-07", "status": "budget_exhausted",
            "last_dispatch_attempt_id": attempt}))
        (dispatch / "result.json").write_text(json.dumps({
            "case_id": "HDFS-07", "attempt_id": attempt,
            "scientific_completed": True, "scientific_result_status": "budget_exhausted",
            "status": "command_succeeded"}))
        self.assertIsNotNone(terminal_receipt(case, dispatch, "HDFS-07"))
        (dispatch / "result.json").write_text(json.dumps({
            "case_id": "HDFS-07", "attempt_id": attempt,
            "scientific_completed": False, "scientific_result_status": "budget_exhausted",
            "status": "command_succeeded"}))
        self.assertIsNone(terminal_receipt(case, dispatch, "HDFS-07"))

    def test_runtime_adapter_jar_requires_matching_artifact_pin(self):
        adapter = self.root / "adapter.jar"
        adapter.write_bytes(b"adapter")
        config = {"agent_properties": {"adapter.jar": str(adapter)}}
        with self.assertRaisesRegex(ValueError, "adapter jar must be pinned"):
            scheduler.verify_runtime_artifacts(config)
        config["runtime_artifacts"] = [{
            "path": str(adapter),
            "sha256": hashlib.sha256(adapter.read_bytes()).hexdigest()}]
        scheduler.verify_runtime_artifacts(config)
        adapter.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            scheduler.verify_runtime_artifacts(config)


if __name__ == "__main__":
    unittest.main()
