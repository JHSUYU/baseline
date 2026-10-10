"""Offline controls for the isolated SOLR-39 preemptive fault package."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from audit_trial import GATE, audit_rows, events_from, markers_from
from run_faults import (HERE, HEALTHY, apply_result, initial_state,
                        make_fault, selected_points)


class StrictPreemptiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = events_from(HEALTHY)
        cls.markers, cls.errors = markers_from(HEALTHY)
        cls.points = selected_points()

    def test_sealed_three_late_doors_have_exact_identity(self):
        self.assertEqual([(p["point"]["node"], p["point"]["door_ordinal"])
                          for p in self.points], [("node2", 12), ("node3", 13),
                                                  ("node2", 15)])
        state = initial_state(json.loads((HERE / "config.json").read_text()), "go-test")
        self.assertEqual(len(state["queue"]), 3)
        self.assertEqual(len(set(state["seen_sequences"])), 3)

    def _synthetic_fault(self, resource: str):
        plan = [make_fault(self.points[0])]
        door = next(row for row in self.rows if row.get("type") == "DOOR_OBSERVED" and
                    row.get("node") == "node2" and row.get("epoch") == 0 and
                    row.get("door_ordinal") == 12 and row.get("site") == plan[0]["point"]["site"])
        gate = copy.deepcopy(door)
        gate.update(type="STATE_READ", site=GATE, key=resource, object="o10",
                    seq=50000, id="test:50000")
        matched = copy.deepcopy(door)
        matched.update(type="FAULT_MATCHED", fault_id=plan[0]["fault_id"],
                       fault_type="EXCEPTION", exception_class=plan[0]["exception_class"],
                       seq=50001, id="test:50001")
        applied = copy.deepcopy(matched)
        applied.update(type="FAULT_APPLIED", seq=50002, id="test:50002")
        result = {"plan": plan, "site_catalog_validation": {"valid": True}}
        return self.rows + [gate, matched, applied], result, plan

    def test_wrong_actual_resource_rejected_despite_matching_actor_ordinal(self):
        rows, result, plan = self._synthetic_fault("/some-other-znode")
        post = audit_rows(rows, self.markers, result, plan, self.errors)
        self.assertFalse(post["valid"])
        self.assertEqual(post["qualification"], "prefault_resource_manager_gate_missing")
        gate_source = (HERE / "src/edu/uva/liftlab/mallory/solr/solr39/PreemptiveGate.java").read_text()
        self.assertLess(gate_source.index("RESOURCE.equals(resource)"),
                        gate_source.index("Probe.stateRead(manager, resource, MARKER)"))
        self.assertLess(gate_source.index("Probe.stateRead(manager, resource, MARKER)"),
                        gate_source.index("Probe.beforeDoor(site, exceptionClass)"))

    def test_missing_or_late_marker_rejected(self):
        rows, result, plan = self._synthetic_fault("/aliases.json")
        rows[-3]["seq"] = 50003  # gate after FAULT_MATCHED and FAULT_APPLIED
        post = audit_rows(rows, self.markers, result, plan, self.errors)
        self.assertFalse(post["valid"])
        self.assertEqual(post["qualification"], "prefault_resource_manager_gate_missing")

    def test_wrong_gate_thread_rejected(self):
        rows, result, plan = self._synthetic_fault("/aliases.json")
        rows[-3]["thread_id"] = rows[-2]["thread_id"] + 1
        post = audit_rows(rows, self.markers, result, plan, self.errors)
        self.assertFalse(post["valid"])
        self.assertEqual(post["qualification"], "prefault_resource_manager_gate_missing")

    def test_invalid_trial_gives_zero_novelty_and_no_children(self):
        config = json.loads((HERE / "config.json").read_text())
        state = initial_state(config, "go-test")
        item = state["queue"].pop(0)
        result = {"trial_id": 1, "plan": item["plan"], "elapsed_seconds": 1,
                  "feedback": {"coverage_ids": ["new_block"],
                               "closure_coverage_ids": ["new_closure_block"]}}
        post = {"valid": False, "qualification": "wrong_resource"}
        old = (list(state["coverage_ids"]), list(state["closure_coverage_ids"]),
               list(state["seen_sequences"]), len(state["queue"]))
        apply_result(state, config, result, post, [], item)
        self.assertEqual((state["coverage_ids"], state["closure_coverage_ids"],
                          state["seen_sequences"], len(state["queue"])), old)
        self.assertEqual(result["case_local_novelty"],
                         {"coverage": 0, "closure_coverage": 0,
                          "observed_reference_edges": 0})


if __name__ == "__main__":
    unittest.main()
