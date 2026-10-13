"""Small contract tests plus an opt-in unchanged-JUnit native integration test."""

from __future__ import annotations

import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from Mallory.native_graphchecker_feedback.feedback import (
    ENGINE, HERE, NoNativeTargetError, _classpath, _scope_digest, build, delta,
    list_native_targets, summarize, summarize_target_set,
)


def summary() -> dict:
    return {
        "schemaVersion": 1,
        "method": "original-graphchecker-corpus-closureplanner",
        "engineJarSha256": "pinned-source-build",
        "staticScopeMapSha256": "scope-pinned",
        "bridgeSourceSha256": "bridge-pinned",
        "maxTasks": 256,
        "targetSiteId": "T#1",
        "targetOccurrenceId": "exact-actor-target",
        "targetFamily": "T#1\ndn0\nREGION.target",
        "targetRegionId": "REGION.target",
        "targetRows": [{"occurrenceId": "exact-actor-target"}],
        "closureMembers": [{"occurrenceId": "exact-actor-target",
                            "family": "dn0#epoch0\nREGION.target"}],
        "observedEdgesWithinClosure": [],
        "branchCoverage": ["check#u1\nfalse"],
        "gaps": [], "truncated": [],
    }


class DeltaTest(unittest.TestCase):
    def test_only_exact_target_closure_novelty_counts(self) -> None:
        healthy = summary()
        trial = copy.deepcopy(healthy)
        trial["closureMembers"].append({"occurrenceId": "exact-upstream",
                                         "family": "nn0#epoch0\nREGION.upstream"})
        trial["observedEdgesWithinClosure"].append({
            "type": "WIRE", "family": "WIRE\nport\nupstream\ntarget",
            "producerOccurrenceId": "exact-upstream",
            "consumerOccurrenceId": "exact-actor-target",
            "evidence": {"producerEndpointId": "exact-endpoint"}})
        trial["branchCoverage"].append("check#u1\ntrue")
        feedback = delta(healthy, trial)
        self.assertEqual(1, feedback["newClosureNodes"])
        self.assertEqual(1, feedback["newObservedClosureEdges"])
        self.assertEqual(1, feedback["newClosureBranchOutcomes"])

    def test_unchanged_native_session_has_zero_delta(self) -> None:
        healthy = summary()
        self.assertEqual(0, delta(healthy, copy.deepcopy(healthy))[
            "newObservedClosureEdges"])

    def test_missing_or_shifted_target_fails_closed(self) -> None:
        healthy = summary()
        trial = copy.deepcopy(healthy)
        trial["targetRows"] = []
        with self.assertRaisesRegex(ValueError, "exact target row"):
            delta(healthy, trial)
        trial = copy.deepcopy(healthy)
        trial["targetOccurrenceId"] = "other-request"
        with self.assertRaisesRegex(ValueError, "exact target row"):
            delta(healthy, trial)

    def test_cross_run_occurrence_shift_keeps_each_run_exact(self) -> None:
        healthy = summary()
        trial = copy.deepcopy(healthy)
        trial["targetOccurrenceId"] = "same-actor-after-reboot"
        trial["targetRows"][0]["occurrenceId"] = "same-actor-after-reboot"
        trial["closureMembers"][0]["occurrenceId"] = "same-actor-after-reboot"
        feedback = delta(healthy, trial)
        self.assertEqual(["exact-actor-target"],
                         feedback["healthyTargetOccurrenceIds"])
        self.assertEqual(["same-actor-after-reboot"],
                         feedback["trialTargetOccurrenceIds"])
        self.assertEqual(0, feedback["newClosureNodes"])

    def test_different_engine_or_static_only_edge_fails_closed(self) -> None:
        healthy = summary()
        trial = copy.deepcopy(healthy)
        trial["engineJarSha256"] = "different-engine"
        with self.assertRaisesRegex(ValueError, "engineJarSha256"):
            delta(healthy, trial)
        trial = copy.deepcopy(healthy)
        trial["observedEdgesWithinClosure"] = [
            {"type": "STATIC_CANDIDATE_WRITER"}]
        with self.assertRaisesRegex(ValueError, "invalid observedEdges"):
            delta(healthy, trial)


class NativeUnmodifiedJUnitIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("GC_NATIVE_FIXTURE"),
                         "set GC_NATIVE_FIXTURE to the unchanged-JUnit scratch root")
    def test_source_built_session_reader_and_original_closure(self) -> None:
        fixture = Path(os.environ["GC_NATIVE_FIXTURE"])
        sessions = list((fixture / "sessions").glob("*/targets.jsonl"))
        self.assertEqual(1, len(sessions))
        target = json.loads(sessions[0].read_text(encoding="utf-8").splitlines()[0])
        site = target["anchorSiteId"]
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        with tempfile.TemporaryDirectory() as scratch:
            result = summarize(fixture, site, Path(scratch) / "summary.json",
                               static_scope_map=fixture / "static_scope_map.jsonl",
                               engine_jar=engine_jar)
            replay = fixture / "replay-root"
            if replay.is_dir():
                repeated = summarize(replay, site,
                                     Path(scratch) / "replay-summary.json",
                                     static_scope_map=fixture / "static_scope_map.jsonl",
                                     engine_jar=engine_jar)
                self.assertEqual(0, delta(result, repeated)["newClosureNodes"])
                baseline_set = summarize_target_set(
                    fixture, site, Path(scratch) / "baseline-set.json",
                    static_scope_map=fixture / "static_scope_map.jsonl",
                    engine_jar=engine_jar)
                replay_set = summarize_target_set(
                    replay, site, Path(scratch) / "replay-set.json",
                    static_scope_map=fixture / "static_scope_map.jsonl",
                    engine_jar=engine_jar)
                self.assertEqual(1, len(baseline_set["perTargetOccurrences"]))
                self.assertEqual(0, delta(baseline_set, replay_set)[
                    "newObservedClosureEdges"])
        self.assertEqual("original-graphchecker-corpus-closureplanner",
                         result["method"])
        self.assertEqual(site, result["targetSiteId"])
        self.assertTrue(any(row["occurrenceId"] == result["targetOccurrenceId"]
                            for row in result["closureMembers"]))
        self.assertGreaterEqual(len(result["branchObservationsWithinClosure"]), 1)
        self.assertEqual(0, delta(result, result)["newClosureBranchOutcomes"])
        # This fixture has one native WRITE but no standalone READ; an exact
        # write/read state edge cannot be asserted from the expression alone.
        self.assertFalse(any(edge["type"] == "STATE"
                             for edge in result["observedEdgesWithinClosure"]))


@unittest.skipUnless((ENGINE / "target" /
                      "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar").is_file(),
                     "build Mallory original GraphChecker engine first")
