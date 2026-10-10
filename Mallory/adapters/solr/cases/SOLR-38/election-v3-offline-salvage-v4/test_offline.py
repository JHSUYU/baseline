#!/usr/bin/env python3
"""Negative controls for SOLR-38's sealed postfault strict path."""

from __future__ import annotations

import copy
import unittest

import audit


class SealedPostfaultPathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, cls.summary, cls.trials, _ = audit.read_sealed()

    def fault_trial(self):
        trial, events = self.trials[1]
        return copy.deepcopy(trial), copy.deepcopy(events)

    def reject(self, trial, events):
        with self.assertRaises(ValueError):
            audit.selected_postfault_path(trial, tuple(events))

    def test_sealed_pilot_has_two_postfault_paths(self):
        receipt = audit.audit()
        self.assertEqual(receipt["same_actor_postfault_strict_target_trials"], 2)
        self.assertTrue(receipt["bounded_pilot_evidence_valid"])
        self.assertFalse(receipt["new_bug_confirmed"])

    def test_wrong_applied_actor_rejected(self):
        trial, events = self.fault_trial()
        for event in events:
            if event.get("type") == "FAULT_APPLIED":
                event["node"] = "node9"
        self.reject(trial, events)

    def test_wrong_door_ordinal_rejected(self):
        trial, events = self.fault_trial()
        trial["plan"][0]["point"]["door_ordinal"] = 2
        self.reject(trial, events)

    def test_wrong_exception_rejected(self):
        trial, events = self.fault_trial()
        for event in events:
            if event.get("type") == "FAULT_APPLIED":
                event["exception_class"] = "java.io.IOException"
        self.reject(trial, events)

    def test_different_descriptor_rejected(self):
        trial, events = self.fault_trial()
        for event in events:
            if event.get("site") == audit.v3_graph.unique_writer.VALUE_READ:
                event["object"] = "different-descriptor"
        self.reject(trial, events)

    def test_intervening_writer_rejected(self):
        trial, events = self.fault_trial()
        native = next(event for event in events if
                      event.get("site", "").startswith(
                          audit.v3_graph.unique_writer.NATIVE_WRITE)
                      and event.get("node") == "node2" and
                      event.get("seq") == 1523)
        competitor = copy.deepcopy(native)
        competitor["id"] += ":competing"
        competitor["seq"] = 1524
        events = list(events) + [competitor]
        self.reject(trial, events)

    def test_target_before_fault_rejected(self):
        trial, events = self.fault_trial()
        for event in events:
            if event.get("type") == "TARGET_CHECK":
                event["seq"] = 1300
        self.reject(trial, events)


if __name__ == "__main__":
    unittest.main()
