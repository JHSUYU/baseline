#!/usr/bin/env python3
"""Negative tamper tests for the role-specific offline verifier (no JUnit)."""

from __future__ import annotations

import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path

import verify

EXPORT: Path


class RoleTamperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = verify.read_json(EXPORT / "config.json")
        cls.healthy = verify.read_json(EXPORT / "trials/r0000/result.json")
        cls.healthy_events = verify.load_events(EXPORT / "trials/r0000", cls.healthy)
        cls.result1 = verify.read_json(EXPORT / "trials/r0001/result.json")
        cls.events1 = verify.load_events(EXPORT / "trials/r0001", cls.result1)
        cls.result2 = verify.read_json(EXPORT / "trials/r0002/result.json")
        cls.events2 = verify.load_events(EXPORT / "trials/r0002", cls.result2)

    def test_real_receipts(self) -> None:
        row = verify.verify_fault(self.events1, self.result1["plan"][0])
        self.assertEqual((row["door_id"], row["matched_id"], row["applied_id"]),
                         ("SOLR-10-r0001:3389", "SOLR-10-r0001:3391",
                          "SOLR-10-r0001:3397"))
        self.assertIsNotNone(verify.verify_path(
            self.events2, self.result2, self.config["target"],
            [verify.verify_fault(self.events2, self.result2["plan"][0])]))

    def mutate_fault_event(self, kind: str, field: str, value: object) -> None:
        events = copy.deepcopy(self.events1)
        event = next(e for e in events if e["type"] == kind
                     and e.get("fault_id") == self.result1["plan"][0]["fault_id"])
        event[field] = value
        with self.assertRaises(ValueError):
            verify.verify_fault(events, self.result1["plan"][0])

    def test_role_ordinal_tamper(self) -> None:
        self.mutate_fault_event("FAULT_APPLIED", "role_ordinal", 18)

    def test_physical_node_tamper(self) -> None:
        self.mutate_fault_event("FAULT_MATCHED", "node", "node9")

    def test_occurrence_tamper(self) -> None:
        self.mutate_fault_event("FAULT_APPLIED", "occurrence", "node3:0:other")

    def test_thread_tamper(self) -> None:
        self.mutate_fault_event("FAULT_APPLIED", "thread_id", 999)

    def test_leader_token_tamper(self) -> None:
        self.mutate_fault_event("FAULT_APPLIED", "role_leader_id", "different-leader")

    def test_missing_observed_door(self) -> None:
        events = tuple(e for e in self.events1 if e.get("id") != "SOLR-10-r0001:3389")
        with self.assertRaisesRegex(ValueError, "role door count"):
            verify.verify_fault(events, self.result1["plan"][0])

    def test_reordered_match(self) -> None:
        events = copy.deepcopy(self.events1)
        next(e for e in events if e.get("id") == "SOLR-10-r0001:3391")["seq"] = 3398
        with self.assertRaisesRegex(ValueError, "event order"):
            verify.verify_fault(events, self.result1["plan"][0])

    def test_leader_decision_tamper(self) -> None:
        events = copy.deepcopy(self.events1)
        next(e for e in events if e.get("id") == "SOLR-10-r0001:3379")["decision"] = "NO"
        with self.assertRaisesRegex(ValueError, "leader decision"):
            verify.verify_fault(events, self.result1["plan"][0])

    def test_guidance_source_tamper(self) -> None:
        fault = copy.deepcopy(self.result1["plan"][0])
        source = fault["role_source"]
        door = next(e for e in self.healthy_events if e.get("id") == source["event_id"])
        fault["role_source"]["leader_id"] = "different-leader"
        with self.assertRaisesRegex(ValueError, "guidance source"):
            verify.verify_guidance(fault, 1, {door["id"]: door},
                                   {0: self.healthy["feedback"]})

    def test_unobserved_path_tamper(self) -> None:
        result = copy.deepcopy(self.result2)
        result["feedback"]["postfault_event_path"]["edges"][0]["consumer_event"] = "bogus"
        with self.assertRaisesRegex(ValueError, "path receipt"):
            verify.verify_path(self.events2, result, self.config["target"],
                               [verify.verify_fault(self.events2, result["plan"][0])])

    def test_target_actor_tamper(self) -> None:
        events = copy.deepcopy(self.events2)
        check_id = self.result2["feedback"]["postfault_event_path"]["target_check_event_id"]
        next(e for e in events if e.get("id") == check_id)["node"] = "node9"
        with self.assertRaises(ValueError):
            verify.verify_path(events, self.result2, self.config["target"],
                               [verify.verify_fault(events, self.result2["plan"][0])])

    def test_manifest_pin_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = json.loads((EXPORT / "evidence-manifest.json").read_text())
            manifest["host"] = "node0"
            (root / "evidence-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "manifest SHA mismatch"):
                verify.verify_manifest(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    args, unittest_args = parser.parse_known_args()
    EXPORT = args.export.resolve(strict=True)
    unittest.main(argv=[__file__, *unittest_args])
