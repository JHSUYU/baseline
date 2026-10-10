#!/usr/bin/env python3
"""Offline validity tests for return bridges and shared-reference evidence."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"))
from Mallory.core.events import Trace, event_address, event_seq  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402
from call_return import add_balanced_returns  # noqa: E402
import gate_v2  # noqa: E402


def row(kind: str, seq: int, thread: int, occurrence: str, region: str,
        **other: object) -> dict:
    return {"id": f"e{seq}", "type": kind, "seq": seq, "node": "n1", "epoch": 0,
            "thread_id": thread, "occurrence": occurrence, "region": region, **other}


def fixture(*, confidence: str = "exact", wrong_exit_thread: bool = False) -> tuple[dict, ...]:
    return (
        row("REGION_ENTER", 1, 1, "watch", "Watcher", parent_id="root"),
        row("DOOR_OBSERVED", 2, 1, "watch", "Watcher", site="getData", fault_type="EXCEPTION"),
        row("REGION_ENTER", 3, 1, "write", "SetIfNewer", parent_id="watch"),
        row("STATE_WRITE", 4, 1, "write", "SetIfNewer", object="o1", key="alias",
            version="value7", version_confidence=confidence),
        row("REGION_EXIT", 5, 2 if wrong_exit_thread else 1, "write", "SetIfNewer"),
        row("REGION_EXIT", 6, 1, "watch", "Watcher"),
        row("REGION_ENTER", 7, 3, "request", "Target", parent_id="root"),
        row("REGION_ENTER", 8, 3, "read", "GetAliases", parent_id="request"),
        row("STATE_READ", 9, 3, "read", "GetAliases", object="o1", key="alias",
            version="value7", version_confidence=confidence),
        row("REGION_EXIT", 10, 3, "read", "GetAliases"),
        row("TARGET_CHECK", 11, 3, "request", "Target", site="check"),
        row("REGION_EXIT", 12, 3, "request", "Target"),
    )


class ReturnBridgeTests(unittest.TestCase):
    def path(self, events: tuple[dict, ...], include_candidates: bool):
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        add_balanced_returns(graph, events, event_address, event_seq)
        return graph.event_path(events[1], events[10],
                                include_candidates=include_candidates, require_edge=True)

    def test_exact_reference_value_has_observed_path(self) -> None:
        path = self.path(fixture(), include_candidates=False)
        self.assertIsNotNone(path)
        self.assertEqual([edge.kind for edge in path], ["program_order", "state", "return"])
        self.assertTrue(all(edge.certainty == "observed" for edge in path))

    def test_sampled_state_stays_candidate(self) -> None:
        events = fixture(confidence="sampled")
        self.assertIsNone(self.path(events, include_candidates=False))
        path = self.path(events, include_candidates=True)
        self.assertIsNotNone(path)
        self.assertEqual([edge.certainty for edge in path], ["observed", "candidate", "observed"])

    def test_unbalanced_return_does_not_bridge(self) -> None:
        self.assertIsNone(self.path(fixture(wrong_exit_thread=True), include_candidates=True))

    def test_case_gate_requires_actual_reference_identity(self) -> None:
        def evaluate(confidence: str) -> dict:
            events = list(fixture(confidence=confidence))
            events[1]["site"] = gate_v2.DOOR
            events[1]["door_ordinal"] = 1
            events[1]["exception_class"] = (
                "org.apache.zookeeper.KeeperException$ConnectionLossException")
            events[10]["site"] = gate_v2.CHECK
            for row, site in ((events[3], "A#setIfNewer"),
                              (events[8], "A#getAliases")):
                row.update(site=site, key=gate_v2.ALIAS_KEY,
                           value_object="value7", identity_kind="reference_value")
            return gate_v2.analyze(
                Trace(tuple(events)),
                {"check_sites": [gate_v2.CHECK], "throw_site": "T#throw",
                 "exception_class": "org.apache.solr.common.SolrException"}, [],
                return_code=0, timed_out=False,
                allow_local_timeline_doors=False,
                reject_coarse_roots=True, require_event_time_paths=True)

        self.assertEqual(evaluate("sampled")["eligible_doors_before_target"], 0)
        self.assertEqual(evaluate("exact")["eligible_doors_before_target"], 1)


if __name__ == "__main__":
    unittest.main()
