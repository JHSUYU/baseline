#!/usr/bin/env python3
"""Two-worker dry run for the node0 checklist coordinator."""

from __future__ import annotations

import concurrent.futures
import getpass
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import coordinator
import evidence_sync_remote


SCRIPT = Path(coordinator.__file__).resolve()


def cli(*arguments: str, expect_ok: bool = True) -> dict:
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)],
                            text=True, capture_output=True, check=False)
    if expect_ok and result.returncode != 0:
        raise AssertionError(result.stderr)
    if not expect_ok and result.returncode == 0:
        raise AssertionError("expected coordinator rejection")
    return json.loads(result.stdout if expect_ok else result.stderr)


class CoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="coordinator-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "node0-ledger"
        manifest = self.base / "checklist.json"
        manifest.write_text(json.dumps({"rows": [
            {"case_id": "HDFS-01", "system": "HDFS 3.4.3", "status": "test_identified"},
            {"case_id": "HBASE-02", "system": "HBase 2.6.6", "status": "mapped_pending_smoke"},
            {"case_id": "SOLR-03", "system": "Solr 8.11.4", "status": "no_cluster_test"},
        ]}), encoding="utf-8")
        initialized = cli("init", "--root", self.root, "--manifest", manifest)
        self.assertEqual(initialized["cases"], 3)

    def claim(self, worker: str, case_id: str | None = None) -> dict:
        options = ["claim", "--root", str(self.root), "--worker", worker]
        if case_id:
            options.extend(["--case-id", case_id])
        return cli(*options)

    def synced_result(self, claim: dict, status: str) -> Path:
        directory = (self.root / "cases" / claim["case_id"] / "artifacts" /
                     f"attempt-{claim['attempt']:03d}")
        directory.mkdir(parents=True)
        result = directory / "result.json"
        result.write_text(json.dumps({"case_id": claim["case_id"],
                                      "status": status,
                                      "fault_trials": 2,
                                      "elapsed_seconds": 8.25}),
                          encoding="utf-8")
        return result

    def test_two_workers_claim_distinct_cases_and_finish(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.claim, worker) for worker in ("node1", "node2")]
            claimed = [future.result() for future in futures]
        self.assertEqual({item["case_id"] for item in claimed},
                         {"HDFS-01", "HBASE-02"})
        self.assertTrue(all(item["claimed"] for item in claimed))
        self.assertFalse(self.claim("node0")["claimed"])

        for item in claimed:
            beat = cli("heartbeat", "--root", self.root,
                       "--case-id", item["case_id"],
                       "--token", item["lease_token"])
            self.assertEqual(beat["attempt"], 1)
            result = self.synced_result(item, "quality_complete")
            completed = cli("complete", "--root", self.root,
                            "--case-id", item["case_id"],
                            "--token", item["lease_token"],
                            "--status", "quality_complete",
                            "--result-file", result)
            self.assertEqual(completed["status"], "quality_complete")
            self.assertEqual(json.loads((self.root / "cases" / item["case_id"] /
                                         "result.json").read_text())["fault_trials"], 2)
        self.assertFalse(self.claim("node1")["claimed"])
        report = cli("status", "--root", self.root)
        self.assertEqual(report["counts"], {"quality_complete": 2,
                                            "no_cluster_test": 1})

    def test_expired_lease_is_taken_over_and_old_token_rejected(self) -> None:
        original = self.claim("node1", "HDFS-01")
        case = self.root / "cases" / "HDFS-01"
        lease_path = case / "lease.d" / "owner.json"
        lease = coordinator.read_json(lease_path)
        lease["expires_at"] = 0
        coordinator.atomic_json(lease_path, lease)
        successor = self.claim("node2", "HDFS-01")
        self.assertEqual(successor["attempt"], 2)
        self.assertNotEqual(original["lease_token"], successor["lease_token"])
        self.assertEqual(len(list(case.glob("lease.stale.*.d"))), 1)
        denied = cli("heartbeat", "--root", self.root,
                     "--case-id", "HDFS-01", "--token", original["lease_token"],
                     expect_ok=False)
        self.assertIn("lease token", denied["error"])
        result = self.synced_result(successor, "candidate_review")
        cli("complete", "--root", self.root, "--case-id", "HDFS-01",
            "--token", successor["lease_token"], "--status", "candidate_review",
            "--result-file", result)
        self.assertFalse(self.claim("node1", "HDFS-01")["claimed"])

    def test_graph_gap_waits_for_explicit_resume(self) -> None:
        first = self.claim("node1", "HDFS-01")
        result = self.synced_result(first, "graph_gap")
        done = cli("complete", "--root", self.root, "--case-id", "HDFS-01",
                   "--token", first["lease_token"], "--status", "graph_gap",
                   "--result-file", result)
        self.assertEqual(done["status"], "graph_gap")
        self.assertEqual(done["last_outcome"], "graph_gap")
        self.assertFalse(self.claim("node2", "HDFS-01")["claimed"])
        resumed = cli("resume", "--root", self.root, "--case-id", "HDFS-01",
                      "--reason", "GraphChecker closure patch v2")
        self.assertEqual(resumed["status"], "pending")
        second = self.claim("node2", "HDFS-01")
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(json.loads((self.root / "cases" / "HDFS-01" /
                                     "result.json").read_text())["status"], "graph_gap")
        budget_result = self.synced_result(second, "budget_or_queue_complete")
        cli("complete", "--root", self.root, "--case-id", "HDFS-01",
            "--token", second["lease_token"],
            "--status", "budget_or_queue_complete", "--result-file", budget_result)
        self.assertFalse(self.claim("node1", "HDFS-01")["claimed"])

    def test_complete_requires_synced_matching_result(self) -> None:
        claim = self.claim("node1", "HDFS-01")
        outside = self.base / "outside.json"
        outside.write_text(json.dumps({"case_id": "HDFS-01",
                                       "status": "quality_complete"}), encoding="utf-8")
        error = cli("complete", "--root", self.root, "--case-id", "HDFS-01",
                    "--token", claim["lease_token"], "--status", "quality_complete",
                    "--result-file", outside, expect_ok=False)
        self.assertIn("node0 case directory", error["error"])
        missing = cli("complete", "--root", self.root, "--case-id", "HDFS-01",
                      "--token", claim["lease_token"], "--status", "quality_complete",
                      expect_ok=False)
        self.assertIn("rsync artifacts", missing["error"])

    def test_bounded_evidence_stages_results_and_remote_trace_hash(self) -> None:
        case = self.base / "worker-case"
        trace = case / "trials" / "0001" / "attempt-01" / "trace" / "runtime_trace.jsonl"
        trace.parent.mkdir(parents=True)
        trace.write_bytes(b'{"event":"METHOD_ENTER"}\n' * 40000)
        (case / "result.json").write_text('{"case_id":"HDFS-01","status":"fuzzing"}')
        (case / "state.json").write_text('{"active":null}')
        selector = case / "trials" / "0001" / "fault-trial.json"
        selector.write_text('{"faults":[]}')
        log = case / "trials" / "0001" / "attempt-01" / "stdout.log"
        log.write_bytes(b"begin\n" + b"x" * 2000 + b"end\n")
        (case / ".coord").mkdir()
        stage_dir = case / ".coord" / "evidence-001-test"
        report = evidence_sync_remote.stage(case, stage_dir, "summary",
                                            1024 * 1024, 100)
        self.assertLessEqual(report["transferred_bytes"], 1024 * 1024)
        self.assertTrue((stage_dir / "result.json").is_file())
        self.assertTrue((stage_dir / "state.json").is_file())
        self.assertTrue((stage_dir / "trials/0001/fault-trial.json").is_file())
        self.assertEqual((stage_dir / "trials/0001/attempt-01/stdout.log")
                         .read_bytes(), log.read_bytes()[-100:])
        self.assertFalse((stage_dir / "trials/0001/attempt-01/trace/runtime_trace.jsonl")
                         .exists())
        manifest = coordinator.read_json(stage_dir / "evidence-manifest.json")
        trace_entry = next(row for row in manifest["omitted"]
                           if row.get("relative_path", "").endswith("runtime_trace.jsonl"))
        self.assertEqual(trace_entry["source_sha256"],
                         evidence_sync_remote.hash_file(trace))
        self.assertEqual(manifest["source_case_dir"], str(case.resolve()))
        compressed = case / ".coord" / "evidence-002-test"
        evidence_sync_remote.stage(case, compressed, "trace", 2 * 1024 * 1024, 100)
        self.assertTrue((compressed /
                         "trials/0001/attempt-01/trace/runtime_trace.jsonl.gz").is_file())

    @unittest.skipUnless(os.environ.get("RUN_REMOTE_COORDINATOR_TEST") == "1",
                         "set RUN_REMOTE_COORDINATOR_TEST=1 for node1/node2 SSH dry run")
    def test_node0_pushes_to_two_remote_workers_and_pulls_results(self) -> None:
        remote_root = f"/tmp/coordinator-smoke-{uuid.uuid4().hex}"
        command_file = self.base / "remote-command.json"
        script = (
            "import json,sys,time; from pathlib import Path; time.sleep(3); "
            "p=Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True); "
            "(p/'result.json').write_text(json.dumps("
            "{'case_id':sys.argv[2],'status':'quality_complete'}))"
        )
        command_file.write_text(json.dumps(["python3", "-c", script,
                                            "{remote_case_dir}", "{case_id}"]),
                                encoding="utf-8")
        identity = Path.home() / ".ssh/id_ed25519_nodes"

        def run(host: str, case_id: str) -> dict:
            result = subprocess.run([
                sys.executable, str(SCRIPT), "dispatch", "--root", str(self.root),
                "--host", host, "--remote-root", remote_root,
                "--command-json", str(command_file),
                "--identity-file", str(identity), "--case-id", case_id,
                "--ttl-seconds", "2",
            ], capture_output=True, text=True, check=False)
            if result.returncode:
                raise AssertionError(result.stderr)
            return json.loads(result.stdout.splitlines()[-1])

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(run, "node1", "HDFS-01")
                second = pool.submit(run, "node2", "HBASE-02")
                reports = [first.result(), second.result()]
            self.assertTrue(all(report["processed"] == 1 for report in reports))
            for report in reports:
                case = report["cases"][0]
                self.assertEqual(case["outcome"], "quality_complete")
                self.assertIsNone(case["error"])
                self.assertGreaterEqual(case["heartbeats"], 1)
                published = self.root / "cases" / case["case_id"] / "result.json"
                self.assertEqual(json.loads(published.read_text())["case_id"],
                                 case["case_id"])
        finally:
            for host in ("node1", "node2"):
                subprocess.run([*coordinator.ssh_base(identity), f"{getpass.getuser()}@{host}",
                                shlex.join(["rm", "-rf", "--", remote_root])],
                               check=False, capture_output=True, text=True)

    @unittest.skipUnless(os.environ.get("RUN_REMOTE_COORDINATOR_TEST") == "1",
                         "set RUN_REMOTE_COORDINATOR_TEST=1 for tmux recovery test")
    def test_resume_attaches_existing_tmux_job_after_node0_dispatcher_dies(self) -> None:
        remote_root = f"/tmp/coordinator-resume-{uuid.uuid4().hex}"
        command_file = self.base / "remote-command.json"
        script = (
            "import json,sys,time; from pathlib import Path; "
            "p=Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True); "
            "f=p/'runs.log'; f.open('a').write('run\\n'); time.sleep(6); "
            "(p/'result.json').write_text(json.dumps("
            "{'case_id':sys.argv[2],'status':'quality_complete'}))"
        )
        command_file.write_text(json.dumps(["python3", "-c", script,
                                            "{remote_case_dir}", "{case_id}"]),
                                encoding="utf-8")
        identity = Path.home() / ".ssh/id_ed25519_nodes"
        base_command = [sys.executable, str(SCRIPT), "dispatch", "--root",
                        str(self.root), "--remote-root", remote_root,
                        "--command-json", str(command_file),
                        "--identity-file", str(identity),
                        "--case-id", "HDFS-01", "--ttl-seconds", "2"]
        process = subprocess.Popen([*base_command, "--host", "node1"],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            case_dir = self.root / "cases" / "HDFS-01"
            job = None
            deadline = time.time() + 5
            while time.time() < deadline:
                job = coordinator.read_json(case_dir / "coord.json").get("remote_job")
                if job:
                    state, _ = coordinator.remote_job_state(
                        coordinator.ssh_base(identity), f"{getpass.getuser()}@node1", job)
                    if state == "running":
                        break
                time.sleep(0.1)
            else:
                raise AssertionError("remote tmux session never started")
            process.kill()
            process.communicate(timeout=3)
            lease = coordinator.read_json(case_dir / "lease.d" / "owner.json")
            time.sleep(max(0, lease["expires_at"] - time.time()) + 0.2)
            resumed = subprocess.run([*base_command, "--host", "node2"],
                                     capture_output=True, text=True, check=False)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            report = json.loads(resumed.stdout.splitlines()[-1])["cases"][0]
            self.assertEqual(report["host"], "node1")
            self.assertTrue(report["reused_remote_job"])
            self.assertEqual(report["outcome"], "quality_complete")
            run_log = case_dir / "artifacts" / "attempt-002" / "runs.log"
            self.assertEqual(run_log.read_text(), "run\n")
            self.assertFalse(self.claim("node2", "HDFS-01")["claimed"])
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)
            for host in ("node1", "node2"):
                subprocess.run([*coordinator.ssh_base(identity), f"{getpass.getuser()}@{host}",
                                shlex.join(["rm", "-rf", "--", remote_root])],
                               check=False, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
