#!/usr/bin/env python3
"""Check the frozen HBASE-31 RPC witness against strict token and thread rules."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CORE = REPO / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(CORE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402


class RequestPathTest(unittest.TestCase):
    def setUp(self) -> None:
        trace = REPO / "data/mallory/calibration_v31_typed/HBASE-31/trials/r0000/events.jsonl.gz"
        compressed = trace.read_bytes()
        self.assertEqual(hashlib.sha256(compressed).hexdigest(),
                         "4a2b6ccdee96431c84fbc6eb41301d1d60fafbfc5db92e7541a498313f52a752")
        self.events = [json.loads(line) for line in gzip.decompress(compressed).splitlines()]
        # Model only the missing, source-backed actor scope on this one worker thread.
        for event in self.events:
            if event["seq"] in (45, 46):
                self.assertEqual(event["node"], "unknown")
                event["node"] = "master0"
                event["occurrence"] = "unscoped:master0:0:root:thread:606:segment:1"
        self.by_seq = {event["seq"]: event for event in self.events}

    def path(self, events):
        rows = {event["seq"]: event for event in events}
        return OccurrenceGraph(events, reject_coarse_roots=True).event_path(
            rows[45], rows[49], require_edge=True)

    def test_matching_request_token_has_observed_rpc_path(self) -> None:
        path = self.path(self.events)
        self.assertIsNotNone(path)
        self.assertEqual([edge.kind for edge in path], ["rpc", "region_parent"])
        self.assertTrue(all(edge.certainty == "observed" for edge in path))

    def test_wrong_request_token_cannot_join_server_check(self) -> None:
        changed = copy.deepcopy(self.events)
        next(event for event in changed if event["seq"] == 47)["correlation"] = \
            "different-request-token"
        self.assertIsNone(self.path(changed))

    def test_different_producer_thread_cannot_join_send(self) -> None:
        changed = copy.deepcopy(self.events)
        next(event for event in changed if event["seq"] == 46)["thread_id"] = 999
        self.assertIsNone(self.path(changed))


if __name__ == "__main__":
    unittest.main()
