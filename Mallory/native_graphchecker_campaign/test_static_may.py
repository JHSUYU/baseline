"""Static MAY hints must never become observed causal closure."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_campaign import campaign as core
from Mallory.native_graphchecker_campaign.static_may import (
    observed_rpc_door_sites, rpc_producer_sites,
)


def _row(role: str, **fields: str) -> str:
    return json.dumps({"kind": "STATIC_SCOPE_SITE", "role": role, **fields})


class StaticMayTest(unittest.TestCase):
    def test_value_edges_keep_all_region_memberships_and_only_rpc_doors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.jsonl"
            path.write_text("\n".join((
                _row("TARGET_SITE", siteId="Target#u1", regionId="second"),
                _row("STATIC_REGION_METHOD", regionId="first", vmMethod="Target"),
                _row("STATIC_REGION_METHOD", regionId="second", vmMethod="Consumer"),
                _row("STATIC_VALUE_EDGE", producerMethod="Producer",
                     consumerMethod="Consumer"),
                _row("DOOR_SITE", siteId="RPC#u1", vmSite="Producer",
                     exceptionClass="x.ServiceException"),
                _row("DOOR_SITE", siteId="FILE#u1", vmSite="Producer",
                     exceptionClass="java.io.IOException"),
                _row("DOOR_SITE", siteId="RPC#unrelated", vmSite="Unrelated",
                     transport="RPC"))) + "\n")
            self.assertEqual(frozenset({"RPC#u1"}),
                             rpc_producer_sites(str(path), core._sha(path),
                                                "Target#u1"))
            with self.assertRaisesRegex(ValueError, "exact target"):
                rpc_producer_sites(str(path), core._sha(path), "Other#u1")

    def test_broad_rpc_catalog_is_only_a_peer_hint_without_value_edges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scope.jsonl"
            path.write_text("\n".join((
                _row("TARGET_SITE", siteId="Target#u1", regionId="target"),
                _row("STATIC_REGION_METHOD", regionId="target", vmMethod="Target"),
                _row("DOOR_SITE", siteId="RPC#u1", vmSite="Control",
                     exceptionClass="x.ServiceException"),
                _row("DOOR_SITE", siteId="FILE#u1", vmSite="Control",
                     exceptionClass="java.io.IOException"))) + "\n")
            digest = core._sha(path)
            self.assertEqual(frozenset(), rpc_producer_sites(
                str(path), digest, "Target#u1"))
            self.assertEqual(frozenset({"RPC#u1"}), observed_rpc_door_sites(
                str(path), digest, "Target#u1"))
            with self.assertRaisesRegex(ValueError, "exact target"):
                observed_rpc_door_sites(str(path), digest, "Other#u1")

    def test_static_producer_is_ranked_without_claiming_closure(self) -> None:
        target = "Target#u1"
        summary = {"targetSiteId": target,
                   "closureMembershipAuthority":
                       "original_runtime_selected_region_finalizer",
                   "closureOccurrenceIds": ["target"],
                   "targetEvidence": {"targetCheckOccurrenceIds": ["target"],
                                      "physicalActor": "dn", "actorEpochOrdinal": 0}}

        def door(site: str, seq: int) -> dict:
            return {"kind": "FAULT_DOOR", "siteId": site, "seq": seq,
                    "node": "nn", "actorEpochOrdinal": 0,
                    "occurrenceId": f"door-{seq}", "ordinal": seq,
                    "exceptionClass": "x.ServiceException"}

        check = {"kind": "TARGET_CHECK", "siteId": target, "seq": 4,
                 "node": "dn", "actorEpochOrdinal": 0,
                 "occurrenceId": "target"}
        rows = [door("RPC#producer", 1), door("RPC#other", 2), check,
                door("RPC#producer", 5)]
        ranked = core._region_doors(
            rows, summary, static_may_rpc_sites=frozenset({"RPC#producer"}))
        self.assertEqual(["static_producer_frontier", "outside_closure",
                          "outside_closure"], [item["tier"] for item in ranked])
        self.assertEqual(["before_selected_target", "before_selected_target",
                          "after_selected_target"],
                         [item["target_phase"] for item in ranked])
        self.assertFalse(any(item["tier"] == "observed_closure" for item in ranked))

        state = {"queue": [], "seen_plan_keys": [],
                 "budget": {"max_faults_per_trial": 3},
                 "completed_fault_trials": 0, "scheduler_version": 6}
        first = ranked[0]["fault"]
        # A strict first injection followed by a target-retaining run may
        # discover another observed door. Mutation extends only that prefix.
        later = core._region_doors(rows, summary, rows[0],
                                   frozenset({"RPC#producer"}))
        core._enqueue(state, later, [first], 0)
        self.assertTrue(any(len(item["faults"]) == 2 for item in state["queue"]))
        self.assertFalse(any(item["tier"] == "observed_closure"
                             for item in state["queue"]))


if __name__ == "__main__":
    unittest.main()
