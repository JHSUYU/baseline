#!/usr/bin/env python3
"""Sealed-trace positive and negative controls for the v3 graph/controller gate."""

from __future__ import annotations

import copy
import gzip
import json
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import config_v3
import graph_overlay
import run_campaign

REFERENCE = Path(__file__).resolve().parent / "reference-events.jsonl.gz"


class StrictGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if config_v3.sha(REFERENCE) != graph_overlay.unique_writer.SEALED_TRACE_SHA256:
            raise ValueError("sealed reference trace changed")
        raw = gzip.decompress(REFERENCE.read_bytes())
        cls.events = tuple(json.loads(line) for line in raw.splitlines())

    def graph(self, events: tuple[dict, ...]):
        return graph_overlay.SourceBackedSolr38Graph(events, reject_coarse_roots=True)

    def strict_paths(self, events: tuple[dict, ...]) -> int:
        graph = self.graph(events)
        by_id = {row["id"]: row for row in events if isinstance(row.get("id"), str)}
        count = 0
        for row in graph_overlay.unique_writer.witnesses(list(events)):
            path = graph.event_path(by_id[row["door"]], by_id[row["target"]], require_edge=True)
            if path and any(edge.kind == "state" and
                            edge.evidence.startswith("solr38_source_backed") for edge in path):
                count += 1
        return count

    def test_sealed_trace_has_twelve_strict_paths(self) -> None:
        self.assertEqual(self.strict_paths(self.events), 12)
        graph = self.graph(self.events)
        self.assertEqual(sum(edge.kind == "state" and
                             edge.evidence.startswith("solr38_source_backed")
                             for edge in graph.edges), 4)

    def test_same_value_different_descriptor_has_no_promoted_edge(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("site") == graph_overlay.unique_writer.VALUE_WRITE:
                row["object"] = "other-descriptor"
        self.assertEqual(self.strict_paths(tuple(events)), 0)

    def test_competing_setter_has_no_promoted_edge(self) -> None:
        events = list(copy.deepcopy(self.events))
        for write in list(events):
            if (write.get("type") == "STATE_WRITE" and
                    str(write.get("site", "")).startswith(graph_overlay.unique_writer.NATIVE_WRITE)
                    and write.get("object") in {"o24", "o37"}):
                other = copy.deepcopy(write)
                other["seq"] = write["seq"] + 1
                other["id"] = write["id"] + ":competing"
                events.append(other)
        self.assertEqual(self.strict_paths(tuple(events)), 0)

    def test_wrong_thread_has_no_promoted_edge(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row.get("site") == graph_overlay.unique_writer.VALUE_READ:
                row["thread_id"] = -1
        self.assertEqual(self.strict_paths(tuple(events)), 0)

    def test_wrong_door_exception_has_no_promoted_edge(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if (row.get("type") == "DOOR_OBSERVED" and
                    str(row.get("site", "")).startswith(graph_overlay.unique_writer.DOOR)):
                row["exception_class"] = "java.io.IOException"
        self.assertEqual(self.strict_paths(tuple(events)), 0)

    def test_target_absent_has_no_promoted_edge(self) -> None:
        events = tuple(row for row in self.events if row.get("type") != "TARGET_CHECK")
        self.assertEqual(self.strict_paths(events), 0)

    def test_failed_fresh_healthy_gate_clears_fault_queue(self) -> None:
        state = {"out": "/unused", "status": "running", "queue": ["fault"],
                 "runtime_attestation": None}
        fake = SimpleNamespace(_apply_result=lambda state, config, result, item:
                               state.update(runtime_attestation={"valid": True}))
        run_campaign.install_health_gate(fake)
        with patch.object(run_campaign, "strict_healthy_proof",
                          return_value={"valid": False, "reason": "no strict edge"}):
            fake._apply_result(state, {}, {"trial_id": 0, "feedback": {"status": "observed"}}, None)
        self.assertEqual(state["status"], "healthy_strict_path_missing")
        self.assertEqual(state["queue"], [])

    def test_fault_without_postfault_target_is_not_accepted(self) -> None:
        fake = SimpleNamespace(_apply_result=lambda state, config, result, item: None)
        run_campaign.install_health_gate(fake)
        result = {"trial_id": 1, "feedback": {"all_faults_effective": True,
                                             "target_check_reached": False,
                                             "target_reached": False}}
        fake._apply_result({}, {}, result, None)
        self.assertFalse(result["feedback"]["solr38_strict_fault_acceptance"])


if __name__ == "__main__":
    unittest.main()
