#!/usr/bin/env python3
"""Offline controls for sealed SOLR-39 v5 reclassification and v6 oracle."""

from __future__ import annotations

import copy
import json
import unittest

from audit_trial import (EXCEPTION, GATE, THROW, audit_rows,
                         events_from, markers_from)
from reconcile import RAW, rebuild_state, verify_sealed


class OfflineContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results, cls.rows, cls.markers, cls.errors = [], [], [], []
        for number in (1, 2, 3):
            trial = RAW / "trials" / f"r{number:04d}"
            cls.results.append(json.loads((trial / "result.json").read_text()))
            cls.rows.append(events_from(trial))
            marks, errors = markers_from(trial)
            cls.markers.append(marks)
            cls.errors.append(errors)

    def examine(self, number, *, rows=None, markers=None, result=None):
        i = number - 1
        result = result if result is not None else self.results[i]
        return audit_rows(rows if rows is not None else self.rows[i],
                          markers if markers is not None else self.markers[i],
                          result, result["plan"], self.errors[i])

    def test_sealed_archive_and_raw_members(self):
        self.assertEqual(verify_sealed()["member_count"], 323)

    def test_only_admin_origin_prior_ref_trial_is_strict_valid(self):
        posts = [self.examine(n) for n in (1, 2, 3)]
        self.assertEqual([p["valid"] for p in posts], [False, False, True])
        self.assertEqual([p["exact_target_exception_candidate"] for p in posts],
                         [False, False, False])
        path = posts[2]["retained_reference_paths"][0]
        self.assertEqual((path["cache_write_seq"], path["fault_applied_seq"],
                          path["target_read_seq"], path["target_check_seq"]),
                         (32094, 32106, 32892, 32895))
        self.assertEqual((path["node"], path["epoch"], path["manager_object"],
                          path["aliases_ref"], path["zk_version"]),
                         ("node2", 0, "o10", 81, 15))
        self.assertEqual(set(path["observed_edge_kinds"]),
                         {"state_exact_ref", "program_return"})
        state = rebuild_state(posts, self.results, self.rows)
        self.assertEqual(state["valid_trials"], [3])
        self.assertEqual(state["invalid_trials"], [1, 2])
        self.assertEqual(state["completed_fault_trials"], [1, 2, 3])
        self.assertEqual(len(state["seen_sequences"]), 3)
        self.assertEqual(state["queue"], [])
        self.assertEqual(state["remaining_budget"]["trials"], 9)
        self.assertEqual(state["trials"][2]["novelty"]["observed_reference_edges"], 1)

    def test_failing_junit_is_separate_from_intact_target_path(self):
        result = copy.deepcopy(self.results[2])
        result["junit_validation"]["status"] = "failed"
        result["junit_validation"]["failures"] = 1
        result["return_code"] = 1
        post = self.examine(3, result=result)
        self.assertTrue(post["valid"])
        self.assertTrue(post["novelty_eligible"])
        self.assertEqual(post["workload_outcome"]["junit_status"], "failed")
        self.assertEqual(post["workload_outcome"]["return_code"], 1)

    def test_wrong_actual_path_and_manager_fail_closed(self):
        rows = [dict(r) for r in self.rows[2]]
        gate = next(r for r in rows if r.get("site") == GATE and
                    r.get("node") == "node2" and r.get("seq") < 32106 and
                    r.get("key") == "/aliases.json" and
                    r.get("occurrence", "").endswith(":task:1937:1"))
        gate["key"] = "/wrong-znode"
        post = self.examine(3, rows=rows)
        self.assertFalse(post["valid"])
        self.assertFalse(post["novelty_eligible"])
        self.assertEqual(post["qualification"], "prefault_resource_manager_gate_missing")
        gate["key"] = "/aliases.json"
        gate["object"] = "other-manager"
        post = self.examine(3, rows=rows)
        self.assertFalse(post["valid"])
        self.assertFalse(post["novelty_eligible"])
        self.assertEqual(post["qualification"],
                         "postfault_bound_actor_prior_reference_target_missing")

    def test_wrong_actor_and_timeout_cannot_get_novelty(self):
        rows = [dict(r) for r in self.rows[2]]
        next(r for r in rows if r.get("type") == "FAULT_APPLIED" and
             r.get("fault_id") == "solr39_v5_node2_0_15")["node"] = "node3"
        post = self.examine(3, rows=rows)
        self.assertFalse(post["valid"])
        self.assertFalse(post["novelty_eligible"])
        self.assertEqual(post["qualification"], "fault_identity_mismatch")
        result = copy.deepcopy(self.results[2])
        result["timed_out"] = True
        post = self.examine(3, result=result)
        self.assertFalse(post["valid"])
        self.assertFalse(post["novelty_eligible"])
        self.assertEqual(post["qualification"], "trace_or_target_identity_incomplete")

    def test_exact_target_throw_is_independent_of_junit_and_path_credit(self):
        rows = [dict(r) for r in self.rows[2]]
        check = next(r for r in rows if r.get("seq") == 32895)
        for row in rows:
            if row["seq"] > 32895:
                row["seq"] += 1
        throw = dict(check)
        throw.update(type="TARGET_THROW", seq=32896, ts=check["ts"] + 1,
                     site=THROW, exception_class=EXCEPTION,
                     id="synthetic-exact-target-throw")
        rows.append(throw)
        result = copy.deepcopy(self.results[2])
        result["junit_validation"]["status"] = "failed"
        result["junit_validation"]["failures"] = 1
        result["return_code"] = 1
        post = self.examine(3, rows=rows, result=result)
        self.assertTrue(post["exact_target_exception_candidate"])
        self.assertEqual(post["exact_target_throw_candidates"][0]["check_seq"], 32895)
        self.assertTrue(post["valid"])
        # A missing reference publication removes novelty, not the exact
        # attributed @247 observation or its source-review candidate label.
        rows = [r for r in rows if r.get("seq") != 32094]
        post = self.examine(3, rows=rows, result=result)
        self.assertTrue(post["exact_target_exception_candidate"])
        self.assertFalse(post["valid"])
        self.assertFalse(post["novelty_eligible"])


if __name__ == "__main__":
    unittest.main()
