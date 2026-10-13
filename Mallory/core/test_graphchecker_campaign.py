"""Focused native GraphChecker campaign evidence tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Mallory.core.graphchecker_campaign import (_door_types, _runner,
                                                _runner_class_sha256, load_config, load_trace,
                                                summarize_evidence, validate_plan)


class GraphCheckerCampaignTest(unittest.TestCase):
    TARGET = {"check_site_id": "check", "throw_site_id": "throw",
              "exception_class": "java.io.IOException"}
    FAULT = {"siteId": "door", "node": "nn-1#epoch0",
             "occurrenceId": "occ-A", "ordinal": 1,
             "exceptionClass": "java.io.IOException"}

    def rows(self):
        return [
            {"kind": "WINDOW_OPEN", "seq": 1},
            {"kind": "ACTIVATION", "seq": 2, "occurrenceId": "occ-A",
             "node": "nn-1#epoch0"},
            {"kind": "FAULT_DOOR", "seq": 3, "siteId": "door",
             "node": "nn-1#epoch0", "occurrenceId": "occ-A", "doorOrdinal": 1},
            {"kind": "FAULT_APPLIED", "seq": 4, "siteId": "door",
             "node": "nn-1#epoch0", "occurrenceId": "occ-A", "doorOrdinal": 1,
             "exceptionClass": "java.io.IOException"},
            {"kind": "TARGET_CHECK", "seq": 5, "siteId": "check",
             "node": "nn-1#epoch0", "occurrenceId": "occ-A", "outcome": "TRUE"},
            {"kind": "TARGET_THROW", "seq": 6, "siteId": "throw",
             "node": "nn-1#epoch0", "occurrenceId": "occ-A",
             "exceptionClass": "java.io.IOException"},
            {"kind": "WINDOW_CLOSE", "seq": 7},
        ]

    def graph(self):
        return {"schemaVersion": 1, "targetSite": "check",
                "targetReached": True, "closureOccurrenceIds": ["occ-A"],
                "closureOccurrenceCutoffs": {"occ-A": 6},
                "closureEdgeIds": ["edge-1"], "closureCoverageSiteIds": ["cov-1"],
                "staticScopeTargetFound": True,
                "staticMayObservedDoorSiteIds": ["may-door"], "gaps": {}}

    def test_exact_native_receipt_and_throw_trigger_target(self):
        evidence = summarize_evidence(self.rows(), self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertTrue(evidence["strict_injection"])
        self.assertTrue(evidence["target_exception_triggered"])
        self.assertEqual([6], evidence["target_throw_seqs_after_fault"])
        self.assertEqual("observed_closure", evidence["eligible_doors"][0]["tier"])

    def test_same_site_in_other_occurrence_is_not_claimed_as_closure(self):
        rows = self.rows()
        rows.insert(3, {"kind": "FAULT_DOOR", "seq": 3,
                        "siteId": "door", "node": "nn-2#epoch0",
                        "occurrenceId": "occ-B", "doorOrdinal": 1})
        # A duplicate sequence is invalid at trace-loading time; for the
        # evidence unit test, leave a gap in order to distinguish instances.
        rows[4]["seq"] = 4
        rows[5]["seq"] = 5
        rows[6]["seq"] = 6
        rows[7]["seq"] = 7
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertEqual(["observed_closure", "outside_closure"],
                         [item["tier"] for item in evidence["eligible_doors"]])

    def test_static_may_is_exploration_only(self):
        rows = self.rows()
        rows.insert(3, {"kind": "FAULT_DOOR", "seq": 3,
                        "siteId": "may-door", "node": "nn-2#epoch0",
                        "occurrenceId": "occ-B", "doorOrdinal": 1})
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertEqual("static_may_observed", evidence["eligible_doors"][1]["tier"])
        self.assertEqual(["occ-A"], evidence["causal_closure_occurrences"])
        self.assertEqual(["edge-1"], evidence["causal_closure_edges"])

    def test_closure_door_after_target_is_not_an_ancestor(self):
        rows = self.rows()
        rows.insert(-1, {"kind": "FAULT_DOOR", "seq": 8,
                         "siteId": "late-door", "node": "nn-1#epoch0",
                         "occurrenceId": "occ-A", "doorOrdinal": 1})
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertEqual("after_target", evidence["eligible_doors"][-1]["tier"])

    def test_missing_or_wrong_fault_identity_cannot_trigger_candidate(self):
        for modify in (lambda rows: rows.pop(2),
                       lambda rows: rows[3].update(node="nn-2#epoch0"),
                       lambda rows: rows[3].update(doorOrdinal=2)):
            with self.subTest(modify=modify):
                rows = self.rows()
                modify(rows)
                evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                              [self.FAULT])
                self.assertFalse(evidence["strict_injection"])
                self.assertFalse(evidence["target_exception_triggered"])

    def test_target_throw_needs_exact_site_type_identity_and_time(self):
        for update in ({"siteId": "another-throw"},
                       {"exceptionClass": "java.lang.RuntimeException"},
                       {"occurrenceId": ""}, {"seq": 3}):
            with self.subTest(update=update):
                rows = self.rows()
                rows[5].update(update)
                evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                              [self.FAULT])
                self.assertFalse(evidence["target_exception_triggered"])

    def test_exact_throw_is_oracle_even_with_incomplete_closure_or_check(self):
        rows = self.rows()
        rows[5]["occurrenceId"] = "occ-B"
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertTrue(evidence["target_exception_triggered"])
        self.assertEqual([], evidence["target_throw_seqs_on_closure_occurrence"])
        self.assertEqual([], evidence["target_throw_seqs_after_check"])

    def test_trace_requires_complete_window_and_monotone_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            rows = self.rows()
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            self.assertEqual(len(rows), len(load_trace(path)))
            for invalid in (rows[:-1], [{**rows[0], "seq": 3}, *rows[1:]]):
                path.write_text("".join(json.dumps(row) + "\n" for row in invalid))
                with self.assertRaises(ValueError):
                    load_trace(path)
            shifted = [{**row, "seq": row["seq"] + 1} for row in rows]
            outside = [{"kind": "COVERAGE", "seq": 1}, *shifted,
                       {"kind": "TARGET_THROW", "seq": 9}]
            path.write_text("".join(json.dumps(row) + "\n" for row in outside))
            self.assertEqual(shifted, load_trace(path))

    def test_plan_rejects_partial_identity(self):
        self.assertEqual([self.FAULT], validate_plan({"faults": [self.FAULT]}))
        with self.assertRaises(ValueError):
            validate_plan({"faults": [{**self.FAULT, "occurrenceId": ""}]})
        selected = _door_types({"doors": [{"siteId": "door",
                                            "exceptionClass": "java.io.IOException"}]})
        self.assertEqual([self.FAULT], validate_plan({"faults": [self.FAULT]}, selected))
        with self.assertRaisesRegex(ValueError, "typed selected door"):
            validate_plan({"faults": [{**self.FAULT,
                                       "exceptionClass": "java.lang.Error"}]}, selected)

    def test_config_rejects_legacy_probe_and_missing_exact_throw(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("original", "tool", "test", "cwd"):
                (root / name).mkdir()
            for name in ("scope.jsonl", "graph.jar"):
                (root / name).write_text("x")
            manifest = {"faultController": "MALLORY_PROBE", "targets": [
                {"kind": "THROW", "siteId": "throw",
                 "exceptionClass": "java.io.IOException"}]}
            (root / "manifest.json").write_text(json.dumps(manifest))
            config = {"schema_version": 1, "case_id": "fixture",
                      "junit": {"class": "A", "method": "test"},
                      "target": {"throw_site_id": "throw",
                                 "exception_class": "java.io.IOException"},
                      "weave_manifest": "manifest.json",
                      "static_scope_map": "scope.jsonl",
                      "original_classes": "original",
                      "tool_classpath": ["tool"], "test_classpath": ["test"],
                      "graph_jar": "graph.jar", "cwd": "cwd"}
            path = root / "config.json"
            path.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "legacy MALLORY_PROBE"):
                load_config(path)
            manifest["faultController"] = "NONE"
            manifest["targets"][0]["siteId"] = "wrong"
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "exact target throw"):
                load_config(path)

    def test_explicit_runner_resolves_original_junit_without_shell(self):
        junit = {"class": "fixture.OriginalJUnit", "method": "originalTest"}
        runner = _runner({"main_class": "fixture.WorkerThreadRunner",
                          "args": ["{class}", "{method}"],
                          "jvm_args": ["-Djava.io.tmpdir=/scratch"]}, junit)
        self.assertEqual(["fixture.OriginalJUnit", "originalTest"], runner["args"])
        with tempfile.TemporaryDirectory() as temp:
            clazz = Path(temp) / "fixture" / "WorkerThreadRunner.class"
            clazz.parent.mkdir()
            clazz.write_bytes(b"pinned runner")
            self.assertEqual(64, len(_runner_class_sha256(runner["main_class"],
                                                        [Path(temp)])))
        with self.assertRaisesRegex(ValueError, "second Java instrumentation"):
            _runner({"main_class": "fixture.Runner", "args": ["{class}"],
                     "jvm_args": ["-javaagent:old.jar"]}, junit)


if __name__ == "__main__":
    unittest.main()
