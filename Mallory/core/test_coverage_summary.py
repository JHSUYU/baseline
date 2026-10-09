"""Compact coverage retains occurrence-specific closure feedback."""

from __future__ import annotations

import unittest

from .events import Trace
from .feedback import analyze


def event(kind: str, seq: int, occurrence: str, **fields):
    return {"type": kind, "id": f"e{seq}", "seq": seq, "node": "solr-1",
            "epoch": 0, "occurrence": occurrence, "region": occurrence,
            "site": fields.pop("site", "probe"),
            **fields}


TARGET = {"check_sites": ["C#guard"], "throw_site": "C#throw",
          "exception_class": "java.lang.IllegalStateException", "node": "solr-1"}


class CoverageSummaryTest(unittest.TestCase):
    def test_later_hit_inside_closure_survives_first_hit_outside(self):
        events = (
            event("REGION_ENTER", 1, "startup", site="startup"),
            event("REGION_ENTER", 2, "target", site="target"),
            event("TARGET_CHECK", 3, "target", site="C#guard", outcome="TAKEN"),
            event("TARGET_CHECK", 4, "target", site="C#guard", outcome="TAKEN"),
            event("COVERAGE_DEF", 5, "coverage-definition", coverage_ref=1,
                  coverage_id="C#shared:TAKEN"),
            event("COVERAGE_DEF", 6, "coverage-definition", coverage_ref=2,
                  coverage_id="C#startup"),
            event("COVERAGE_DEF", 7, "coverage-definition", coverage_ref=3,
                  coverage_id="C#target"),
            event("COVERAGE_SUMMARY", 8, "startup", coverage_refs=[1, 2]),
            event("COVERAGE_SUMMARY", 9, "target", coverage_refs=[1, 3]),
        )
        feedback = analyze(Trace(events), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "observed")
        self.assertEqual(feedback["event_count"], 9)
        self.assertEqual(feedback["coverage_ids"],
                         ["C#shared:TAKEN", "C#startup", "C#target"])
        self.assertEqual(feedback["closure_coverage_ids"],
                         ["C#shared:TAKEN", "C#target"])
        self.assertEqual(len(feedback["target_instances"]), 1)
        self.assertEqual(feedback["coverage_ref_errors"], [])

    def test_undefined_and_conflicting_refs_fail_closed(self):
        prefix = (event("REGION_ENTER", 1, "target", site="target"),
                  event("TARGET_CHECK", 2, "target", site="C#guard"))
        undefined = prefix + (event("COVERAGE_SUMMARY", 3, "target", coverage_refs=[9]),)
        feedback = analyze(Trace(undefined), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "coverage_ref_invalid")
        self.assertTrue(any(error.startswith("undefined_ref")
                            for error in feedback["coverage_ref_errors"]))
        conflicting = prefix + (
            event("COVERAGE_DEF", 3, "coverage-definition", coverage_ref=1,
                  coverage_id="C#one"),
            event("COVERAGE_DEF", 4, "coverage-definition", coverage_ref=1,
                  coverage_id="C#other"),
            event("COVERAGE_SUMMARY", 5, "target", coverage_refs=[1]),
        )
        feedback = analyze(Trace(conflicting), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "coverage_ref_invalid")
        self.assertIn("conflicting_ref:1", feedback["coverage_ref_errors"])

    def test_previous_string_summary_is_still_readable(self):
        events = (event("REGION_ENTER", 1, "target", site="target"),
                  event("TARGET_CHECK", 2, "target", site="C#guard"),
                  event("COVERAGE_SUMMARY", 3, "target", coverage_ids=["C#legacy"]))
        feedback = analyze(Trace(events), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["status"], "observed")
        self.assertEqual(feedback["coverage_ids"], ["C#legacy"])
        self.assertEqual(feedback["closure_coverage_ids"], ["C#legacy"])

    def test_legacy_branch_and_method_rows_keep_previous_coverage_semantics(self):
        events = (
            event("REGION_ENTER", 1, "target", site="target"),
            event("BRANCH", 2, "target", site="C#branch", outcome="TAKEN",
                  coverage_id="C#branch:TAKEN"),
            event("METHOD", 3, "target", site="C#method", coverage_id="C#method"),
            event("TARGET_CHECK", 4, "target", site="C#guard", outcome="TAKEN"),
        )
        feedback = analyze(Trace(events), TARGET, [], return_code=0, timed_out=False)
        self.assertEqual(feedback["coverage_ids"], ["C#branch:TAKEN", "C#method"])
        self.assertEqual(feedback["closure_coverage_ids"], ["C#branch:TAKEN", "C#method"])


if __name__ == "__main__":
    unittest.main()
