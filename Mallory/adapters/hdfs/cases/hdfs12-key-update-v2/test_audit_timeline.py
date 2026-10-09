#!/usr/bin/env python3
"""Pure Python checks for HDFS-12 selector and timeline rejection rules."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("audit_timeline", HERE / "audit_timeline.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def row(number, kind, phase=None, **fields):
    result = {"id": f"run:{number}", "seq": number, "ts": number * 100,
              "type": kind, "node": "hdfs-cluster-1/dn0", "epoch": 0,
              "thread_id": 7, "context": "req-dn", "occurrence": "occ"}
    if phase:
        result["phase"] = phase
    result.update(fields)
    return result


class NoGraphPath:
    def __init__(self, *_args, **_kwargs):
        pass

    def event_path(self, *_args, **_kwargs):
        return None


class CapturingGraph:
    def __init__(self):
        self.edges = []

    def _add(self, write, read, kind, evidence):
        self.edges.append((write["id"], read["id"], kind, evidence))


class TimelineTest(unittest.TestCase):
    def test_indexed_junit_selector_rejects_zero_and_wrong_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xml"
            path.write_text('<testsuite tests="0"/>')
            with self.assertRaisesRegex(ValueError, "executed 0"):
                audit.junit_method(path, True)
            path.write_text('<testsuite><testcase classname="org.apache.hadoop.hdfs.TestEncryptedTransfer" name="testLongLivedClient[1]"/></testsuite>')
            with self.assertRaisesRegex(ValueError, "unexpected JUnit"):
                audit.junit_method(path, True)
            path.write_text('<testsuite><testcase classname="org.apache.hadoop.hdfs.TestEncryptedTransfer" name="testLongLivedClient[0]"/></testsuite>')
            self.assertEqual(audit.junit_method(path, True)["name"], audit.TEST_NAME)
            suffix = "mallory_0000_2c6dd471a09f4d12bffe172ba96c3cf1"
            path.write_text('<testsuite><testcase classname="org.apache.hadoop.hdfs.TestEncryptedTransfer('
                            + suffix + ')" name="testLongLivedClient[0]"/></testsuite>')
            self.assertEqual(audit.junit_method(path, True)["name"], audit.TEST_NAME)
            path.write_text('<testsuite><testcase classname="org.apache.hadoop.hdfs.TestEncryptedTransfer('
                            + suffix + ')Extra" name="testLongLivedClient[0]"/></testsuite>')
            with self.assertRaisesRegex(ValueError, "unexpected JUnit"):
                audit.junit_method(path, True)

    def test_repeated_identical_mint_is_one_identity_class(self):
        lookup = row(20, "HDFS12_KEY", "dn_lookup", bpid="BP-1",
                     owner_bpid="BP-1", key_id=42, token_id="a" * 64,
                     expiry_ms=2000, wall_time_ms=1000, request="req-dn")
        mint = row(10, "HDFS12_KEY", "nn_token_mint", node="hdfs-cluster-1/nn0",
                   bpid="BP-1", owner_bpid="BP-1", key_id=42,
                   token_id="a" * 64, expiry_ms=2000, request="req-nn")
        duplicate = {**mint, "id": "run:11", "seq": 11, "ts": 1100}
        self.assertEqual(audit.minted([mint, duplicate], lookup)["id"], "run:11")
        conflict = {**duplicate, "id": "run:12", "request": "another-request"}
        self.assertIsNone(audit.minted([mint, conflict], lookup))

    def test_exact_state_edge_requires_same_value_and_no_intervening_write(self):
        fields = {"node": "hdfs-cluster-1/dn0", "epoch": 0, "bpid": "BP-1",
                  "manager_id": 3, "key_id": 42, "version": 2, "value_id": 9,
                  "state_token": "manager:3:key:42:version:2", "matched": True}
        write = row(10, "HDFS12_KEY_STATE", "write", **fields)
        read = row(20, "HDFS12_KEY_STATE", "read", **fields)
        graph = CapturingGraph()
        self.assertEqual(audit.exact_key_read_from(graph, [write, read])[0]["read_id"],
                         "run:20")
        self.assertEqual(len(graph.edges), 1)
        different = {**read, "value_id": 10}
        self.assertEqual(audit.exact_key_read_from(CapturingGraph(), [write, different]), [])
        intervening = row(15, "HDFS12_KEY_STATE", "write_gap", **fields)
        self.assertEqual(audit.exact_key_read_from(CapturingGraph(),
                         [write, intervening, read]), [])

    def test_exact_response_task_and_key_path_has_no_root_join(self):
        nn = "hdfs-cluster-1/nn0"
        dn = "hdfs-cluster-1/dn0"
        token = "rpc-1"
        task = "task-1"
        def event(seq, kind, node, thread, occurrence, **fields):
            base = {"id": f"run:{seq}", "seq": seq, "ts": seq * 100,
                    "type": kind, "node": node, "epoch": 0,
                    "thread_id": thread, "occurrence": occurrence,
                    "context": fields.pop("context", token),
                    "site": fields.pop("site", "test:site"),
                    "region": fields.pop("region", None)}
            return {**base, **fields}
        state = {"phase": "write", "bpid": "BP-1", "manager_id": 2,
                 "key_id": 42, "version": 3, "value_id": 7,
                 "state_token": "manager:2:key:42:version:3", "matched": True}
        rows = [
            event(1, "HDFS12_KEY", nn, 1, "nn-rpc", phase="nn_command_key"),
            event(2, "SEND", nn, 1, "nn-rpc", correlation=token,
                  transport="hadoop-ipc", port="response"),
            event(3, "RECV", dn, 2, "unscoped:" + dn + ":0:rpc-1:thread:2:segment:1",
                  correlation=token, transport="hadoop-ipc", port="response"),
            event(4, "REGION_ENTER", dn, 2, "dn-enqueue", region="enqueue",
                  parent_id=token),
            event(5, "TASK_SUBMIT", dn, 2, "dn-enqueue", region="enqueue",
                  correlation=task),
            event(6, "REGION_EXIT", dn, 2, "dn-enqueue", region="enqueue"),
            event(7, "TASK_CLAIM", dn, 3,
                  "unscoped:" + dn + ":0:task-1:thread:3:segment:1",
                  context=task, correlation=task),
            event(8, "REGION_ENTER", dn, 3, "dn-run", context=task,
                  region="run", parent_id=task),
            event(9, "HDFS12_KEY", dn, 3, "dn-run", region="run",
                  phase="dn_add_keys"),
            event(10, "HDFS12_KEY_STATE", dn, 3, "dn-run", region="run", **state),
            event(11, "REGION_EXIT", dn, 3, "dn-run", region="run"),
            event(12, "HDFS12_KEY_STATE", dn, 4, "dn-target",
                  **{**state, "phase": "read"}),
            event(13, "TARGET_CHECK", dn, 4, "dn-target", site=audit.CHECK,
                  outcome="TAKEN"),
        ]
        graph = audit.OccurrenceGraph(rows, reject_coarse_roots=True)
        self.assertEqual(len(audit.exact_key_read_from(graph, rows)), 1)
        path = graph.event_path(rows[0], rows[-1], require_edge=True)
        self.assertEqual([edge.kind for edge in path],
                         ["rpc", "region_parent", "task", "region_parent",
                          "key_read_from"])
        broken = [dict(x) for x in rows]
        broken[2]["node"] = "unknown"
        graph = audit.OccurrenceGraph(broken, reject_coarse_roots=True)
        audit.exact_key_read_from(graph, broken)
        self.assertIsNone(graph.event_path(broken[0], broken[-1], require_edge=True))

    def pilot_rows(self):
        nn = {"node": "hdfs-cluster-1/nn0", "thread_id": 8, "context": "req-nn"}
        key = {"bpid": "BP-1", "owner_bpid": "BP-1", "key_id": 42}
        dn_key = {"bpid": "BP-1", "owner_bpid": "BP-1", "key_id": 42,
                  "token_id": "a" * 64, "expiry_ms": 2000, "wall_time_ms": 1000,
                  "request": "req-dn"}
        heartbeat = {"bpid": "BP-1", "owner_bpid": "BP-1", "key_id": -1,
                     "peer": "DN-1", "actor_ref": "actor@123", "request": "req-dn"}
        return [
            row(1, "HDFS12_KEY", "dn_bind", peer="DN-1"),
            row(10, "HDFS12_KEY", "nn_rotation_next", **nn, **key),
            row(11, "HDFS12_KEY", "nn_pending_true", **nn, **key, peer="DN-1"),
            row(12, "HDFS12_KEY", "dn_heartbeat_attempt", **heartbeat),
            row(13, "DOOR_OBSERVED", site=audit.DOOR, hit=1, door_ordinal=1),
            row(14, "FAULT_APPLIED", site=audit.DOOR, hit=1, door_ordinal=1),
            row(15, "HDFS12_KEY", "nn_rotation_current", **nn, **key),
            row(16, "HDFS12_KEY", "nn_token_mint", **nn, **key,
                token_id="a" * 64, expiry_ms=2000, request="req-nn"),
            row(17, "HDFS12_KEY", "dn_heartbeat_attempt", **heartbeat),
            row(18, "DOOR_OBSERVED", site=audit.DOOR, hit=2, door_ordinal=2),
            row(19, "HDFS12_KEY", "dn_lookup", **dn_key),
            row(20, "TARGET_CHECK", site=audit.CHECK, outcome="FALLTHROUGH"),
            row(21, "TARGET_THROW", site=audit.THROW),
        ]

    def receipt(self):
        return {"status": "healthy_admitted",
                "config_sha256": audit.sha(HERE / "HDFS-12-healthy-only.json")}

    def test_r1_h1_r2_h2_is_timing_only_without_graph_path(self):
        with patch.object(audit, "OccurrenceGraph", NoGraphPath):
            result = audit.pilot(self.pilot_rows(), self.receipt())
        self.assertEqual(result["status"], "timing_only")
        self.assertEqual([result[key] for key in ("r1_id", "h1_id", "r2_id", "h2_id")],
                         ["run:10", "run:12", "run:15", "run:17"])

    def test_prior_add_keys_closes_window(self):
        rows = self.pilot_rows()
        added = row(18.5, "HDFS12_KEY", "dn_add_keys",
                    bpid="BP-1", owner_bpid="BP-1", key_id=42)
        added["ts"] = 1850
        rows.insert(-2, added)
        with patch.object(audit, "OccurrenceGraph", NoGraphPath):
            with self.assertRaisesRegex(ValueError, "no exact"):
                audit.pilot(rows, self.receipt())

    def test_token_or_actor_mismatch_rejected(self):
        rows = self.pilot_rows()
        rows[-3]["token_id"] = "b" * 64
        with patch.object(audit, "OccurrenceGraph", NoGraphPath):
            with self.assertRaisesRegex(ValueError, "no exact"):
                audit.pilot(rows, self.receipt())
        rows = self.pilot_rows()
        rows[8]["actor_ref"] = "actor@different"
        with patch.object(audit, "OccurrenceGraph", NoGraphPath):
            with self.assertRaisesRegex(ValueError, "no exact"):
                audit.pilot(rows, self.receipt())


if __name__ == "__main__":
    unittest.main()
