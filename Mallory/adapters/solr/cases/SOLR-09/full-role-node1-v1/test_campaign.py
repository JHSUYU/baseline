"""Offline checks for SOLR-09's exact role selector and fail-closed gate."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("solr09_node1_full_runner", HERE / "run_campaign.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RoleCampaignTest(unittest.TestCase):
    def test_fault_plan_accepts_only_exact_typed_role_and_distinct_ordinals(self):
        first = {"fault_id": "f1", "point": {"site": runner.SITE, "role": runner.ROLE,
                                               "role_ordinal": 1},
                 "fault_type": "EXCEPTION", "exception_class": runner.EXCEPTION}
        self.assertTrue(runner.valid_plan([first]))
        self.assertFalse(runner.valid_plan([first, first]))
        self.assertFalse(runner.valid_plan([{**first, "point": {"site": runner.SITE,
                    "role": runner.ROLE, "role_ordinal": 1, "node": "node2"}}]))
        self.assertFalse(runner.valid_plan([{**first, "exception_class": "java.io.IOException"}]))

    def test_mutation_keeps_only_same_occurrence_typed_door(self):
        raw = {"site": runner.SITE, "node": "node2", "epoch": 0, "door_ordinal": 1}
        door = {"site": runner.SITE, "point": raw, "event_id": "healthy:272",
                "exception_class": runner.EXCEPTION, "role": runner.ROLE,
                "role_resolution": "unique", "role_ordinal": 1,
                "role_node": "node2", "role_epoch": 0,
                "role_source_occurrence": "node2:0:deleteCore:one",
                "local_timeline_evidence": {"target_check_event_id": "healthy:286"}}
        candidate = {"faults": [{"fault_id": "f1", "point": raw,
                                  "fault_type": "EXCEPTION",
                                  "exception_class": runner.EXCEPTION}],
                     "signature": "old"}
        with patch.object(runner, "BASE_MUTATE", return_value=[candidate]):
            result = runner.mutate([], {"doors": [door]}, {"budget": {"max_faults_per_trial": 3}})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["faults"][0]["point"],
                         {"site": runner.SITE, "role": runner.ROLE, "role_ordinal": 1})
        door["role_node"] = "node3"
        candidate["faults"][0]["point"] = raw
        with patch.object(runner, "BASE_MUTATE", return_value=[candidate]):
            self.assertEqual(runner.mutate([], {"doors": [door]}, {}), [])

    def test_fault_receipt_requires_same_physical_command(self):
        point = {"site": runner.SITE, "role": runner.ROLE, "role_ordinal": 1}
        event = {"site": runner.SITE, "role": runner.ROLE,
                 "role_resolution": "unique", "role_ordinal": 1,
                 "node": "node2", "epoch": 0, "occurrence": "node2:0:cmd",
                 "role_node": "node2", "role_epoch": 0,
                 "role_source_occurrence": "node2:0:cmd", "region": runner.REGION,
                 "thread_id": 217}
        self.assertTrue(runner.role_receipt(event, point))
        self.assertFalse(runner.role_receipt({**event, "role_source_occurrence": "other"},
                                             point))
        self.assertFalse(runner.role_receipt({**event, "node": "unknown"}, point))

    def test_candidate_requires_throw_in_applied_command_occurrence(self):
        point = {"site": runner.SITE, "role": runner.ROLE, "role_ordinal": 1}
        fault = {"fault_id": "f1", "point": point, "fault_type": "EXCEPTION",
                 "exception_class": runner.EXCEPTION}
        identity = {"site": runner.SITE, "role": runner.ROLE,
                    "role_resolution": "unique", "role_ordinal": 1,
                    "node": "node2", "epoch": 0, "occurrence": "node2:0:cmd",
                    "role_node": "node2", "role_epoch": 0,
                    "role_source_occurrence": "node2:0:cmd", "region": runner.REGION,
                    "thread_id": 217, "context": "delete-command"}
        trace = SimpleNamespace(events=[
            {**identity, "id": "m", "type": "FAULT_MATCHED", "fault_id": "f1",
             "exception_class": runner.EXCEPTION, "seq": 10},
            {**identity, "id": "a", "type": "FAULT_APPLIED", "fault_id": "f1",
             "exception_class": runner.EXCEPTION, "seq": 11},
            {"id": "t", "type": "TARGET_THROW", "site": runner.THROW,
             "exception_class": "org.apache.solr.common.SolrException",
             "node": "node3", "epoch": 0, "occurrence": "node3:0:other",
             "thread_id": 222, "context": "other-command", "seq": 20}])
        target = {"exception_class": "org.apache.solr.common.SolrException"}
        with patch.object(runner, "BASE_ANALYZE", return_value={
                "doors": [], "target_exception_candidate": True}):
            feedback = runner.analyze(trace, target, [fault])
        self.assertFalse(feedback["target_exception_candidate"])
        trace.events[-1].update(node="node2", occurrence="node2:0:cmd",
                                thread_id=217, context="delete-command")
        with patch.object(runner, "BASE_ANALYZE", return_value={
                "doors": [], "target_exception_candidate": True}):
            feedback = runner.analyze(trace, target, [fault])
        self.assertTrue(feedback["target_exception_candidate"])

    def test_fresh_healthy_gap_stops_campaign_before_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = {"out": tmp, "status": "running", "queue": [{"faults": [1]}]}
            with patch.object(runner, "BASE_APPLY_RESULT", return_value=None), \
                 patch.object(runner, "audit_healthy",
                              return_value={"case_id": "SOLR-09", "status": "healthy_role_gap"}):
                runner.apply_result(state, {}, {"trial_id": 0}, None)
            self.assertEqual(state["status"], "healthy_role_gap")
            self.assertEqual(state["queue"], [])
            self.assertTrue((Path(tmp) / "fresh-healthy-role-audit.json").is_file())


if __name__ == "__main__":
    unittest.main()
