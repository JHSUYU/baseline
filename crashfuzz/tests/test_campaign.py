import json
from pathlib import Path
import socket
import tempfile
import unittest

from adhoc_crashfuzz.backend import CommandResult
from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import TargetSpec
from adhoc_crashfuzz.mutation import NodeGroup


class FakeCluster:
    containers = {"n1": "fixture-1", "n2": "fixture-2"}

    def __init__(self, baseline_fatal=False, target_only_after_crash=False):
        self.dead = set()
        self.baseline_fatal = baseline_fatal
        self.target_only_after_crash = target_only_after_crash
        self.run_dir = None
        self.port = 0

    def prepare(self, run_dir, _host, port):
        self.dead.clear()
        self.run_dir = run_dir
        self.port = port
        return CommandResult(0, "", "")

    def kill_node(self, node):
        self.dead.add(node)

    def start_node(self, node):
        self.dead.remove(node)

    def run_workload(self, _run_dir):
        base = {"schema": 1, "node": "n1", "process": "p1",
                "thread": "1", "span": "1", "context": "root/request#1"}
        point = dict(base, kind="FAULT_POINT", seq=2, site="io.write",
                     ordinal=1, phase="BEFORE")
        with socket.create_connection(("127.0.0.1", self.port), 5) as sock:
            sock.sendall((json.dumps(point) + "\n").encode())
            self.assert_continue(sock)
        rows = [dict(base, kind="METHOD_ENTER", seq=1, site="request"),
                point]
        if not self.target_only_after_crash or "n1" in self.dead:
            rows.append(dict(base, kind="TARGET", seq=3, site="check",
                             fatal=self.baseline_fatal or "n1" in self.dead))
        trace_dir = self.run_dir / "traces"
        trace_dir.mkdir()
        with (trace_dir / "trace-n1-p1.jsonl").open("w") as out:
            for row in rows:
                out.write(json.dumps(row) + "\n")
        return CommandResult(0, "", "")

    @staticmethod
    def assert_continue(sock):
        answer = sock.recv(4096).decode()
        if answer != "CONTINUE\n":
            raise AssertionError(answer)

    def check(self, _run_dir):
        return CommandResult(0, "", "")


class CampaignTests(unittest.TestCase):
    def test_matched_trial_limit_stops_retry_campaign(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(
                target=TargetSpec("check"), output_dir=Path(temp),
                backend=FakeCluster(),
                groups=(NodeGroup(frozenset({"n1", "n2"}), 1),),
                roles={}, controller_bind="127.0.0.1",
                controller_advertise="127.0.0.1", max_runs=4,
                matched_trial_limit=1, replay_count=0)
            answer = Campaign(settings).run()
            self.assertEqual(2, answer["tested"])

    def test_baseline_fatal_is_not_a_fault_finding(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(
                target=TargetSpec("check"), output_dir=Path(temp),
                backend=FakeCluster(baseline_fatal=True),
                groups=(NodeGroup(frozenset({"n1", "n2"}), 1),),
                roles={}, controller_bind="127.0.0.1",
                controller_advertise="127.0.0.1", max_runs=2)
            with self.assertRaisesRegex(RuntimeError, "fault-free seed already"):
                Campaign(settings).run()
            self.assertEqual(1, len(list((Path(temp) / "runs").iterdir())))

    def test_seed_mutation_target_oracle_and_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeCluster()
            settings = Settings(
                target=TargetSpec("check"), output_dir=Path(temp),
                backend=backend,
                groups=(NodeGroup(frozenset({"n1", "n2"}), 1),),
                roles={}, controller_bind="127.0.0.1",
                controller_advertise="127.0.0.1", max_runs=2,
                max_faults=2, replay_count=1)
            answer = Campaign(settings).run()
            self.assertEqual(2, answer["tested"])
            self.assertEqual(1, answer["findings"])
            finding = json.loads((Path(temp) / "findings.jsonl").read_text())
            self.assertTrue(finding["confirmation"]["reproduced"])

    def test_fault_can_expose_target_missing_from_healthy_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(
                target=TargetSpec("check"), output_dir=Path(temp),
                backend=FakeCluster(target_only_after_crash=True),
                groups=(NodeGroup(frozenset({"n1", "n2"}), 1),),
                roles={}, controller_bind="127.0.0.1",
                controller_advertise="127.0.0.1", max_runs=2,
                replay_count=1, allow_unreached_seed=True)
            answer = Campaign(settings).run()
            self.assertFalse(answer["seed_target_reached"])
            self.assertEqual(1, answer["findings"])


if __name__ == "__main__":
    unittest.main()
