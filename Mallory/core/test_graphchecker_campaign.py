"""Focused native GraphChecker campaign evidence tests."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_campaign import (_archive_jsonl, _archive_stat,
                                                _archive_trace_pair, _trace_digest,
                                                _prior_trace_metadata,
                                                _target_throw_count,
                                                _target_throw_profiles,
                                                _profile_exceeds_healthy_envelope,
                                                _raw_target_throw_exceeds_healthy_envelope,
                                                _strict_fault_receipt,
                                                _unique_message_selectors,
                                                _static_producer_frontier_sites,
                                                _static_may_sidecar,
                                                _trial_scratch_root,
                                                _validate_scratch_root,
                                                _check_woven_major,
                                                _door_types, _runner, _tree_sha256,
                                                _manifest_target,
                                                _trial_verdict,
                                                _trial_arg,
                                                _runner_class_sha256, _verify_prepared,
                                                _tracing_runtime_jar,
                                                _runtime_classpath,
                                                load_config, load_trace, prepare, run_trial,
                                                scan_window_trace, summarize_evidence,
                                                validate_plan, verify_trial_artifacts)
from Mallory.core.graphchecker_trial import analyze_trial


class GraphCheckerCampaignTest(unittest.TestCase):
    def _stub_run_trial(self, root, rows, faults, graph=None,
                        healthy_profiles=None):
        prepared = root / "prepared"
        prepared.mkdir()
        (prepared / "weave-manifest.json").write_text(json.dumps({
            "doors": [{"siteId": "door", "exceptionClass": "java.io.IOException"}]}))
        (prepared / "weave-receipt.json").write_text("{}")
        scope = root / "scope.jsonl"
        scope.write_text("")
        config = {"case_id": "fixture", "junit": {"class": "OriginalJUnit"},
                  "target": self.TARGET, "target_site_rows": [],
                  "static_scope_map": scope, "static_may_scope_map": None,
                  "trial_cwd_template": None, "trial_cwd_template_sha256": None,
                  "runner": {"main_class": "OriginalRunner", "args": [],
                             "jvm_args": []}, "java": "java", "timeout_seconds": 10,
                  "graph_jar": root / "unused-graph.jar"}

        class FinishedJUnit:
            pid = os.getpid()

            def __init__(self, _argv, *, env, **_kwargs):
                Path(env["MALLORY_GC_TRACE"]).write_text("".join(
                    json.dumps(row) + "\n" for row in rows))

            def wait(self, timeout=None):
                return 0

        def graph_run(scratch, *_args):
            if graph is None:
                raise AssertionError("unmatched fast path called graph analyzer")
            (scratch / "graphchecker-feedback.json").write_text(json.dumps(graph))
            (scratch / "graphchecker-graph.jsonl").write_text('{}\n')
            return graph

        prior = None
        if healthy_profiles is not None:
            prior = root / "prior.jsonl.gz"
            prior.write_bytes(b"pinned prior")
        with patch("Mallory.core.graphchecker_campaign._verify_prepared",
                   return_value=[root / "woven"]), patch(
                   "Mallory.core.graphchecker_campaign._runtime_classpath",
                   return_value=[]), patch(
                   "Mallory.core.graphchecker_campaign._trial_scratch_root",
                   return_value=root), patch(
                   "Mallory.core.graphchecker_campaign._process_start_ticks",
                   return_value=1), patch(
                   "Mallory.core.graphchecker_campaign.subprocess.Popen",
                   side_effect=FinishedJUnit), patch(
                   "Mallory.core.graphchecker_campaign.analyze_trial",
                   side_effect=graph_run) as analyzer, patch(
                   "Mallory.core.graphchecker_campaign._prior_trace_metadata",
                   return_value=(0, "a" * 64, None)), patch(
                   "Mallory.core.graphchecker_campaign._prior_trace_profiles",
                   return_value=(healthy_profiles[0]
                                 if healthy_profiles is not None else None)):
            result = run_trial(config, prepared, root / "trial",
                               {"faults": faults}, prior)
        return result, analyzer

    def test_unmatched_without_postfault_throw_skips_graph_and_resumes_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [self.rows()[0], self.rows()[2], self.rows()[4], self.rows()[-1]]
            result, analyzer = self._stub_run_trial(root, rows, [self.FAULT])
            analyzer.assert_not_called()
            self.assertEqual("unmatched", result["status"])
            self.assertEqual("skipped_unmatched_v1", result["graph_analysis"])
            self.assertEqual(0.0, result["phase_seconds"]["graph_analysis"])
            self.assertEqual((0, 0), (result["applied_faults_raw"],
                                      result["matched_fault_prefix_raw"]))
            self.assertTrue(result["junit_passed"])
            self.assertEqual(1, result["evidence"]["raw_target_check_rows"])
            self.assertEqual({"raw_trace", "window_trace"},
                             set(result["artifacts"]))
            verify_trial_artifacts(root / "trial", result)
            archive = root / "trial" / result["artifacts"]["raw_trace"]["path"]
            with archive.open("ab") as output:
                output.write(b"damaged")
            with self.assertRaisesRegex(ValueError, "changed raw_trace"):
                verify_trial_artifacts(root / "trial", result)

    def test_partial_applied_without_target_throw_skips_graph_but_keeps_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [row for row in self.rows() if row["kind"] != "TARGET_THROW"]
            second = {**self.FAULT, "ordinal": 2}
            result, analyzer = self._stub_run_trial(root, rows, [self.FAULT, second])
            analyzer.assert_not_called()
            self.assertEqual("skipped_unmatched_v1", result["graph_analysis"])
            self.assertEqual((1, 1), (result["applied_faults_raw"],
                                      result["matched_fault_prefix_raw"]))
            self.assertEqual(["occ-A"], result[
                "matched_fault_prefix_occurrence_ids"])
            self.assertFalse(result["partial_target_exception_observed"])
            verify_trial_artifacts(root / "trial", result)
            with self.assertRaisesRegex(ValueError, "invalid unmatched graph-skip"):
                verify_trial_artifacts(root / "trial", {
                    **result, "status": "checked"})
            with self.assertRaisesRegex(ValueError, "invalid unmatched graph-skip"):
                verify_trial_artifacts(root / "trial", {
                    **result, "partial_target_exception_observed": True})

    def test_partial_applied_target_throw_keeps_graph_and_manual_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = self.rows()
            rows[5].update(fingerprintVersion=1, structuralFingerprint="b" * 64)
            second = {**self.FAULT, "ordinal": 2}
            result, analyzer = self._stub_run_trial(
                root, rows, [self.FAULT, second], self.graph(), [{}])
            analyzer.assert_called_once()
            self.assertEqual("unmatched", result["status"])
            self.assertEqual("completed", result["graph_analysis"])
            self.assertEqual((1, 1), (result["applied_faults_raw"],
                                      result["matched_fault_prefix_raw"]))
            self.assertEqual(["occ-A"], result[
                "matched_fault_prefix_occurrence_ids"])
            self.assertTrue(result["partial_target_exception_observed"])
            self.assertTrue(result[
                "partial_target_exception_candidate_raw_differential"])
            self.assertFalse(result["target_exception_candidate"])
            self.assertIn("graph", result["artifacts"])
            self.assertIn("workdir_artifact", result)
            verify_trial_artifacts(root / "trial", result)

    def test_later_mismatched_applied_row_does_not_hide_prefix_throw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = self.rows()
            rows[-1]["seq"] = 8
            rows.insert(-1, {**rows[3], "seq": 7, "doorOrdinal": 3})
            second = {**self.FAULT, "ordinal": 2}
            result, analyzer = self._stub_run_trial(
                root, rows, [self.FAULT, second], self.graph())
            analyzer.assert_called_once()
            self.assertEqual("unmatched", result["status"])
            self.assertEqual((2, 1), (result["applied_faults_raw"],
                                      result["matched_fault_prefix_raw"]))
            self.assertEqual(4, result["partial_target_throw_review_cutoff_seq"])
            self.assertEqual([6], result[
                "partial_target_throw_seqs_after_observed_fault"])

    def test_fault_free_healthy_still_runs_full_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [self.rows()[0], self.rows()[4], self.rows()[-1]]
            result, analyzer = self._stub_run_trial(root, rows, [], self.graph())
            analyzer.assert_called_once()
            self.assertEqual("healthy_seed", result["status"])
            self.assertEqual("completed", result["graph_analysis"])
            self.assertIn("graph", result["artifacts"])

    def test_sha_pinned_tracing_runtime_precedes_exact_soot_cp_without_shadowing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jar = root / "trace.jar"
            resource = "edu/uva/liftlab/mallory/graphchecker/runtime/TraceRows.class"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr(resource, b"pinned trace")
            identity = {"path": str(jar),
                        "sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                        "trace_rows_sha256": hashlib.sha256(b"pinned trace").hexdigest()}
            self.assertEqual(jar, _tracing_runtime_jar(identity, root))
            config = {"tracing_runtime_jar": jar,
                      "explicit_soot_dependency_classpath": True,
                      "original_class_dirs": [root / "original"],
                      "soot_dependency_classpath": [root / "old-runtime.jar"],
                      "test_classpath": [root / "tests"],
                      "tool_classpath": [root / "tools"]}
            self.assertEqual(jar, _runtime_classpath(config)[0])
            self.assertEqual(root / "old-runtime.jar", _runtime_classpath(config)[2])
            identity["trace_rows_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "TraceRows SHA-256"):
                _tracing_runtime_jar(identity, root)
            identity["trace_rows_sha256"] = hashlib.sha256(b"pinned trace").hexdigest()
            with zipfile.ZipFile(jar, "a") as archive:
                archive.writestr("org/apache/solr/Fake.class", b"shadow")
            identity["sha256"] = hashlib.sha256(jar.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "nontracing application classes"):
                _tracing_runtime_jar(identity, root)

    TARGET = {"check_site_id": "check", "throw_site_id": "throw",
              "exception_class": "java.io.IOException"}
    FAULT = {"siteId": "door", "node": "nn-1#epoch0",
             "occurrenceId": "occ-A", "ordinal": 1,
             "exceptionClass": "java.io.IOException"}

    def test_exact_factory_call_throw_requires_unique_manifest_identity(self):
        manifest = {"targets": [
            {"kind": "BRANCH", "siteId": "check"},
            {"kind": "CALL_THROW", "siteId": "factory",
             "exceptionClass": "java.lang.IllegalStateException"}]}
        target = {"check_site_id": "check", "throw_site_id": "factory",
                  "exception_class": "java.lang.IllegalStateException"}
        self.assertEqual(2, len(_manifest_target(manifest, target)))
        manifest["targets"].append(dict(manifest["targets"][1]))
        with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
            _manifest_target(manifest, target)

    def test_prior_trace_receipt_reuses_exact_throw_count_without_decoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "graphchecker-trace.jsonl"
            source.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            receipt = _archive_jsonl(source, root)
            archived = root / receipt["path"]
            count = _target_throw_count(self.rows(), self.TARGET)
            self.assertEqual(1, count)
            (root / "result.json").write_text(json.dumps({
                "backend": "graphchecker_native", "status": "pass",
                "case_id": "HDFS-01", "trace_sha256": receipt["content_sha256"],
                "target_throw_count_for_differential": count,
                "target_throw_count_scope": {
                    "site_id": "throw", "exception_class": "java.io.IOException"},
                "artifacts": {"window_trace": receipt}}))
            with patch("Mallory.core.graphchecker_campaign.scan_window_trace",
                       side_effect=AssertionError("prior trace was rescanned")), patch(
                       "Mallory.core.graphchecker_campaign._trace_digest",
                       side_effect=AssertionError("prior trace was decompressed")):
                self.assertEqual((1, receipt["content_sha256"], receipt["sha256"]),
                                 _prior_trace_metadata(archived, self.TARGET,
                                                       "HDFS-01"))
            result_path = root / "result.json"
            sealed = result_path.read_text()
            altered = json.loads(sealed)
            altered["target_throw_count_scope"]["site_id"] = "another-throw"
            result_path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError, "metadata differs"):
                _prior_trace_metadata(archived, self.TARGET, "HDFS-01")
            result_path.write_text(sealed)
            with archived.open("ab") as output:
                output.write(b"changed")
            with self.assertRaisesRegex(ValueError, "archive .*changed"):
                _prior_trace_metadata(archived, self.TARGET, "HDFS-01")

    def test_prior_trace_frozen_gzip_receipt_uses_full_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "graphchecker-trace.jsonl"
            source.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            receipt = _archive_jsonl(source, root)
            archived = root / receipt["path"]
            (root / "result.json").write_text(json.dumps({
                "backend": "graphchecker_native", "status": "invalid_graphchecker_trace",
                "case_id": "HDFS-01", "trace_sha256": receipt["content_sha256"],
                "artifacts": {"window_trace": receipt}}))
            with patch("Mallory.core.graphchecker_campaign.scan_window_trace",
                       wraps=scan_window_trace) as scanned:
                count, content, archive = _prior_trace_metadata(
                    archived, self.TARGET, "HDFS-01")
            self.assertEqual((1, receipt["content_sha256"], receipt["sha256"]),
                             (count, content, archive))
            self.assertEqual(1, scanned.call_count)

    def test_prior_trace_old_plain_path_keeps_original_oracle(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = Path(temporary) / "graphchecker-trace.jsonl"
            trace.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            count, content, archive = _prior_trace_metadata(trace, self.TARGET,
                                                            "HDFS-01")
            self.assertEqual((1, _trace_digest(trace)[0], None),
                             (count, content, archive))
            self.assertEqual(0, _target_throw_count([{
                "kind": "TARGET_THROW", "siteId": "throw",
                "exceptionClass": "java.io.IOException"}], self.TARGET))

    def test_alternate_gzip_levels_keep_exact_archive_receipts(self):
        content = "".join(json.dumps(row) + "\n" for row in self.rows()).encode()
        content_sha = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for level in (1, 3, 6, 9):
                trial = root / f"level-{level}"
                trial.mkdir()
                archive = trial / "graphchecker-trace.jsonl.gz"
                with archive.open("wb") as output:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=output,
                                       mtime=0, compresslevel=level) as stream:
                        stream.write(content)
                receipt = {"path": archive.name, "encoding": "gzip",
                           "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "bytes": archive.stat().st_size,
                           "content_sha256": content_sha,
                           "content_bytes": len(content)}
                result = {"backend": "graphchecker_native",
                          "status": "invalid_graphchecker_trace", "case_id": "HDFS-01",
                          "trace_sha256": content_sha,
                          "artifacts": {"window_trace": receipt}}
                (trial / "result.json").write_text(json.dumps(result))
                verify_trial_artifacts(trial, result, {"window_trace"})
                self.assertEqual((1, content_sha, receipt["sha256"]),
                                 _prior_trace_metadata(archive, self.TARGET,
                                                       "HDFS-01"))
                with archive.open("ab") as output:
                    output.write(b"changed")
                with self.assertRaisesRegex(ValueError, "changed window_trace"):
                    verify_trial_artifacts(trial, result, {"window_trace"})

    def test_legacy_plain_trial_receipts_remain_readable_and_strict(self):
        with tempfile.TemporaryDirectory() as temporary:
            trial = Path(temporary)
            content = b'{"kind":"TARGET_CHECK","siteId":"check"}\n'
            paths = {name: trial / filename for name, filename in (
                ("raw_trace", "graphchecker-raw.jsonl"),
                ("window_trace", "graphchecker-trace.jsonl"),
                ("graph", "graphchecker-graph.jsonl"))}
            for path in paths.values():
                path.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            result = {"backend": "graphchecker_native", "status": "checked",
                      "raw_trace_sha256": digest, "trace_sha256": digest,
                      "graph_sha256": digest}
            verify_trial_artifacts(trial, result)
            self.assertTrue(all(path.read_bytes() == content
                                for path in paths.values()))
            paths["window_trace"].write_bytes(content + b"changed")
            with self.assertRaisesRegex(ValueError, "changed legacy window_trace"):
                verify_trial_artifacts(trial, result)

    def test_scratch_root_override_and_default(self):
        default = Path("/dev/shm") if Path("/dev/shm").is_dir() else None
        self.assertEqual(default, _trial_scratch_root({}))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(root, _validate_scratch_root(str(root)))
            self.assertEqual(root, _trial_scratch_root({"scratch_root": root}))
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            for invalid in ("relative/path", str(root / "missing"), str(alias)):
                with self.assertRaisesRegex(ValueError, "scratch_root"):
                    _validate_scratch_root(invalid)

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
        self.assertEqual((1, 1, 0, 0), (
            evidence["raw_target_check_rows"], evidence["raw_target_throw_rows"],
            evidence["unattributed_target_check_rows"],
            evidence["unattributed_target_throw_rows"]))
        self.assertTrue(evidence["strict_injection"])
        self.assertTrue(evidence["target_exception_triggered"])
        self.assertEqual([6], evidence["target_throw_seqs_after_fault"])
        self.assertEqual("observed_closure", evidence["eligible_doors"][0]["tier"])
        self.assertTrue(evidence["injection_specific_target_reached"])
        self.assertTrue(evidence["injection_specific_target_throw"])
        self.assertEqual(("candidate", True),
                         _trial_verdict(evidence, [self.FAULT], 0))

    def test_profile_envelope_needs_a_causal_excess_over_every_healthy_seed(self):
        rows = self.rows()
        expected = "a" * 64
        novel = "b" * 64
        rows[5].update(fingerprintVersion=1, structuralFingerprint=expected)
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertEqual({expected: 1}, _target_throw_profiles(rows, self.TARGET))
        self.assertFalse(_profile_exceeds_healthy_envelope(
            evidence["target_throw_rows_after_fault"], [6], self.TARGET,
            [{expected: 1}, {expected: 1}]))
        self.assertEqual(("needs_differential_review", False),
                         _trial_verdict(evidence, [self.FAULT], 1,
                                        self.TARGET,
                                        [{expected: 1}, {expected: 1}]))
        rows[5]["structuralFingerprint"] = novel
        evidence = summarize_evidence(rows, self.graph(), self.TARGET,
                                      [self.FAULT])
        self.assertEqual(("candidate", True),
                         _trial_verdict(evidence, [self.FAULT], 1,
                                        self.TARGET,
                                        [{expected: 1}, {expected: 1}]))
        self.assertEqual(("needs_differential_review", False),
                         _trial_verdict(evidence, [self.FAULT], 1,
                                        self.TARGET,
                                        [{expected: 1}, {novel: 1}]))
        rows[5].pop("fingerprintVersion")
        self.assertIsNone(_target_throw_profiles(rows, self.TARGET))

    def test_extra_post_fault_throw_is_recorded_without_a_graph_edge(self):
        healthy = "a" * 64
        rows = self.rows()
        rows[5].update(fingerprintVersion=1, structuralFingerprint=healthy)
        extra = {**rows[5], "seq": 8}
        rows.insert(6, extra)
        self.assertTrue(_raw_target_throw_exceeds_healthy_envelope(
            rows, [extra], self.TARGET, [{healthy: 1}, {healthy: 1}]))
        self.assertFalse(_raw_target_throw_exceeds_healthy_envelope(
            rows, [extra], self.TARGET, [{healthy: 2}]))
        self.assertFalse(_raw_target_throw_exceeds_healthy_envelope(
            rows, [{**extra, "exceptionClass": "other"}], self.TARGET,
            [{healthy: 1}]))
        self.assertFalse(_raw_target_throw_exceeds_healthy_envelope(
            rows, [extra], self.TARGET, None))

    def test_raw_fault_receipt_checks_full_identity_before_graph(self):
        rows = self.rows()
        _, _, matched, strict, last_seq = _strict_fault_receipt(
            rows, [self.FAULT])
        self.assertTrue(strict)
        self.assertEqual((1, 4), (len(matched), last_seq))
        wrong = {**self.FAULT, "occurrenceId": "another-request"}
        _, _, _, strict, last_seq = _strict_fault_receipt(rows, [wrong])
        self.assertFalse(strict)
        self.assertIsNone(last_seq)

    def test_message_replay_requires_unique_seed_and_postfault_door(self):
        key, parent = "a" * 64, "b" * 64
        fault = {"siteId": "queue-offer", "node": "seed#epoch0",
                 "occurrenceId": "seed-occurrence", "replayOccurrenceId": "seed-replay",
                 "ordinal": 1, "exceptionClass": "java.io.IOException",
                 "messageReplayKey": key, "messageParentId": parent}
        door = {"kind": "FAULT_DOOR", "seq": 1, "siteId": "queue-offer",
                "node": "migrated#epoch0", "occurrenceId": "actual-occurrence",
                "replayOccurrenceId": "other-replay", "doorOrdinal": 1,
                "messageReplayKey": key, "messageParentId": parent}
        applied = {**door, "kind": "FAULT_APPLIED", "seq": 2,
                   "exceptionClass": "java.io.IOException"}
        self.assertEqual({("queue-offer", key, parent)},
                         _unique_message_selectors([door]))
        self.assertEqual(set(), _unique_message_selectors([door, {**door, "seq": 3}]))
        self.assertTrue(_strict_fault_receipt([door, applied], [fault])[3])
        self.assertFalse(_strict_fault_receipt([door, applied, {**door, "seq": 3}],
                                               [fault])[3])
        self.assertFalse(_strict_fault_receipt(
            [{**door, "messageReplayKey": "c" * 64}, applied], [fault])[3])
        self.assertFalse(_strict_fault_receipt(
            [{**door, "messageParentId": "c" * 64}, applied], [fault])[3])
        validate_plan({"faults": [fault]})
        with self.assertRaisesRegex(ValueError, "message replay identity"):
            validate_plan({"faults": [{**fault, "messageParentId": ""}]})

    def test_static_producer_frontier_is_only_a_site_hint(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "static.jsonl"
            path.write_text("".join(json.dumps({
                "kind": "STATIC_SCOPE_SITE", "role": "DOOR_SITE",
                "regionId": region, "siteId": site}) + "\n" for region, site in (
                    ("producer", "rpc-reply"), ("unrelated", "other-rpc"))))
            graph = {"staticMayRelations": [{
                "kind": "STATIC_STATE", "producerRegionId": "producer",
                "consumerRegionId": "target", "carrier": "key-map"}]}
            self.assertEqual({("producer", "rpc-reply")},
                             _static_producer_frontier_sites(path, graph))
            graph["staticMayRelations"][0]["kind"] = "STATIC_VALUE"
            self.assertEqual({("producer", "rpc-reply")},
                             _static_producer_frontier_sites(path, graph))
            self.assertEqual(set(), _static_producer_frontier_sites(path, {}))

    def test_separate_static_may_sidecar_ranks_observed_door_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "merged-may.jsonl"
            rows = [
                {"role": "TARGET_SITE", "regionId": "target", "siteId": "check"},
                {"role": "STATIC_REGION_METHOD", "regionId": "target",
                 "vmMethod": "targetMethod"},
                {"role": "STATIC_REGION_METHOD", "regionId": "producer",
                 "vmMethod": "producerMethod"},
                {"role": "STATIC_VALUE_EDGE", "producerMethod": "producerMethod",
                 "consumerMethod": "targetMethod", "carrier": "key"},
                {"role": "DOOR_SITE", "regionId": "producer", "siteId": "rpc"},
                {"role": "DOOR_SITE", "regionId": "unrelated", "siteId": "other"},
            ]
            path.write_text("".join(json.dumps({"kind": "STATIC_SCOPE_SITE", **row})
                                    + "\n" for row in rows))
            may = _static_may_sidecar(path, ["check"], set())
            self.assertEqual({"rpc"}, may["door_sites"])
            self.assertEqual({("producer", "rpc")}, may["producer_frontier_sites"])
            self.assertEqual(1, may["relation_count"])
            runtime = [
                {"kind": "FAULT_DOOR", "seq": 2, "siteId": "rpc",
                 "regionId": "producer", "node": "nn#epoch0",
                 "occurrenceId": "unrelated-rpc", "doorOrdinal": 1},
                {"kind": "TARGET_CHECK", "seq": 3, "siteId": "check",
                 "node": "nn#epoch0", "occurrenceId": "target-occ", "outcome": "FALSE"},
            ]
            graph = {**self.graph(), "closureOccurrenceIds": ["target-occ"],
                     "closureOccurrenceCutoffs": {"target-occ": 3},
                     "staticMayObservedDoorSiteIds": []}
            evidence = summarize_evidence(runtime, graph, self.TARGET, [],
                                          {"rpc": "java.io.IOException"},
                                          may["producer_frontier_sites"], may)
            self.assertEqual("static_may_observed",
                             evidence["eligible_doors"][0]["tier"])
            self.assertFalse(evidence["injection_specific_target_reached"])
            self.assertEqual("separate_soot_sidecar",
                             evidence["static_may_ranking_source"])
            self.assertEqual([], graph["staticMayObservedDoorSiteIds"])

    def test_real_hdfs_target_row_shape_is_counted_without_attribution(self):
        # HDFS-29 healthy raw trace has this exact selected TARGET_CHECK
        # shape: the source site executed, but no node/occurrence was set.
        site = ("<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: "
                "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB "
                "getActiveNamenodeForBP(java.lang.String)>#u4")
        target = {"check_site_id": site, "throw_site_id": "throw",
                  "exception_class": "java.io.IOException"}
        graph = {**self.graph(), "targetSite": site, "targetReached": False,
                 "closureOccurrenceIds": [], "closureOccurrenceCutoffs": {}}
        rows = [{"siteId": site, "outcome": "TRUE", "kind": "TARGET_CHECK",
                 "threadKey": "410", "seq": 1186925}]
        evidence = summarize_evidence(rows, graph, target, [])
        self.assertEqual(1, evidence["raw_target_check_rows"])
        self.assertEqual(1, evidence["unattributed_target_check_rows"])
        self.assertEqual(0, evidence["attributed_target_check_rows"])
        self.assertFalse(evidence["target_reached"])

    def test_only_exact_selected_target_rows_contribute_raw_counts(self):
        rows = [
            {"kind": "TARGET_CHECK", "siteId": "other", "seq": 1},
            {"kind": "TARGET_THROW", "siteId": "throw",
             "exceptionClass": "java.lang.IllegalStateException", "seq": 2},
            {"kind": "TARGET_THROW", "siteId": "throw",
             "exceptionClass": "java.io.IOException", "seq": 3},
        ]
        graph = {**self.graph(), "targetReached": False,
                 "closureOccurrenceIds": [], "closureOccurrenceCutoffs": {}}
        evidence = summarize_evidence(rows, graph, self.TARGET, [])
        self.assertEqual(0, evidence["raw_target_check_rows"])
        self.assertEqual(1, evidence["raw_target_throw_rows"])
        self.assertEqual(1, evidence["unattributed_target_throw_rows"])

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

    def test_direct_gzip_graph_archive_keeps_one_compression_layer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scratch = root / "scratch"
            output = root / "trial"
            scratch.mkdir()
            output.mkdir()
            graph = scratch / "graphchecker-graph.jsonl.gz"
            content = b'{"kind":"NODE","occurrenceId":"n1"}\n'
            with gzip.open(graph, "wb") as stream:
                stream.write(content)
            receipt = _archive_jsonl(graph, output)
            self.assertFalse(graph.exists())
            self.assertEqual("graphchecker-graph.jsonl.gz", receipt["path"])
            self.assertEqual(hashlib.sha256(content).hexdigest(),
                             receipt["content_sha256"])
            self.assertEqual(len(content), receipt["content_bytes"])
            self.assertEqual((receipt["content_sha256"], receipt["content_bytes"]),
                             _trace_digest(output / receipt["path"]))

    def test_identical_traces_share_verified_gzip_but_resume_checks_both(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp)
            raw = trial / "graphchecker-raw.jsonl"
            window = trial / "graphchecker-trace.jsonl"
            content = (b'{"kind":"COVERAGE","siteId":"c"}\n' * 1000)
            raw.write_bytes(content)
            window.write_bytes(content)
            with patch("Mallory.core.graphchecker_campaign._trace_digest",
                       wraps=_trace_digest) as digest:
                raw_receipt, window_receipt, shared, timings = _archive_trace_pair(
                    raw, window, trial)
                artifacts = {"raw_trace": raw_receipt, "window_trace": window_receipt}
                result = {"backend": "graphchecker_native",
                          "status": "invalid_graphchecker_trace", "artifacts": artifacts,
                          "raw_trace_sha256": raw_receipt["content_sha256"],
                          "trace_sha256": window_receipt["content_sha256"]}
                stats = {name: _archive_stat(trial / receipt["path"])
                         for name, receipt in artifacts.items()}
                verify_trial_artifacts(trial, result, _fresh_stats=stats)
                # One gzip decompression verifies the one physical archive;
                # the other digest is a plain-source comparison.
                self.assertEqual(1, sum(Path(call.args[0]).suffix == ".gz"
                                        for call in digest.call_args_list))
                verify_trial_artifacts(trial, result)
                self.assertEqual(3, sum(Path(call.args[0]).suffix == ".gz"
                                        for call in digest.call_args_list))
            self.assertTrue(shared)
            self.assertFalse(raw.exists())
            self.assertFalse(window.exists())
            self.assertEqual(raw_receipt["sha256"], window_receipt["sha256"])
            self.assertEqual(raw_receipt["content_sha256"],
                             window_receipt["content_sha256"])
            raw_gzip = trial / raw_receipt["path"]
            window_gzip = trial / window_receipt["path"]
            self.assertEqual(os.stat(raw_gzip).st_ino, os.stat(window_gzip).st_ino)
            self.assertLessEqual(0, timings["archive_raw_trace"])
            self.assertLessEqual(0, timings["window_dedup_check"])
            self.assertLessEqual(0, timings["archive_window_trace"])
            with window_gzip.open("r+b") as stream:
                stream.seek(12)
                stream.write(b"damage")
            with self.assertRaisesRegex(ValueError, "changed raw_trace"):
                verify_trial_artifacts(trial, result)

    def test_distinct_traces_keep_distinct_archives_and_fresh_stat_is_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp)
            raw = trial / "graphchecker-raw.jsonl"
            window = trial / "graphchecker-trace.jsonl"
            raw.write_bytes(b'{"kind":"COVERAGE","seq":1}\n')
            window.write_bytes(b'{"kind":"COVERAGE","seq":2}\n')
            raw_receipt, window_receipt, shared, _ = _archive_trace_pair(
                raw, window, trial)
            self.assertFalse(shared)
            self.assertNotEqual(os.stat(trial / raw_receipt["path"]).st_ino,
                                os.stat(trial / window_receipt["path"]).st_ino)
            result = {"backend": "graphchecker_native",
                      "status": "invalid_graphchecker_trace",
                      "artifacts": {"raw_trace": raw_receipt,
                                    "window_trace": window_receipt},
                      "raw_trace_sha256": raw_receipt["content_sha256"],
                      "trace_sha256": window_receipt["content_sha256"]}
            stats = {name: _archive_stat(trial / receipt["path"])
                     for name, receipt in result["artifacts"].items()}
            verify_trial_artifacts(trial, result, _fresh_stats=stats)
            verify_trial_artifacts(trial, result)
            (trial / window_receipt["path"]).unlink()
            with self.assertRaisesRegex(ValueError, "changed window_trace"):
                verify_trial_artifacts(trial, result, _fresh_stats=stats)

    def test_trace_hardlink_never_replaces_an_existing_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            trial = Path(temp)
            raw = trial / "graphchecker-raw.jsonl"
            window = trial / "graphchecker-trace.jsonl"
            raw.write_bytes(b'{"kind":"TARGET_CHECK"}\n')
            window.write_bytes(raw.read_bytes())
            existing = trial / "graphchecker-trace.jsonl.gz"
            existing.write_bytes(b"other trial evidence")
            with self.assertRaises(FileExistsError):
                _archive_trace_pair(raw, window, trial)
            self.assertEqual(b"other trial evidence", existing.read_bytes())
            self.assertTrue(window.is_file())

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

    def test_compressed_prior_uses_summary_and_plain_prior_remains_supported(self):
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
                if "--capabilities" in command:
                    return subprocess.CompletedProcess(
                        command, 0, b"mallory-healthy-summary-v1\n", b"")
                if "--healthy-summary" in command:
                    self.assertEqual(root / receipt["path"], Path(command[5]))
                    Path(command[6]).write_text(json.dumps({
                        "summaryVersion": 1, "targetSites": ["check"],
                        "nodeFamilies": ["R"], "edgeFamilies": [],
                        "coverageSites": []}))
                else:
                    selected = Path(command[-1])
                    observed.append((selected, selected.read_bytes()))
                    (trial / "graphchecker-feedback.json").write_text(
                        json.dumps({"schemaVersion": 1, "targetSite": "check"}))

            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=fake_run):
                analyze_trial(trial, "check", root / receipt["path"], jar)
            self.assertEqual(trial / "prior.summary.json", observed[0][0])
            summary = json.loads(observed[0][1])
            self.assertEqual(1, summary["summaryVersion"])
            self.assertEqual(["check"], summary["targetSites"])
            self.assertEqual(64, len(summary["priorTraceSha256"]))
            self.assertEqual(64, len(summary["graphJarSha256"]))
            self.assertTrue((root / receipt["path"]).is_file())
            plain = root / "fallback.jsonl"
            plain.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            fallback = root / "fallback-trial"
            fallback.mkdir()
            (fallback / "graphchecker-trace.jsonl").write_text('{}\n')

            def plain_run(command, **_):
                self.assertNotIn("--healthy-summary", command)
                self.assertEqual(plain, Path(command[-1]))
                (fallback / "graphchecker-feedback.json").write_text(
                    json.dumps({"schemaVersion": 1, "targetSite": "check"}))

            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=plain_run):
                analyze_trial(fallback, "check", plain, jar)

    def test_old_graph_jar_uses_private_plain_prior_without_truncating_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "trial"
            trial.mkdir()
            (trial / "graphchecker-trace.jsonl").write_text("{}\n")
            jar = root / "old-graph.jar"
            jar.write_bytes(b"old jar fixture")
            prior = root / "healthy.jsonl"
            prior.write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
            receipt = _archive_jsonl(prior, root)
            archived = root / receipt["path"]
            before = archived.read_bytes()
            commands = []
            plain_inputs = []

            def old_run(command, **_):
                commands.append(command)
                if "--capabilities" in command:
                    return subprocess.CompletedProcess(command, 2, b"", b"usage")
                self.assertEqual(before, archived.read_bytes())
                self.assertNotEqual(archived, Path(command[-1]))
                self.assertEqual(".jsonl", Path(command[-1]).suffix)
                plain_inputs.append(Path(command[-1]))
                self.assertEqual(prior_text, plain_inputs[-1].read_text())
                (trial / "graphchecker-feedback.json").write_text(
                    json.dumps({"schemaVersion": 1, "targetSite": "check"}))
                return subprocess.CompletedProcess(command, 0, b"", b"")

            prior_text = "".join(json.dumps(row) + "\n" for row in self.rows())
            with patch("Mallory.core.graphchecker_trial.subprocess.run",
                       side_effect=old_run):
                analyze_trial(trial, "check", archived, jar)
            self.assertEqual(2, len(commands))
            self.assertEqual("--capabilities", commands[0][-1])
            self.assertFalse(plain_inputs[0].exists())
            self.assertEqual(before, archived.read_bytes())

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
            self.assertIsNone(config["scratch_root"])
            self.assertEqual(6144, config["graph_heap_mb"])
            self.assertFalse(config["graph_output_gzip"])
            raw["graph_output_gzip"] = True
            config_path.write_text(json.dumps(raw))
            self.assertTrue(load_config(config_path)["graph_output_gzip"])
            raw["graph_output_gzip"] = "yes"
            config_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "graph_output_gzip"):
                load_config(config_path)
            raw.pop("graph_output_gzip")
            raw["graph_heap_mb"] = 12288
            config_path.write_text(json.dumps(raw))
            self.assertEqual(12288, load_config(config_path)["graph_heap_mb"])
            raw["graph_heap_mb"] = True
            config_path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "graph_heap_mb"):
                load_config(config_path)
            raw.pop("graph_heap_mb")
            raw["scratch_root"] = str(root)
            config_path.write_text(json.dumps(raw))
            self.assertEqual(root, load_config(config_path)["scratch_root"])
            raw.pop("scratch_root")
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
