#!/usr/bin/env python3
"""Offline trace checks for SOLR-40 healthy admission."""

import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("solr40_full_campaign", HERE / "run_campaign.py")
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)

from Mallory.core.events import Trace  # noqa: E402


def event(kind, seq, occurrence, site):
    row = {"type": kind, "id": f"e{seq}", "seq": seq, "node": "node1",
           "epoch": 0, "occurrence": occurrence, "region": occurrence,
           "site": site}
    if kind == "DOOR_OBSERVED":
        row.update({"door_ordinal": 1, "fault_type": "EXCEPTION",
                    "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException"})
    return row


class HealthyGateTest(unittest.TestCase):
    def feedback(self, events):
        target = {"check_sites": [campaign.CHECK],
                  "throw_site": campaign.CHECK.replace("@132:branch:1", "@133:throw:1"),
                  "exception_class": "org.apache.solr.common.SolrException"}
        trace = Trace(tuple(events))
        options = {"return_code": 0, "timed_out": False,
                   "allow_local_timeline_doors": True,
                   "reject_coarse_roots": True}
        base = campaign.BASE_ANALYZE(trace, target, [], **options)
        gated = campaign.analyze(trace, target, [], **options)
        return base, gated

    def test_same_node_door_before_only_later_occurrence_cannot_promote(self):
        base, gated = self.feedback([
            event("TARGET_CHECK", 1, "request-1", campaign.CHECK),
            event("DOOR_OBSERVED", 2, "watcher", campaign.DOOR),
            event("TARGET_CHECK", 3, "request-2", campaign.CHECK),
        ])
        self.assertEqual(base["status"], "observed")
        self.assertEqual(len(base["doors"]), 1)
        self.assertEqual(gated["status"], "healthy_exact_watcher_door_missing")
        self.assertEqual(gated["eligible_doors_before_target"], 0)

    def test_exact_door_before_check_in_same_occurrence_can_promote(self):
        base, gated = self.feedback([
            event("TARGET_CHECK", 1, "request-1", campaign.CHECK),
            event("DOOR_OBSERVED", 2, "request-2", campaign.DOOR),
            event("TARGET_CHECK", 3, "request-2", campaign.CHECK),
        ])
        self.assertEqual(len(base["doors"]), 1)
        self.assertEqual(gated["status"], "observed")
        self.assertEqual(gated["eligible_doors_before_target"], 1)
        self.assertEqual(gated["doors"][0]["point"]["node"], "node1")


if __name__ == "__main__":
    unittest.main()