class NativeTypedEdgeIntegrationTest(unittest.TestCase):
    def test_source_built_closure_uses_exact_wire_state_and_start_rows(self) -> None:
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        classes = build(engine_jar=engine_jar)
        classpath = f"{classes}:{_classpath(engine_jar)}"
        subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                        str(HERE / "SyntheticNativeSession.java")], check=True,
                       timeout=120, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            full = root / "full"
            missing = root / "missing"
            generator = ["java", "-cp", classpath,
                         "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession"]
            subprocess.run(generator + [str(full)], check=True, timeout=30)
            subprocess.run(generator + [str(missing),
                                        "--missing-handoff-expression"],
                           check=True, timeout=30)
            complete = summarize(full, "Keys#check#u3", root / "full.json",
                                 static_scope_map=full / "static_scope_map.jsonl",
                                 engine_jar=engine_jar)
            withheld = summarize(missing, "Keys#check#u3",
                                 root / "missing.json",
                                 exact_occurrence_id=complete["targetOccurrenceId"],
                                 static_scope_map=missing / "static_scope_map.jsonl",
                                 engine_jar=engine_jar)
        self.assertEqual({"R.target", "R.writer", "R.sender"},
                         {item["regionId"] for item in complete["closureMembers"]})
        self.assertEqual({"WIRE", "STATE", "MESSAGE_START"},
                         {item["type"] for item in
                          complete["observedEdgesWithinClosure"]})
        self.assertEqual({"STATE"},
                         {item["type"] for item in
                          withheld["observedEdgesWithinClosure"]})
        self.assertEqual({"R.target", "R.writer"},
                         {item["regionId"] for item in withheld["closureMembers"]})

    def test_target_set_keeps_distinct_native_occurrences(self) -> None:
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        classes = build(engine_jar=engine_jar)
        classpath = f"{classes}:{_classpath(engine_jar)}"
        subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                        str(HERE / "SyntheticNativeSession.java")], check=True,
                       timeout=120, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        generator = ["java", "-cp", classpath,
                     "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession"]
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            single = root / "single"
            pair = root / "pair"
            subprocess.run(generator + [str(single)], check=True, timeout=30)
            subprocess.run(generator + [str(pair), "--second-target"],
                           check=True, timeout=30)
            listed = list_native_targets(pair, "Keys#check#u3",
                                         engine_jar=engine_jar)
            healthy = summarize_target_set(
                single, "Keys#check#u3", root / "healthy.json",
                static_scope_map=single / "static_scope_map.jsonl",
                engine_jar=engine_jar)
            trial = summarize_target_set(
                pair, "Keys#check#u3", root / "trial.json",
                static_scope_map=pair / "static_scope_map.jsonl",
                engine_jar=engine_jar)
        self.assertEqual(2, len(listed))
        self.assertEqual({item["occurrenceId"] for item in listed},
                         set(trial["targetOccurrenceIds"]))
        self.assertEqual(2, len(trial["perTargetOccurrences"]))
        for one in trial["perTargetOccurrences"]:
            self.assertTrue(any(row["occurrenceId"] == one["targetOccurrenceId"]
                                for row in one["closureMembers"]))
        feedback = delta(healthy, trial)
        self.assertTrue(feedback["targetSetMode"])
        self.assertEqual(1, feedback["newClosureNodes"])
        self.assertEqual(2, len(feedback["trialTargetOccurrenceIds"]))
        missing_pin = copy.deepcopy(trial)
        missing_pin.pop("staticScopeBundleSha256")
        with self.assertRaisesRegex(ValueError, "staticScopeBundleSha256"):
            delta(healthy, missing_pin)

    def test_one_pass_target_set_equals_separate_exact_plans(self) -> None:
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        classes = build(engine_jar=engine_jar)
        classpath = f"{classes}:{_classpath(engine_jar)}"
        subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                        str(HERE / "SyntheticNativeSession.java")], check=True,
                       timeout=120, capture_output=True)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            pair = root / "pair"
            subprocess.run(["java", "-cp", classpath,
                            "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                            str(pair), "--second-target"], check=True,
                           timeout=30, capture_output=True)
            targets = list_native_targets(pair, "Keys#check#u3",
                                          engine_jar=engine_jar)
            with patch("Mallory.native_graphchecker_feedback.feedback.subprocess.run",
                       wraps=subprocess.run) as invoked:
                combined = summarize_target_set(
                    pair, "Keys#check#u3", root / "combined.json",
                    static_scope_map=pair / "static_scope_map.jsonl",
                    engine_jar=engine_jar)
            java_calls = [call.args[0] for call in invoked.call_args_list
                          if call.args and isinstance(call.args[0], list)
                          and "edu.uva.liftlab.mallory.nativefeedback.NativeFeedbackMain"
                          in call.args[0]]
            self.assertEqual(1, len(java_calls))
            self.assertIn("--target-set", java_calls[0])
            for target in targets:
                separate = summarize(
                    pair, "Keys#check#u3", root / (target["nodeName"] + ".json"),
                    exact_occurrence_id=target["occurrenceId"],
                    static_scope_map=pair / "static_scope_map.jsonl",
                    engine_jar=engine_jar)
                from_set = next(item for item in combined["perTargetOccurrences"]
                                if item["targetOccurrenceId"] == target["occurrenceId"])
                self.assertEqual(separate, from_set)
            filtered = summarize_target_set(
                pair, "Keys#check#u3", root / "filtered.json",
                static_scope_map=pair / "static_scope_map.jsonl",
                actor_names={"dn2"}, engine_jar=engine_jar)
            self.assertEqual(1, len(filtered["perTargetOccurrences"]))
            self.assertEqual("dn2", filtered["perTargetOccurrences"][0]["targetNodeName"])
            with self.assertRaises(NoNativeTargetError):
                summarize_target_set(
                    pair, "Keys#check#u3", root / "absent.json",
                    static_scope_map=pair / "static_scope_map.jsonl",
                    actor_names={"missing"}, engine_jar=engine_jar)

    def test_mixed_target_reach_keeps_only_reached_closure(self) -> None:
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        classes = build(engine_jar=engine_jar)
        classpath = f"{classes}:{_classpath(engine_jar)}"
        subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                        str(HERE / "SyntheticNativeSession.java")], check=True,
                       timeout=120, capture_output=True)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            pair = root / "mixed"
            subprocess.run(["java", "-cp", classpath,
                            "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                            str(pair), "--second-target-unreached"], check=True,
                           timeout=30, capture_output=True)
            result = summarize_target_set(
                pair, "Keys#check#u3", root / "mixed.json",
                static_scope_map=pair / "static_scope_map.jsonl",
                engine_jar=engine_jar)
            self.assertEqual(1, len(result["perTargetOccurrences"]))
            self.assertEqual("dn", result["perTargetOccurrences"][0]["targetNodeName"])
            self.assertEqual(1, len(result["unreachedTargetRows"]))
            self.assertNotIn(result["unreachedTargetRows"][0]["occurrenceId"],
                             result["targetOccurrenceIds"])
            with self.assertRaises(NoNativeTargetError) as excluded:
                summarize_target_set(
                    pair, "Keys#check#u3", root / "excluded.json",
                    static_scope_map=pair / "static_scope_map.jsonl",
                    actor_names={"dn2"}, engine_jar=engine_jar)
            self.assertTrue(excluded.exception.site_target_rows_seen)
            alone = root / "alone"
            subprocess.run(["java", "-cp", classpath,
                            "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                            str(alone), "--unreached-target"], check=True,
                           timeout=30, capture_output=True)
            with self.assertRaises(NoNativeTargetError) as no_reach:
                summarize_target_set(
                    alone, "Keys#check#u3", root / "alone.json",
                    static_scope_map=alone / "static_scope_map.jsonl",
                    engine_jar=engine_jar)
            self.assertTrue(no_reach.exception.site_target_rows_seen)

    def test_gzipped_static_scope_preserves_plain_native_session_feedback(self) -> None:
        engine_jar = (Path(os.environ["GC_NATIVE_ENGINE_JAR"])
                      if os.environ.get("GC_NATIVE_ENGINE_JAR") else None)
        classes = build(engine_jar=engine_jar)
        classpath = f"{classes}:{_classpath(engine_jar)}"
        subprocess.run(["javac", "-cp", classpath, "-d", str(classes),
                        str(HERE / "SyntheticNativeSession.java")], check=True,
                       timeout=120, capture_output=True)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            pair = root / "pair"
            subprocess.run(["java", "-cp", classpath,
                            "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                            str(pair), "--second-target"], check=True,
                           timeout=30, capture_output=True)
            plain = pair / "static_scope_map.jsonl"
            zipped = pair / "static_scope_map.jsonl.gz"
            with gzip.open(zipped, "wb") as stream:
                stream.write(plain.read_bytes())
            skeleton = pair / "region_skeletons.jsonl.gz"
            with gzip.open(skeleton, "wb") as stream:
                stream.write(b'{"regionId":"R.target","methods":[]}\n')
            first_scope_digest = _scope_digest(plain)
            baseline = summarize_target_set(
                pair, "Keys#check#u3", root / "plain.json",
                static_scope_map=plain, engine_jar=engine_jar)
            compressed = summarize_target_set(
                pair, "Keys#check#u3", root / "gzip.json",
                static_scope_map=zipped, engine_jar=engine_jar)
            for name in ("closureMembers", "observedEdgesWithinClosure",
                         "branchCoverage", "targetOccurrenceIds", "targetRows"):
                self.assertEqual(baseline[name], compressed[name])
            self.assertNotEqual(baseline["staticScopeMapSha256"],
                                compressed["staticScopeMapSha256"])
            with gzip.open(skeleton, "wb") as stream:
                stream.write(b'{"regionId":"R.target","methods":["changed"]}\n')
            self.assertNotEqual(first_scope_digest, _scope_digest(plain))


if __name__ == "__main__":
    unittest.main()
