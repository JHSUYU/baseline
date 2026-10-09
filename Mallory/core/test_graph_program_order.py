"""Exact event-time proofs across nested regions."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import unittest

from .events import Trace
from .feedback import analyze
from .graph import OccurrenceGraph


def event(kind, seq, occurrence, *, thread=7, region=None, **fields):
    row = {"type": kind, "id": f"e{seq}", "seq": seq, "node": "n",
           "epoch": 0, "thread_id": thread, "occurrence": occurrence,
           **fields}
    if region is not None:
        row["region"] = region
    return row


def nested_trace():
    return [event("REGION_ENTER", 1, "parent", region="P", parent_id="root"),
            event("DOOR_OBSERVED", 2, "parent", region="P"),
            event("REGION_ENTER", 3, "child", region="C", parent_id="parent"),
            event("TARGET_CHECK", 4, "child", region="C"),
            event("REGION_EXIT", 5, "child", region="C"),
            event("REGION_EXIT", 6, "parent", region="P")]


def insert_between(rows, kind, occurrence, region, **fields):
    for row in rows[2:]:
        row["seq"] += 1
    rows.insert(2, event(kind, 3, occurrence, region=region, id="extra", **fields))


class NestedProgramOrderTest(unittest.TestCase):
    def path(self, rows):
        graph = OccurrenceGraph(tuple(rows), reject_coarse_roots=True)
        door = next(row for row in rows if row["type"] == "DOOR_OBSERVED")
        check = next(row for row in rows if row["type"] == "TARGET_CHECK")
        return graph, graph.event_path(door, check, require_edge=True)

    def test_direct_nested_region_has_root_free_event_path(self):
        graph, path = self.path(nested_trace())
        self.assertIsNotNone(path)
        self.assertEqual([(edge.kind, edge.producer_event, edge.consumer_event)
                          for edge in path], [("program_order", "e2", "e3")])
        self.assertEqual(1, graph.summary()["edges_by_kind"]["program_order"])

    def test_latest_parent_event_carries_earlier_door(self):
        rows = nested_trace()
        insert_between(rows, "METHOD", "parent", "P")
        graph, path = self.path(rows)
        self.assertEqual("extra", path[0].producer_event)
        self.assertEqual(1, graph.summary()["edges_by_kind"]["program_order"])

    def test_rejects_ambiguous_or_non_nested_order(self):
        changes = {
            "other_thread": lambda rows: rows[2].update(thread_id=8),
            "missing_thread": lambda rows: rows[1].pop("thread_id"),
            "boolean_thread": lambda rows: rows[1].update(thread_id=True),
            "wrong_parent": lambda rows: rows[2].update(parent_id="other"),
            "wrong_region": lambda rows: rows[1].update(region="other"),
            "missing_child_occurrence": lambda rows: rows[2].update(occurrence=None),
            "duplicate_sequence": lambda rows: rows[2].update(seq=2),
            "boolean_sequence": lambda rows: rows[1].update(seq=True),
            "duplicate_event_id": lambda rows: rows[2].update(id="e2"),
            "duplicate_parent_enter": lambda rows: insert_between(
                rows, "REGION_ENTER", "parent", "P", parent_id="root"),
            "parent_exited": lambda rows: insert_between(
                rows, "REGION_EXIT", "parent", "P"),
            "parent_exit_without_thread": lambda rows: insert_between(
                rows, "REGION_EXIT", "parent", "P", thread=None),
            "intervening_child": lambda rows: insert_between(
                rows, "REGION_ENTER", "other", "O", parent_id="parent"),
            "duplicate_child_enter": lambda rows: insert_between(
                rows, "REGION_ENTER", "child", "C", parent_id="parent"),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                rows = nested_trace()
                change(rows)
                _, path = self.path(rows)
                self.assertIsNone(path)

    @unittest.skipUnless(os.environ.get("MALLORY_SOLR18_V38_CAMPAIGN"),
                         "set MALLORY_SOLR18_V38_CAMPAIGN for the SHA-bound replay")
    def test_sha_bound_solr18_v38_replay(self):
        campaign = Path(os.environ["MALLORY_SOLR18_V38_CAMPAIGN"])
        packed = (campaign / "trials/r0000/events.jsonl.gz").read_bytes()
        self.assertEqual("7d72f575a822c3e8e1e458e778a4a642c6323406aa1334a7b1c2c5b841287960",
                         hashlib.sha256(packed).hexdigest())
        raw = gzip.decompress(packed)
        self.assertEqual("1f465be326555af6814375a2a9e9dd4bd902124f4491b7e540bbfccd5c118462",
                         hashlib.sha256(raw).hexdigest())
        events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
        config_bytes = (campaign / "config.json").read_bytes()
        self.assertEqual("13e5bf5b7bdce68cf69185c0e933da49ff87e6cd3a8842336daab6b371e6ed59",
                         hashlib.sha256(config_bytes).hexdigest())
        config = json.loads(config_bytes)
        sites = set(config["target"]["check_sites"])
        checks = [row for row in events if row.get("type") == "TARGET_CHECK"
                  and row.get("site") in sites]
        doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
                 and row.get("node") not in (None, "unknown") and
                 isinstance(row.get("thread_id"), int)]
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        paths = [(door, check, graph.event_path(door, check, require_edge=True))
                 for check in checks for door in doors if door["seq"] < check["seq"]]
        witnesses = [(door, check, path) for door, check, path in paths if path is not None]
        self.assertEqual(51, len(checks))
        self.assertEqual(51, len(witnesses))
        self.assertEqual(17, len({door["id"] for door, _, _ in witnesses}))
        self.assertTrue(all(len(path) == 1 and path[0].kind == "program_order"
                            for _, _, path in witnesses))
        feedback = analyze(Trace(events), config["target"], [], return_code=0,
                           timed_out=False, reject_coarse_roots=True,
                           require_event_time_paths=True)
        self.assertEqual("observed", feedback["status"])
        self.assertEqual(17, sum(door["in_closure"] for door in feedback["doors"]))
        self.assertEqual(17, sum(edge["kind"] == "program_order"
                                 for edge in feedback["closure_edges"]))


if __name__ == "__main__":
    unittest.main()
