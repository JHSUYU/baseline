"""Offline tests against the SHA-pinned HDFS-18 v4 trace."""

from __future__ import annotations

import copy
import gzip
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from healthy_gate import (DOOR, DN, atomic_json, digest, exact_chain, promote,
                          verify_pair, verify_promotion)

HERE = Path(__file__).resolve().parent


def materialize(root: Path) -> tuple[dict, list[dict]]:
    with tarfile.open(HERE / "prior-healthy.tar.gz", "r:gz") as archive:
        for relative in ("result.json", "trials/r0000/result.json",
                         "trials/r0000/events.jsonl.gz"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(relative).read())
    trial = json.loads((root / "trials/r0000/result.json").read_text())
    events = [json.loads(line) for line in gzip.decompress(
        (root / "trials/r0000/events.jsonl.gz").read_bytes()).splitlines()]
    return trial, events


def seed_checkpoint(root: Path) -> tuple[dict, dict]:
    materialize(root)
    config = json.loads((HERE / "HDFS-18-node2-full-v5a.json").read_text())
    atomic_json(root / "config.json", config)
    verdict = verify_pair(root)
    state = {"config_digest": digest(config), "status": "calibration_complete",
             "calibration_only": True, "completed_trials": [0],
             "running": None, "next_trial": 1,
             "queue": [{"faults": [{"point": verdict["point"],
                                     "fault_type": "EXCEPTION",
                                     "exception_class": "java.io.IOException"}],
                        "selection_reason": "dynamic_closure"}]}
    atomic_json(root / "checkpoint.json", state)
    return verdict, state


class HealthyGateTest(unittest.TestCase):
    def test_pinned_trace_has_exact_named_rpc_region_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial, events = materialize(root)
            verdict = verify_pair(root)
            self.assertEqual(verdict["door_seq"], 133)
            self.assertEqual(verdict["send_seq"], 134)
            self.assertEqual(verdict["recv_seq"], 135)
            self.assertEqual(verdict["region_seq"], 137)
            self.assertEqual(verdict["target_seq"], 138)
            self.assertEqual(exact_chain(trial, events)["point"]["node"], DN)

    def test_unknown_actor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial, events = materialize(Path(directory))
            altered = copy.deepcopy(events)
            for event in altered:
                if event.get("type") == "DOOR_OBSERVED" and event.get("site") == DOOR:
                    event["node"] = "unknown"
            with self.assertRaisesRegex(ValueError, "no exact named typed"):
                exact_chain(trial, altered)

    def test_unmatched_rpc_token_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial, events = materialize(Path(directory))
            altered = copy.deepcopy(events)
            for event in altered:
                if event.get("seq") == 135:
                    event["correlation"] = "different-request"
            with self.assertRaisesRegex(ValueError, "no exact named typed"):
                exact_chain(trial, altered)

    def test_promotion_rejects_generic_queue_and_preserves_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materialize(root)
            config = json.loads((HERE / "HDFS-18-node2-full-v5a.json").read_text())
            (root / "config.json").write_text(json.dumps(config))
            verdict = verify_pair(root)
            state = {"config_digest": digest(config), "status": "calibration_complete",
                     "calibration_only": True, "completed_trials": [0],
                     "running": None, "next_trial": 1,
                     "queue": [{"faults": [{"point": verdict["point"],
                                             "fault_type": "EXCEPTION",
                                             "exception_class": "java.io.IOException"}],
                                "selection_reason": "dynamic_closure"}]}
            (root / "checkpoint.json").write_text(json.dumps(state))
            admitted = promote(root)
            self.assertEqual(admitted["queue_entries"], 1)
            self.assertEqual(verify_promotion(root)["status"], "admitted")
            self.assertEqual(admitted["trial_sha256"], verdict["trial_sha256"])
            root2 = Path(directory) / "bad"
            root2.mkdir()
            materialize(root2)
            (root2 / "config.json").write_text(json.dumps(config))
            bad = copy.deepcopy(state)
            bad["queue"][0]["faults"][0]["point"]["site"] = "generic-rpc"
            (root2 / "checkpoint.json").write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, "unverified fault point"):
                promote(root2)

    def test_interrupted_promotion_reuses_gate_and_completes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verdict, state = seed_checkpoint(root)
            verdict["queue_entries"] = 1
            # Simulate interruption after the first durable write in promote.
            atomic_json(root / "healthy-gate.json", verdict)
            gate_bytes = (root / "healthy-gate.json").read_bytes()
            trial_bytes = (root / "trials/r0000/result.json").read_bytes()
            self.assertTrue(state["calibration_only"])
            self.assertEqual(promote(root), verdict)
            self.assertEqual((root / "healthy-gate.json").read_bytes(), gate_bytes)
            self.assertEqual((root / "trials/r0000/result.json").read_bytes(), trial_bytes)
            self.assertFalse(json.loads((root / "checkpoint.json").read_text())[
                "calibration_only"])
            self.assertEqual(promote(root), verdict)
            self.assertEqual(verify_promotion(root), verdict)

    def test_interrupted_promotion_rejects_changed_gate_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verdict, _ = seed_checkpoint(root)
            verdict["queue_entries"] = 1
            verdict["rpc_token"] = "unrelated-request"
            atomic_json(root / "healthy-gate.json", verdict)
            checkpoint_bytes = (root / "checkpoint.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "existing healthy gate differs"):
                promote(root)
            self.assertEqual((root / "checkpoint.json").read_bytes(), checkpoint_bytes)


if __name__ == "__main__":
    unittest.main()
