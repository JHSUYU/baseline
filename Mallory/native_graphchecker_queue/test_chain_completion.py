"""Fail-closed tests for a chained native checklist receipt."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from .chain_completion import inspect_chain, sha256


SITE = "<Sample: void target()>#u1"
THROW = {"siteId": "<Sample: void target()>#u2",
         "exceptionClass": "java.io.IOException"}
DOOR = "<Sample: void rpc()>#u3"


def write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return path


def pin(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": sha256(path)}


class ChainedCompletionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = "ZOOKEEPER-TEST"

    def segment(self, name: str, *, previous: dict | None = None,
                fault_ordinal: int = 1, exact_throw: bool = False) -> dict:
        root = self.root / name
        config_path = root / "config.json"
        checkpoint_path = root / "checkpoint.json"
        summary_path = root / "summary.json"
        fault = {"siteId": DOOR, "node": "zk-peer-1",
                 "actorEpochOrdinal": 0, "ordinal": fault_ordinal,
                 "exceptionClass": "java.io.IOException",
                 "sourceOccurrenceId": "occ-rpc"}
        config = {"case_id": self.case,
                  "junit": {"class": "SampleTest", "method": "testCluster"},
                  "runner": {"mode": "region_state"},
                  "target_site": SITE, "target_throw": THROW,
                  "budget": {"fault_trials": 1, "seconds": 60,
                             "max_faults_per_trial": 4}}
        if previous is not None:
            config["predecessor_campaign"] = {
                key: previous[key]["path"] for key in ("config", "checkpoint", "summary")}
            config["predecessor_campaign"].update({
                key + "_sha256": previous[key]["sha256"]
                for key in ("config", "checkpoint", "summary")})
        write(config_path, config)
        for index in (0, 1):
            trial = root / "trials" / f"r{index:04d}"
            trial.mkdir(parents=True, exist_ok=True)
            write(trial / "original-graph/summary.json", {"targetReached": True})
        write(root / "trials/r0000/result.json", {
            "case_id": self.case, "status": "healthy_seed", "junit_passed": True,
            "native_target_retained": True, "target_exception_triggered": False,
            "faults": [], "elapsed_seconds": 2.0})
        events = [
            {"kind": "FAULT_DOOR", "seq": 1, "siteId": DOOR,
             "node": "zk-peer-1", "actorEpochOrdinal": 0,
             "occurrenceId": "occ-rpc", "ordinal": fault_ordinal,
             "exceptionClass": "java.io.IOException"},
            {"kind": "FAULT_APPLIED", "seq": 2, "siteId": DOOR,
             "node": "zk-peer-1", "actorEpochOrdinal": 0,
             "occurrenceId": "occ-rpc", "ordinal": fault_ordinal,
             "exceptionClass": "java.io.IOException"},
            {"kind": "TARGET_CHECK", "seq": 3, "siteId": SITE,
             "node": "zk-peer-1", "actorEpochOrdinal": 0,
             "occurrenceId": "occ-target", "ordinal": 1}]
        if exact_throw:
            events.append({"kind": "TARGET_THROW", "seq": 4,
                           "siteId": THROW["siteId"],
                           "exceptionClass": THROW["exceptionClass"],
                           "node": "zk-peer-1", "actorEpochOrdinal": 0,
                           "occurrenceId": "occ-target", "ordinal": 1})
        events_path = root / "trials/r0001/iteration-native/fault-events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("".join(json.dumps(row) + "\n" for row in events))
        write(root / "trials/r0001/result.json", {
            "case_id": self.case, "status": "needs_causal_review" if exact_throw else "checked",
            "faults": [fault], "strict_injection": True,
            "native_target_retained": True, "fault_in_target_closure": True,
            "junit_passed": True, "target_exception_triggered": exact_throw,
            "target_throw_rows": events[-1:] if exact_throw else [],
            "target_temporal_admitted": False,
            "target_temporal_reason": ("cross_occurrence_order_unproved"
                                       if exact_throw else "no_exact_target_throw"),
            "target_temporal_evidence": None,
            "fault_events_sha256": sha256(events_path), "elapsed_seconds": 10.0})
        state = {"case_id": self.case, "status": "complete_trial_budget",
                 "terminal": True, "active": None, "config_sha256": sha256(config_path),
                 "completed_fault_trials": 1, "elapsed_seconds": 12.0,
                 "trials": [{"name": "r0001", "result": "trials/r0001/result.json",
                             "elapsed_seconds": 10.0, "strict_injection": True,
                             "native_target_retained": True,
                             "target_exception_triggered": exact_throw}]}
        if previous is not None:
            state["predecessor_import"] = {"source": previous["checkpoint"]["sha256"]}
        write(checkpoint_path, state)
        write(summary_path, state)
        audit = write(root / "full-audit.json", {
            "method": "exact_frozen_python_full_native_inspect_case",
            "source_tar_sha256": "source", "engine_jar_sha256": "engine",
            "trial_evidence_sha256": {"trial": "hash"},
            "fingerprint": {"native_root": str(root),
                            "config_sha256": sha256(config_path),
                            "checkpoint_sha256": sha256(checkpoint_path),
                            "summary_sha256": sha256(summary_path)},
            "row": {"case_id": self.case, "native_tested_complete": True,
                    "fault_trials": 1, "strict_fault_trials": 1,
                    "strict_target_retained_fault_trials": 1,
                    "strict_in_target_closure_trials": 1,
                    "target_throw_trials": int(exact_throw),
                    "elapsed_seconds": 12.0}})
        return {"config": pin(config_path), "checkpoint": pin(checkpoint_path),
                "summary": pin(summary_path), "frozen_audit": pin(audit)}

    def manifest(self, segments: list[dict], *, fault_budget: int = 1) -> Path:
        budget = {"fault_trials": fault_budget, "seconds": 7200,
                  "max_faults_per_trial": 4}
        authority = write(self.root / "reviewed-budget.json", {
            "case_id": self.case, "budget": budget})
        return write(self.root / "chain.json", {
            "schema_version": 1, "case_id": self.case,
            "budget": budget, "formal_budget_authority": pin(authority),
            "segments": segments})

    def test_complete_requires_budget_and_full_graph_audit(self) -> None:
        segment = self.segment("one")
        receipt = inspect_chain(self.manifest([segment]))
        self.assertTrue(receipt["native_tested_complete"])
        self.assertEqual(receipt["strict_fault_trials"], 1)
        self.assertEqual(receipt["exact_target_throw_trials"], 0)
        del segment["frozen_audit"]
        self.assertFalse(inspect_chain(self.manifest([segment]))[
            "native_tested_complete"])
        missing_policy = self.manifest([self.segment("other")])
        value = json.loads(missing_policy.read_text())
        del value["formal_budget_authority"]
        write(missing_policy, value)
        self.assertFalse(inspect_chain(missing_policy)["native_tested_complete"])
        self.assertFalse(inspect_chain(self.manifest([segment], fault_budget=2))[
            "native_tested_complete"])

    def test_exact_throw_requires_matching_original_events(self) -> None:
        segment = self.segment("one", exact_throw=True)
        receipt = inspect_chain(self.manifest([segment]))
        self.assertEqual(receipt["exact_target_throw_trials"], 1)
        result = Path(segment["checkpoint"]["path"]).parent / "trials/r0001/result.json"
        value = json.loads(result.read_text())
        value["target_throw_rows"] = []
        write(result, value)
        with self.assertRaisesRegex(ValueError, "exact target exception oracle"):
            inspect_chain(self.root / "chain.json")

    def test_successor_replay_and_predecessor_pin_rejected(self) -> None:
        first = self.segment("first")
        second = self.segment("second", previous=first)
        with self.assertRaisesRegex(ValueError, "replayed a prior"):
            inspect_chain(self.manifest([first, second], fault_budget=2))
        second = self.segment("second", previous=first, fault_ordinal=2)
        self.assertTrue(inspect_chain(self.manifest([first, second],
                                                    fault_budget=2))[
            "native_tested_complete"])
        config = Path(second["config"]["path"])
        value = json.loads(config.read_text())
        value["predecessor_campaign"]["checkpoint_sha256"] = "wrong"
        write(config, value)
        second["config"] = pin(config)
        checkpoint = Path(second["checkpoint"]["path"])
        state = json.loads(checkpoint.read_text())
        state["config_sha256"] = second["config"]["sha256"]
        write(checkpoint, state)
        second["checkpoint"] = pin(checkpoint)
        with self.assertRaisesRegex(ValueError, "predecessor pin"):
            inspect_chain(self.manifest([first, second], fault_budget=2))

    def test_tampered_event_stream_rejected(self) -> None:
        segment = self.segment("one")
        manifest = self.manifest([segment])
        events = Path(segment["checkpoint"]["path"]).parent / (
            "trials/r0001/iteration-native/fault-events.jsonl")
        events.write_text(events.read_text().replace("FAULT_APPLIED", "FAULT_DOOR"))
        with self.assertRaisesRegex(ValueError, "durable fault events changed"):
            inspect_chain(manifest)

    def test_same_segment_duplicate_plan_rejected(self) -> None:
        segment = self.segment("one")
        root = Path(segment["checkpoint"]["path"]).parent
        shutil.copytree(root / "trials/r0001", root / "trials/r0002")
        checkpoint = json.loads((root / "checkpoint.json").read_text())
        second = dict(checkpoint["trials"][0])
        second.update(name="r0002", result="trials/r0002/result.json")
        checkpoint["trials"].append(second)
        checkpoint["completed_fault_trials"] = 2
        checkpoint["elapsed_seconds"] = 22.0
        write(root / "checkpoint.json", checkpoint)
        write(root / "summary.json", checkpoint)
        segment["checkpoint"] = pin(root / "checkpoint.json")
        segment["summary"] = pin(root / "summary.json")
        with self.assertRaisesRegex(ValueError, "segment replayed an exact fault plan"):
            inspect_chain(self.manifest([segment], fault_budget=2))


if __name__ == "__main__":
    unittest.main()
