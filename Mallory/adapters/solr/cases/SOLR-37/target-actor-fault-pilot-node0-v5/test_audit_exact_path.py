import copy
import unittest

from audit_exact_path import (ASSIGNED, CONSUMED, DOOR, EXCEPTION, GUARD_READ, PUBLISHED,
                              REGION, RESOURCE, audit_trial, evaluate)


def row(seq, kind, site, occurrence, thread, **fields):
    return {"id": f"trial:{seq}", "seq": seq, "type": kind, "site": site,
            "occurrence": occurrence, "thread_id": thread,
            "node": "shard-4", "epoch": 0, **fields}


def valid_trace():
    return (
        row(1, "DOOR_OBSERVED",
            DOOR, "watcher", 11, region=REGION, resource=RESOURCE,
            occurrence_kind="watcher_region", reader_ref="reader-1",
            state_version=1, door_ordinal=1, exception_class=EXCEPTION),
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

    def test_fault_receipts_and_postfault_target_are_required(self):
        point = {"site": DOOR, "node": "shard-4", "epoch": 0,
                 "door_ordinal": 1, "resource": RESOURCE, "region": REGION,
                 "occurrence_kind": "watcher_region"}
        plan = [{"fault_id": "f1", "point": point, "fault_type": "EXCEPTION",
                 "exception_class": EXCEPTION}]
        identity = {"region": REGION, "resource": RESOURCE,
                    "occurrence_kind": "watcher_region", "reader_ref": "reader-1",
                    "state_version": 1, "door_ordinal": 1}
        trace = (
            row(1, "DOOR_OBSERVED", DOOR, "watcher", 11,
                exception_class=EXCEPTION, **identity),
            row(2, "FAULT_MATCHED", DOOR, "watcher", 11, fault_id="f1",
                fault_type="EXCEPTION", exception_class=EXCEPTION, **identity),
            row(3, "FAULT_APPLIED", DOOR, "watcher", 11, fault_id="f1",
                fault_type="EXCEPTION", exception_class=EXCEPTION, **identity),
            row(4, "TARGET_CHECK",
                "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks@994:branch:9",
                "guard", 22),
        )
        self.assertTrue(audit_trial(trace, plan)["valid"])
        for index, field, value in ((1, "reader_ref", "wrong"),
                                    (2, "resource", "/collections/other/state.json"),
                                    (2, "occurrence", "other-watcher")):
            with self.subTest(index=index, field=field):
                events = list(copy.deepcopy(trace))
                events[index][field] = value
                self.assertFalse(audit_trial(tuple(events), plan)["valid"])
        self.assertFalse(audit_trial(trace[:3], plan)["valid"])
        self.assertFalse(audit_trial(trace, [{**plan[0], "point":
            {**point, "resource": "/collections/other/state.json"}}])["valid"])
        events = list(copy.deepcopy(valid_trace()))
        events[1]["seq"] = 7
        self.assertEqual(0, evaluate(tuple(events))["strict_witness_count"])

    def test_actual_target_actor_can_change_between_healthy_runs(self):
        events = list(copy.deepcopy(valid_trace()))
        for event in events:
            event["node"] = "shard-2"
            event["occurrence"] = event["occurrence"].replace("shard-4", "shard-2")
        result = evaluate(tuple(events))
        self.assertEqual(1, result["strict_witness_count"])
        self.assertEqual([{"node": "shard-2", "epoch": 0, "door_ordinal": 1}],
                         result["qualified_points"])
        events[0]["node"] = "shard-4"
        self.assertEqual(0, evaluate(tuple(events))["strict_witness_count"])


if __name__ == "__main__":
    unittest.main()
