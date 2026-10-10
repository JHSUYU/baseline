import copy
import unittest

from audit_exact_path import (ASSIGNED, CONSUMED, GUARD_READ, PUBLISHED,
                              evaluate)


def row(seq, kind, site, occurrence, thread, **fields):
    return {"id": f"trial:{seq}", "seq": seq, "type": kind, "site": site,
            "occurrence": occurrence, "thread_id": thread,
            "node": "shard-4", "epoch": 0, **fields}


def valid_trace():
    return (
        row(1, "DOOR_OBSERVED",
            "org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState@1641:door:1",
            "watcher", 11),
        row(2, "STATE_WRITE", PUBLISHED, "watcher", 11,
            object="reader-1", key="clusterState", version=1,
            version_confidence="exact"),
        row(3, "STATE_READ", CONSUMED, "processor", 22,
            object="reader-1", key="clusterState", version=1,
            version_confidence="exact"),
        row(4, "STATE_WRITE", ASSIGNED, "processor", 22,
            object="processor-1", key="clusterState", version=1,
            version_confidence="exact"),
        row(5, "STATE_READ", GUARD_READ, "guard", 22,
            object="processor-1", key="clusterState", version=1,
            version_confidence="exact"),
        row(6, "TARGET_CHECK",
            "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks@994:branch:9",
            "guard", 22),
    )


class ExactPathAuditTest(unittest.TestCase):
    def test_two_exact_reference_hops_reach_guard(self):
        result = evaluate(valid_trace())
        self.assertEqual(1, result["strict_witness_count"])
        self.assertTrue(result["eligible_for_fault_pilot"])

    def test_sampled_value_is_only_candidate(self):
        events = list(copy.deepcopy(valid_trace()))
        events[1]["version_confidence"] = "sampled"
        result = evaluate(tuple(events))
        self.assertEqual(0, result["strict_witness_count"])
        self.assertGreater(result["candidate_state_edges"], 0)

    def test_different_reader_or_field_value_is_not_a_path(self):
        for index, field, value in ((2, "object", "another-reader"),
                                    (4, "version", 2),
                                    (4, "object", "another-processor")):
            with self.subTest(index=index, field=field):
                events = list(copy.deepcopy(valid_trace()))
                events[index][field] = value
                self.assertEqual(0, evaluate(tuple(events))["strict_witness_count"])

    def test_wrong_actor_and_reversed_time_are_not_a_path(self):
        events = list(copy.deepcopy(valid_trace()))
        events[0]["node"] = "shard-2"
        self.assertEqual(0, evaluate(tuple(events))["strict_witness_count"])
        events = list(copy.deepcopy(valid_trace()))
        events[1]["seq"] = 7
        self.assertEqual(0, evaluate(tuple(events))["strict_witness_count"])


if __name__ == "__main__":
    unittest.main()
