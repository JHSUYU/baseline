"""Focused REGION_STATE graph feedback tests, independent of live systems."""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from Mallory.native_graphchecker_feedback.region_state_graph import (
    _closed_inputs, delta_region_state, record_region_state,
    summarize_region_state,
)


SITE = "<example.Keys: void check()>#u7"
TARGET_REGION = "REGION.check"
ACTIVATION = "REGION.targetAct"
RECEIVER = "REGION.receiver"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class RegionStateGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scope = self.root / "scope.jsonl"
        self.graph = self.root / "graph.jsonl.gz"
        self.skeletons = self.root / "regions.jsonl.gz"
        self.engine = self.root / "engine.jar"
        for path in (self.scope, self.graph, self.skeletons, self.engine):
            path.write_text("pinned fixture\n")

    def _case(self, name: str, *, target_actor: str = "nn1",
              new_region: bool = False) -> dict:
        root = self.root / name
        trace = root / "trace"
        trace.mkdir(parents=True)
        (trace / "streaming_trace_manifest.json").write_text(json.dumps({
            "schemaVersion": 2, "kind": "STREAMING_RUNTIME_TRACE",
            "status": "CLOSED", "tracedRows": "fixture-traced-rows"}) + "\n")
        (trace / "schedule.jsonl").write_text("\n")
        source = f"{target_actor}#epoch1"
        occurrence = f"{source}/region/{ACTIVATION}/ctx:fixture"
        rows = [
            {"event": "METHOD_ENTER", "seq": 1, "callId": 10,
             "parentCallId": 0, "sourceKey": source},
            {"event": "METHOD_ENTER", "seq": 2, "callId": 20,
             "parentCallId": 0, "sourceKey": "nn2#epoch0"},
            {"event": "BRANCH", "seq": 3, "callId": 10,
             "siteId": SITE, "outcome": False},
            {"event": "EXCHANGE_SEND", "seq": 4, "callId": 10,
             "sourceKey": source, "transport": "TEST_RPC", "half": "REQUEST",
             "correlationId": "message-1", "attemptId": "1", "spanId": 50,
             "producerEndpoint": f"{source}/region/{ACTIVATION}/site:SEND"},
            {"event": "EXCHANGE_RECEIVE", "seq": 5, "callId": 20,
             "sourceKey": "nn2#epoch0", "transport": "TEST_RPC", "half": "REQUEST",
             "correlationId": "message-1", "attemptId": "1",
             "remoteParentSpanId": 50},
            {"event": "BRANCH", "seq": 6, "callId": 20,
             "siteId": "Receiver#u2", "outcome": True},
        ]
        plans = [
            {"kind": "CONCOLIC_REGION_PLAN", "occurrenceId": occurrence,
             "regionId": ACTIVATION, "sourceKey": source,
             "rootCallId": 10, "foldedRegionIds": [TARGET_REGION]},
            {"kind": "CONCOLIC_REGION_PLAN",
             "occurrenceId": f"nn2#epoch0/region/{RECEIVER}/ctx:fixture",
             "regionId": RECEIVER, "sourceKey": "nn2#epoch0",
             "rootCallId": 20},
        ]
        if new_region:
            rows.extend([
                {"event": "METHOD_ENTER", "seq": 7, "callId": 30,
                 "parentCallId": 0, "sourceKey": "nn3#epoch0"},
                {"event": "BRANCH", "seq": 8, "callId": 30,
                 "siteId": "Recovery#u4", "outcome": True},
            ])
            plans.append({"kind": "CONCOLIC_REGION_PLAN",
                          "occurrenceId": "nn3#epoch0/region/REGION.recovery/ctx:fixture",
                          "regionId": "REGION.recovery", "sourceKey": "nn3#epoch0",
                          "rootCallId": 30})
        write_jsonl(trace / "runtime_trace.jsonl", rows)
        plan = root / "recorded/concolic_region_plan.jsonl"
        write_jsonl(plan, [{"kind": "CONCOLIC_RUNTIME_MODEL_CATALOG",
                           "regions": [], "gaps": []}, *plans])
        events = root / "fault-events.jsonl"
        write_jsonl(events, [{"kind": "TARGET_CHECK", "seq": 1,
                              "siteId": SITE, "node": target_actor,
                              "actorEpochOrdinal": 1,
                              "ordinal": 1,
                              "occurrenceId": "exact-runtime-check"}])
        pins = _closed_inputs(trace, self.scope, self.graph, self.skeletons)
        receipt = root / "target-occurrence.json"
        receipt.write_text(json.dumps({
            "schemaVersion": 1, "kind": "MALLORY_OBSERVED_TARGET_OCCURRENCE",
            "checkSiteId": SITE, "targetRegionId": TARGET_REGION,
            "fatalOutcome": True, "selectedOccurrenceAddress": occurrence,
            "selectedEventSeq": 3, "selectedCallId": 10, **{
                key: pins[key] for key in (
                    "traceManifestSha256", "runtimeTraceSha256", "scheduleSha256",
                    "scopeMapSha256", "candidateGraphSha256",
                    "regionSkeletonsSha256")}}) + "\n")
        return {"trace": trace, "plan": plan, "receipt": receipt,
                "events": events}

    def _summarize(self, case: dict) -> dict:
        return summarize_region_state(
            case["trace"], case["plan"], case["receipt"], case["events"],
            self.scope, self.graph, self.skeletons, SITE,
            engine_jar=self.engine)

    def test_observed_exchange_branch_and_actor_switch_delta(self) -> None:
        healthy = self._summarize(self._case("healthy"))
        fault = self._summarize(self._case("fault", target_actor="nn3",
                                           new_region=True))
        self.assertTrue(healthy["targetReached"])
        self.assertEqual(2, healthy["counts"]["regionPlanRows"])
        self.assertEqual(1, len(healthy["edgeFamilies"]))
        self.assertEqual(1, len(healthy["closureEdgeFamilies"]))
        self.assertIn(f"{SITE}|false", healthy["branchOutcomeIds"])
        delta = delta_region_state(healthy, fault)
        self.assertEqual("compared", delta["status"])
        self.assertTrue(delta["targetRetained"])
        self.assertTrue(delta["targetActorChanged"])
        self.assertIn("nn3/relation/REGION.recovery", delta["newNodeFamilies"])
        self.assertIn("Recovery#u4|true", delta["newBranchOutcomeIds"])

    def test_target_receipt_and_loss_are_fail_closed(self) -> None:
        case = self._case("healthy")
        healthy = self._summarize(case)
        broken = json.loads(case["receipt"].read_text())
        broken["runtimeTraceSha256"] = "changed"
        case["receipt"].write_text(json.dumps(broken) + "\n")
        with self.assertRaisesRegex(ValueError, "input changed"):
            self._summarize(case)
        lost = {"backend": "original_region_state", "targetSiteId": SITE,
                "targetReached": False,
                "provenance": healthy["provenance"]}
        delta = delta_region_state(healthy, lost)
        self.assertEqual("target_lost", delta["status"])
        self.assertEqual([], delta["newNodeFamilies"])

    def test_exact_target_throw_survives_unplanned_resolver_and_absence(self) -> None:
        case = self._case("fatal")
        thrown_site = "<example.Keys: void check()>#u8"
        with case["events"].open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "kind": "TARGET_THROW", "seq": 2, "siteId": thrown_site,
                "exceptionClass": "java.io.IOException", "node": "nn1",
                "actorEpochOrdinal": 1,
                "occurrenceId": "exact-runtime-check"}) + "\n")

        class FailedResolver:
            returncode = 2
            stdout = ""
            stderr = "TARGET_CHECK_NOT_OBSERVED"

        args = dict(test_id="fixture", target_site=SITE,
                    fault_events=case["events"], static_scope_map=self.scope,
                    candidate_graph=self.graph, region_skeletons=self.skeletons,
                    engine_jar=self.engine,
                    target_throw={"siteId": thrown_site,
                                  "exceptionClass": "java.io.IOException"})
        with patch("Mallory.native_graphchecker_feedback.region_state_graph.subprocess.run",
                   return_value=FailedResolver()):
            fatal = record_region_state(case["trace"], self.root / "fatal-graph",
                                        **args)
            self.assertEqual("target_throw_unplanned", fatal["status"])
            self.assertTrue(fatal["targetReached"])
            self.assertTrue(fatal["targetThrowObserved"])
            self.assertEqual("exact-runtime-check", fatal["targetEvidence"][
                "targetCheckOccurrenceIds"][0])
            self.assertEqual([], fatal["nodeFamilies"])

            args["target_throw"] = {"siteId": thrown_site,
                                    "exceptionClass": "java.lang.AssertionError"}
            absent = record_region_state(case["trace"],
                                         self.root / "absent-graph", **args)
            self.assertEqual("target_absent", absent["status"])
            self.assertFalse(absent["targetReached"])

    def test_real_zk07_recordings_if_available(self) -> None:
        base = Path("/dev/shm/mallory-native-zk07-regionfault-v1")
        static = Path("/dev/shm/mallory-zk07-wjtp-fixed-v1/original")
        if not (base / "healthy/graph/recorded/concolic_region_plan.jsonl").is_file():
            self.skipTest("isolated ZK07 recording fixture is unavailable")
        target = "<org.apache.zookeeper.server.quorum.Learner: long registerWithLeader(int)>#u51"
        summaries = {}
        for name, trace in (("healthy", "target/causynth-trace"),
                            ("fault3", "trace")):
            root = base / name
            summaries[name] = summarize_region_state(
                root / trace, root / "graph/recorded/concolic_region_plan.jsonl",
                root / "graph/target-occurrence.json", root / "fault-events.jsonl",
                static / "static_scope_map.jsonl",
                static / "candidate_dataflow_edges.jsonl.gz",
                static / "region_skeletons.jsonl.gz", target)
        delta = delta_region_state(summaries["healthy"], summaries["fault3"])
        self.assertEqual(97, summaries["healthy"]["counts"]["regionPlanRows"])
        self.assertEqual(67, summaries["fault3"]["counts"]["regionPlanRows"])
        self.assertTrue(delta["targetRetained"])
        self.assertGreater(len(delta["newNodeFamilies"]), 0)
        self.assertGreater(len(delta["newClosureEdgeFamilies"]), 0)


if __name__ == "__main__":
    unittest.main()
