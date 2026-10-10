#!/usr/bin/env python3
"""Negative controls for the SOLR-39 case-local graph overlay."""

import unittest

from audit_graph_gap import (TRIAL, audit_rows, events_from, join_field_events,
                             markers_from, qualify, validate_postfault_retained_reference,
                             validate_return, validate_value)


class GraphGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = events_from(TRIAL)
        cls.markers, errors = markers_from(TRIAL)
        assert not errors
        cls.paired, collisions = join_field_events(cls.rows, cls.markers)
        assert not any(collisions.values())
        cls.paths = audit_rows(cls.rows, cls.markers)["candidate_paths"]
        cls.path = cls.paths[-1]

    def changed_row(self, seq, **changes):
        rows = self.rows.copy()
        index = next(i for i, row in enumerate(rows) if row["seq"] == seq)
        rows[index] = {**rows[index], **changes}
        return rows

    def changed_marker(self, seq, **changes):
        paired = self.paired.copy()
        index = next(i for i, row in enumerate(paired) if row["field_seq"] == seq)
        paired[index] = {**paired[index], **changes}
        return paired

    def test_sealed_trace_yields_three_late_observed_paths(self):
        result = qualify()
        self.assertEqual(result["status"], "strict_late_healthy_doors_observed")
        self.assertEqual(len(result["qualified_event_time_paths"]), 5)
        self.assertEqual(len(result["late_qualified_paths"]), 3)
        for path in result["qualified_event_time_paths"]:
            self.assertEqual([edge["kind"] for edge in path["observed_witness"]],
                             ["program_order", "state_exact_ref", "program_return"])
            self.assertTrue(all(edge["certainty"] == "observed"
                                for edge in path["observed_witness"]))

    def test_different_caller_thread_rejected(self):
        rows = self.changed_row(self.path["target_read_seq"], thread_id=-999)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validate_return(rows, self.path)

    def test_different_caller_epoch_rejected(self):
        rows = self.changed_row(self.path["target_read_seq"], epoch=7)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validate_return(rows, self.path)

    def test_wrong_nested_parent_rejected(self):
        seq = self.path["target_read_seq"] - 1
        rows = self.changed_row(seq, parent_id="unrelated:occurrence")
        with self.assertRaisesRegex(ValueError, "under target"):
            validate_return(rows, self.path)

    def test_unbalanced_getter_exit_rejected(self):
        seq = self.path["target_read_seq"] + 1
        rows = self.changed_row(seq, occurrence="unrelated:occurrence")
        with self.assertRaisesRegex(ValueError, "unbalanced nested exit"):
            validate_return(rows, self.path)

    def test_wrong_manager_object_rejected(self):
        rows = self.changed_row(self.path["target_read_seq"], object="other-manager")
        with self.assertRaisesRegex(ValueError, "same Aliases reference"):
            validate_value(rows, self.paired, self.path)

    def test_wrong_aliases_reference_rejected(self):
        paired = self.changed_marker(self.path["target_read_seq"], aliases_ref=10**9)
        with self.assertRaisesRegex(ValueError, "same Aliases reference"):
            validate_value(self.rows, paired, self.path)

    def test_intervening_publication_rejected(self):
        paired = self.paired + [{**next(row for row in self.paired
                                       if row["field_seq"] == self.path["cache_write_seq"]),
                                  "field_seq": self.path["cache_write_seq"] + 1}]
        with self.assertRaisesRegex(ValueError, "intervening aliases publication"):
            validate_value(self.rows, paired, self.path)

    def test_prior_reference_on_bound_manager(self):
        write = next(row for row in self.rows
                     if row["seq"] == self.path["cache_write_seq"])
        simulated_fault = {"seq": write["seq"] + 1, "node": write["node"],
                           "epoch": write["epoch"]}
        observed_write, observed_read = validate_postfault_retained_reference(
            self.rows, self.paired, self.path, simulated_fault, write["object"])
        self.assertEqual(observed_write["seq"], write["seq"])
        self.assertEqual(observed_read["seq"], self.path["target_read_seq"])

    def test_postfault_target_different_manager_rejected(self):
        write = next(row for row in self.rows
                     if row["seq"] == self.path["cache_write_seq"])
        simulated_fault = {"seq": write["seq"] + 1, "node": write["node"],
                           "epoch": write["epoch"]}
        with self.assertRaisesRegex(ValueError, "bound manager"):
            validate_postfault_retained_reference(
                self.rows, self.paired, self.path, simulated_fault, "other-manager")

    def test_postfault_no_prior_reference_rejected(self):
        write = next(row for row in self.rows
                     if row["seq"] == self.path["cache_write_seq"])
        simulated_fault = {"seq": write["seq"] - 1, "node": write["node"],
                           "epoch": write["epoch"]}
        with self.assertRaisesRegex(ValueError, "prior reference"):
            validate_postfault_retained_reference(
                self.rows, self.paired, self.path, simulated_fault, write["object"])


if __name__ == "__main__":
    unittest.main()
