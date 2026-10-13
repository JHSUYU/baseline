"""Focused native GraphChecker campaign evidence tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_campaign import (_archive_jsonl, _check_woven_major,
                                                _door_types, _runner, _tree_sha256,
                                                _trial_verdict,
                                                _trial_arg,
                                                _runner_class_sha256, _verify_prepared,
                                                load_config, load_trace, prepare,
                                                scan_window_trace, summarize_evidence,
                                                validate_plan, verify_trial_artifacts)
from Mallory.core.graphchecker_trial import analyze_trial


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
                "targetThrowClosures": [{
                    "siteId": "throw", "exceptionClass": "java.io.IOException",
                    "node": "nn-1#epoch0", "occurrenceId": "occ-A", "seq": 6,
                    "closureOccurrenceCutoffs": {"occ-A": 6}}],
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
        self.assertTrue(evidence["injection_specific_target_reached"])
        self.assertTrue(evidence["injection_specific_target_throw"])
        self.assertEqual(("candidate", True),
                         _trial_verdict(evidence, [self.FAULT], 0))

    def test_replay_selector_matches_new_exact_rpc_occurrence(self):
        plan = {**self.FAULT, "replayOccurrenceId": "stable-rpc-lineage"}
        rows = self.rows()
        for row in rows:
            if row.get("occurrenceId") == "occ-A":
                row["occurrenceId"] = "occ-B"
            if row["kind"] in {"FAULT_DOOR", "FAULT_APPLIED"}:
                row["replayOccurrenceId"] = "stable-rpc-lineage"
        graph = self.graph()
        graph["closureOccurrenceIds"] = ["occ-B"]
        graph["closureOccurrenceCutoffs"] = {"occ-B": 6}
        graph["targetThrowClosures"][0]["occurrenceId"] = "occ-B"
        graph["targetThrowClosures"][0]["closureOccurrenceCutoffs"] = {"occ-B": 6}
        evidence = summarize_evidence(rows, graph, self.TARGET, [plan],
                                      {"door": "java.io.IOException"})
        self.assertTrue(evidence["strict_injection"])
        self.assertEqual(["occ-B"], evidence["actual_fault_occurrence_ids"])
        self.assertTrue(evidence["injection_specific_target_throw"])
        self.assertEqual("stable-rpc-lineage",
                         evidence["eligible_doors"][0]["replayOccurrenceId"])
        rows[3]["replayOccurrenceId"] = "other-rpc-lineage"
        rejected = summarize_evidence(rows, graph, self.TARGET, [plan])
        self.assertFalse(rejected["strict_injection"])
        self.assertFalse(rejected["target_exception_triggered"])

    def test_short_circuit_throw_can_omit_second_guard_in_one_trial(self):
        # The negated A && B rollback checks can throw when A is false and B
        # never executes. The exact THROW is still a valid oracle; guard
        # completeness is tracked across the campaign, not forced per trial.
        target = {**self.TARGET, "check_site_ids": ["check", "check-2"]}
        graph = {**self.graph(), "configuredTargetSites": ["check", "check-2"],
                 "observedTargetSites": ["check"], "missingTargetSites": ["check-2"],
                 "allTargetSitesReached": False}
        evidence = summarize_evidence(self.rows(), graph, target, [self.FAULT])
        self.assertEqual(["check-2"], evidence["missing_check_sites_in_trial"])
        self.assertTrue(evidence["injection_specific_target_throw"])
        self.assertEqual(("candidate", True),
                         _trial_verdict(evidence, [self.FAULT], 0))

    def test_other_request_throw_does_not_inherit_check_closure(self):
        rows = self.rows()
        rows[5]["occurrenceId"] = "occ-B"
        graph = self.graph()
        graph["targetThrowClosures"][0]["occurrenceId"] = "occ-B"
        graph["targetThrowClosures"][0]["closureOccurrenceCutoffs"] = {"occ-B": 6}
        evidence = summarize_evidence(rows, graph, self.TARGET, [self.FAULT])
        self.assertTrue(evidence["injection_specific_target_reached"])
        self.assertTrue(evidence["target_exception_triggered"])
        self.assertFalse(evidence["injection_specific_target_throw"])
        self.assertEqual(("needs_causal_review", False),
                         _trial_verdict(evidence, [self.FAULT], 0))

    def test_second_request_target_does_not_validate_first_request_fault(self):
        rows = self.rows()
        rows[4]["occurrenceId"] = "occ-B"
        rows[5]["occurrenceId"] = "occ-B"
        graph = self.graph()
        graph["closureOccurrenceIds"] = ["occ-B"]
        graph["closureOccurrenceCutoffs"] = {"occ-B": 6}
        evidence = summarize_evidence(rows, graph, self.TARGET, [self.FAULT],
                                      {"door": "java.io.IOException"})
        self.assertTrue(evidence["strict_injection"])
        self.assertTrue(evidence["target_exception_triggered"])
        self.assertTrue(evidence["post_fault_target_reached"])
        self.assertFalse(evidence["injection_specific_target_reached"])
        self.assertEqual([], evidence["fault_occurrences_in_target_closure"])
        self.assertEqual(("needs_causal_review", False),
                         _trial_verdict(evidence, [self.FAULT], 0))

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

    def test_selected_observed_door_is_noncausal_exploration(self):
        rows = self.rows()
        rows.insert(3, {"kind": "FAULT_DOOR", "seq": 3,
                        "siteId": "selected-door", "node": "nn-2#epoch0",
                        "occurrenceId": "occ-B", "doorOrdinal": 1})
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT],
                                      {"door": "java.io.IOException",
                                       "selected-door": "java.io.IOException"})
        self.assertEqual("selected_scope_observed",
                         evidence["eligible_doors"][1]["tier"])
        self.assertEqual(["selected-door"],
                         evidence["selected_scope_observed_door_sites"])
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

    def test_throw_only_target_does_not_require_static_branch_anchor(self):
        rows = self.rows()
        target = {"throw_site_id": "throw", "exception_class": "java.io.IOException"}
        graph = self.graph()
        graph["targetSite"] = "throw"
        graph["staticScopeTargetFound"] = False
        evidence = summarize_evidence(rows, graph, target, [self.FAULT])
        self.assertTrue(evidence["target_exception_triggered"])

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
        replay = {**self.FAULT, "replayOccurrenceId": "stable-rpc-lineage"}
        self.assertEqual([replay], validate_plan({"faults": [replay]}))
        with self.assertRaisesRegex(ValueError, "replay occurrence"):
            validate_plan({"faults": [{**self.FAULT, "replayOccurrenceId": ""}]})
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

    def test_stream_window_and_durable_gzip_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp)
            raw = trial / "graphchecker-raw.jsonl"
            window = trial / "graphchecker-trace.jsonl"
            graph = trial / "graphchecker-graph.jsonl"
            rows = [{"kind": "COVERAGE", "seq": 1},
                    *[{**row, "seq": row["seq"] + 1} for row in self.rows()],
                    {"kind": "COVERAGE", "seq": 9}]
            raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
            selected, count = scan_window_trace(raw, window)
            self.assertEqual(7, count)
            self.assertEqual(["FAULT_DOOR", "FAULT_APPLIED", "TARGET_CHECK",
                              "TARGET_THROW"], [row["kind"] for row in selected])
            self.assertEqual(7, len(load_trace(window)))
            graph.write_text('{"kind":"edge"}\n')
            artifacts = {name: _archive_jsonl(trial / filename, trial)
                         for name, filename in (
                             ("raw_trace", raw.name),
                             ("window_trace", window.name),
                             ("graph", graph.name))}
            result = {"backend": "graphchecker_native", "status": "checked",
                      "artifacts": artifacts,
                      "raw_trace_sha256": artifacts["raw_trace"]["content_sha256"],
                      "trace_sha256": artifacts["window_trace"]["content_sha256"],
                      "graph_sha256": artifacts["graph"]["content_sha256"]}
            verify_trial_artifacts(trial, result)
            self.assertFalse(raw.exists())
            self.assertFalse(window.exists())
            self.assertEqual(7, len(load_trace(trial / "graphchecker-trace.jsonl.gz")))
            with (trial / "graphchecker-trace.jsonl.gz").open("ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaisesRegex(ValueError, "changed window_trace"):
                verify_trial_artifacts(trial, result)

    def test_multi_guard_analysis_passes_ordered_sites_to_java(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "trial"
            trial.mkdir()
            (trial / "graphchecker-trace.jsonl").write_text("{}\n")
            jar = root / "graph.jar"
            jar.write_bytes(b"fixture")
            seen = []

            def fake_run(command, **_):
                seen.extend(json.loads(command[-1]))
                (trial / "graphchecker-feedback.json").write_text(json.dumps({
                    "schemaVersion": 1, "targetSite": "guard-a",
                    "configuredTargetSites": ["guard-a", "guard-b"]}))

            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=fake_run):
                analyze_trial(trial, ["guard-a", "guard-b"], jar=jar)
            self.assertEqual(["guard-a", "guard-b"], seen)

    def test_compressed_prior_is_materialized_only_during_graph_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "trial"
            trial.mkdir()
            (trial / "graphchecker-trace.jsonl").write_text('{}\n')
            jar = root / "graph.jar"
            jar.write_bytes(b"fixture")
            prior = root / "prior.jsonl"
            prior.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            receipt = _archive_jsonl(prior, root)
            observed = []

            def fake_run(command, **_):
                materialized = Path(command[-1])
                observed.append((materialized, materialized.read_bytes()))
                (trial / "graphchecker-feedback.json").write_text(
                    json.dumps({"schemaVersion": 1, "targetSite": "check"}))

            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=fake_run):
                analyze_trial(trial, "check", root / receipt["path"], jar)
            self.assertEqual(prior.read_bytes() if prior.exists() else
                             "".join(json.dumps(row) + "\n" for row in self.rows()).encode(),
                             observed[0][1])
            self.assertFalse(observed[0][0].exists())

    def test_pinned_trial_template_and_java_major_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture"
            fixture.mkdir()
            file = fixture / "initial.txt"
            file.write_text("before")
            before = _tree_sha256(fixture)
            file.write_text("after")
            self.assertNotEqual(before, _tree_sha256(fixture))
            self.assertEqual(f"-Djava.io.tmpdir={root}/cwd",
                             _trial_arg("-Djava.io.tmpdir={trial_cwd}",
                                        root / "trial", root / "cwd"))
            clazz = root / "Selected.class"
            clazz.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x37")
            with self.assertRaisesRegex(ValueError, "exceeds Java 8 max 52"):
                _check_woven_major(clazz, 8, 52)
            clazz.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
            self.assertEqual(52, _check_woven_major(clazz, 8, 52))

    def test_weaver_receives_exact_planner_dependency_classpath_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original"
            tool = root / "tool"
            test = root / "test"
            for directory in (original, tool, test):
                directory.mkdir()
            clazz = original / "fixture" / "Target.class"
            clazz.parent.mkdir()
            clazz.write_bytes(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")
            junit = test / "fixture" / "Test.class"
            junit.parent.mkdir()
            junit.write_bytes(clazz.read_bytes())
            runner = (tool / "edu" / "uva" / "liftlab" / "mallory" /
                      "graphchecker" / "weave" / "JUnitTrialMain.class")
            runner.parent.mkdir(parents=True)
            runner.write_bytes(clazz.read_bytes())
            dep1, dep2 = root / "dep1.jar", root / "dep2.jar"
            dep1.write_bytes(b"first")
            dep2.write_bytes(b"second")
            dependencies = [str(dep1), str(dep2)]
            from hashlib import sha256
            import os
            cp_hash = sha256(os.pathsep.join(dependencies).encode()).hexdigest()
            manifest = {"schemaVersion": 1, "faultController": "NONE",
                        "sootDependencyClasspathSha256": cp_hash,
                        "targets": [{"clazz": "fixture.Target", "method": "run",
                                     "kind": "THROW", "siteId": "throw",
                                     "exceptionClass": "java.io.IOException"}],
                        "doors": []}
            (root / "manifest.json").write_text(json.dumps(manifest))
            (root / "scope.jsonl").write_text("{}\n")
            (root / "graph.jar").write_bytes(b"graph")
            raw = {"schema_version": 1, "case_id": "CP-ORDER",
                   "junit": {"class": "fixture.Test", "method": "test"},
                   "target": {"throw_site_id": "throw",
                              "exception_class": "java.io.IOException"},
                   "weave_manifest": str(root / "manifest.json"),
                   "static_scope_map": str(root / "scope.jsonl"),
                   "original_classes": str(original),
                   "tool_classpath": [str(tool)],
                   "test_classpath": [str(test)],
                   "soot_dependency_classpath": dependencies,
                   "graph_jar": str(root / "graph.jar"), "cwd": str(root)}
            config_path = root / "config.json"
            config_path.write_text(json.dumps(raw))
            config = load_config(config_path)
            raw["soot_dependency_classpath"] = dependencies[::-1]
            config_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "ordered Soot dependency classpath"):
                load_config(config_path)
            raw["soot_dependency_classpath"] = dependencies
            config_path.write_text(json.dumps(raw))
            config = load_config(config_path)
            (root / "manifest.json").write_text(json.dumps({
                key: value for key, value in manifest.items()
                if key != "sootDependencyClasspathSha256"}))
            with self.assertRaisesRegex(ValueError, "ordered Soot dependency classpath"):
                load_config(config_path)
            (root / "manifest.json").write_text(json.dumps(manifest))
            config = load_config(config_path)
            launched = []

            def fake_weave(argv, **_):
                launched.append(argv)
                woven = Path(argv[-2]) / "fixture" / "Target.class"
                woven.parent.mkdir(parents=True)
                woven.write_bytes(clazz.read_bytes())

            with patch("Mallory.core.graphchecker_campaign.subprocess.run",
                       side_effect=fake_weave):
                prepared = prepare(config, root / "prepared")
            self.assertEqual(os.pathsep.join(dependencies), launched[0][-1])
            self.assertEqual([str(original), *dependencies, str(test), str(tool)],
                             json.loads((prepared / "weave-receipt.json").read_text())[
                                 "runtime_classpath"])
            self.assertEqual([prepared / "woven"], _verify_prepared(config, prepared))


if __name__ == "__main__":
    unittest.main()
