"""Focused REGION_STATE graph feedback tests, independent of live systems."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from Mallory.native_graphchecker_feedback.region_state_graph import (
    JAR, _closed_inputs, delta_region_state, record_region_state,
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

    def test_configured_graph_heap_is_used_for_original_resolver(self) -> None:
        case = self._case("heap")
        class FailedResolver:
            returncode = 2
            stdout = ""
            stderr = "TARGET_CHECK_NOT_OBSERVED"
        arguments = dict(test_id="fixture", target_site=SITE,
                         fault_events=case["events"], static_scope_map=self.scope,
                         candidate_graph=self.graph, region_skeletons=self.skeletons,
                         engine_jar=self.engine)
        with patch("Mallory.native_graphchecker_feedback.region_state_graph.subprocess.run",
                   return_value=FailedResolver()):
            record_region_state(case["trace"], self.root / "heap-output",
                                heap_mb=8192, **arguments)
        command = json.loads((self.root / "heap-output/resolver-command.json").read_text())
        self.assertIn("-Xmx8192m", command)
        with self.assertRaisesRegex(ValueError, "bounded heap"):
            record_region_state(case["trace"], self.root / "invalid-heap",
                                heap_mb=0, **arguments)

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
             "producerEndpoint": f"{occurrence}/site:SEND"},
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
        def original_ids(_path, _jar, plans):
            return {("exact-runtime-check" if row["regionId"] == ACTIVATION
                     else "exact-receiver"): row for row in plans}
        with patch("Mallory.native_graphchecker_feedback.region_state_graph."
                   "_plan_identity_rows", side_effect=original_ids):
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
        self.assertEqual("original_runtime_selected_region_finalizer",
                         healthy["closureMembershipAuthority"])
        self.assertEqual(["exact-receiver", "exact-runtime-check"],
                         healthy["closureOccurrenceIds"])
        self.assertIn(f"{SITE}|false", healthy["branchOutcomeIds"])
        delta = delta_region_state(healthy, fault)
        self.assertEqual("compared", delta["status"])
        self.assertTrue(delta["targetRetained"])
        self.assertTrue(delta["targetActorChanged"])
        self.assertIn("nn3/relation/REGION.recovery", delta["newNodeFamilies"])
        self.assertIn("Recovery#u4|true", delta["newBranchOutcomeIds"])

    def test_same_region_family_does_not_admit_different_exact_endpoint(self) -> None:
        case = self._case("different-sender-occurrence")
        trace = case["trace"] / "runtime_trace.jsonl"
        rows = [json.loads(line) for line in trace.read_text().splitlines()]
        send = next(row for row in rows if row["event"] == "EXCHANGE_SEND")
        send["producerEndpoint"] = (
            "nn1#epoch1/region/REGION.targetAct/ctx:another-instance/site:SEND")
        write_jsonl(trace, rows)
        receipt = json.loads(case["receipt"].read_text())
        receipt["runtimeTraceSha256"] = _closed_inputs(
            case["trace"], self.scope, self.graph, self.skeletons)[
                "runtimeTraceSha256"]
        case["receipt"].write_text(json.dumps(receipt) + "\n")
        summary = self._summarize(case)
        self.assertEqual(1, len(summary["edgeFamilies"]))
        self.assertEqual([], summary["closureEdgeFamilies"])

    def test_receive_before_first_method_uses_exact_message_anchor(self) -> None:
        case = self._case("anchored-receive")
        trace_file = case["trace"] / "runtime_trace.jsonl"
        rows = [json.loads(line) for line in trace_file.read_text().splitlines()]
        sent = next(row for row in rows if row.get("event") == "EXCHANGE_SEND")
        received = next(row for row in rows if row.get("event") == "EXCHANGE_RECEIVE")
        plans = [json.loads(line) for line in case["plan"].read_text().splitlines()]
        sent["producerEndpointId"] = "endpoint-1"
        sent["producerEndpoint"] = plans[1]["occurrenceId"] + "/site:SEND"
        received["callId"] = 0  # transport hook ran before the handler entered
        receiver_enter = next(row for row in rows if row.get("event") ==
                              "METHOD_ENTER" and row.get("callId") == 20)
        receiver_branch = next(row for row in rows if row.get("event") ==
                               "BRANCH" and row.get("callId") == 20)
        receiver_enter["seq"] = 6
        receiver_branch["seq"] = 7
        rows.sort(key=lambda row: row["seq"])
        write_jsonl(trace_file, rows)
        plans[2]["occurrenceId"] = (
            f"nn2#epoch0/region/{RECEIVER}/ctx:Anchor:endpoint-1@TEST_RPC/"
            "idx:handler@0")
        write_jsonl(case["plan"], plans)
        receipt = json.loads(case["receipt"].read_text())
        receipt.update(_closed_inputs(case["trace"], self.scope, self.graph,
                                      self.skeletons))
        case["receipt"].write_text(json.dumps(receipt) + "\n")

        summary = self._summarize(case)
        self.assertEqual(1, summary["counts"]["pairedExchangeEvents"])
        self.assertEqual(1, summary["counts"]["anchorMappedPairedExchanges"])
        self.assertEqual(0, summary["counts"]["unmappedPairedExchanges"])
        self.assertEqual(1, len(summary["edgeFamilies"]))

        plans[2]["occurrenceId"] = plans[2]["occurrenceId"].replace(
            "Anchor:endpoint-1@", "Anchor:another-endpoint@")
        write_jsonl(case["plan"], plans)
        mismatched = self._summarize(case)
        self.assertEqual(0, mismatched["counts"]["anchorMappedPairedExchanges"])
        self.assertEqual(1, mismatched["counts"]["unmappedPairedExchanges"])
        self.assertEqual([], mismatched["edgeFamilies"])

        plans[2]["occurrenceId"] = plans[2]["occurrenceId"].replace(
            "Anchor:another-endpoint@", "Anchor:endpoint-1@")
        write_jsonl(case["plan"], plans)
        sent["producerEndpoint"] = (
            "nn1#epoch1/region/ROLE.TRANSPORT/ctx:Root:fixture/site:SEND")
        write_jsonl(trace_file, rows)
        receipt = json.loads(case["receipt"].read_text())
        receipt.update(_closed_inputs(case["trace"], self.scope, self.graph,
                                      self.skeletons))
        case["receipt"].write_text(json.dumps(receipt) + "\n")
        role_only = self._summarize(case)
        self.assertEqual(0, role_only["counts"]["anchorMappedPairedExchanges"])
        self.assertEqual(1, role_only["counts"]["unmappedPairedExchanges"])
        self.assertEqual([], role_only["edgeFamilies"])

        # A valid original GraphChecker ROLE address is an ambient causal
        # context, not a static REGION. Its transported endpoint can lead to
        # an exactly anchored selected receiver without admitting the sender
        # as a member of the target's Finalizer closure.
        sent["producerEndpoint"] = (
            "nn1#epoch1/region/ROLE.TRANSPORT/ctx:Root:fixture/idx:send@0/site:SEND")
        write_jsonl(trace_file, rows)
        receipt = json.loads(case["receipt"].read_text())
        receipt.update(_closed_inputs(case["trace"], self.scope, self.graph,
                                      self.skeletons))
        case["receipt"].write_text(json.dumps(receipt) + "\n")
        role_context = self._summarize(case)
        self.assertEqual(1, role_context["counts"]["contextBoundaryPairedExchanges"])
        self.assertEqual(1, role_context["counts"]["unmappedPairedExchanges"])
        self.assertEqual([
            "TEST_RPC|REQUEST|nn1/context/ROLE.TRANSPORT->nn2/relation/REGION.receiver"
        ], role_context["contextBoundaryEdgeFamilies"])
        self.assertEqual([], role_context["edgeFamilies"])
        self.assertEqual([], role_context["closureEdgeFamilies"])
        self.assertEqual(1, len(delta_region_state(role_only, role_context)[
            "newContextBoundaryEdgeFamilies"]))
        legacy_healthy = dict(role_only)
        legacy_healthy.pop("contextBoundaryEdgeFamilies")
        self.assertEqual([], delta_region_state(legacy_healthy, role_context)[
            "newContextBoundaryEdgeFamilies"])

        sent["producerEndpoint"] = sent["producerEndpoint"].replace(
            "nn1#epoch1/", "another#epoch0/")
        write_jsonl(trace_file, rows)
        receipt = json.loads(case["receipt"].read_text())
        receipt.update(_closed_inputs(case["trace"], self.scope, self.graph,
                                      self.skeletons))
        case["receipt"].write_text(json.dumps(receipt) + "\n")
        wrong_source = self._summarize(case)
        self.assertEqual([], wrong_source["contextBoundaryEdgeFamilies"])

        sent["producerEndpoint"] = sent["producerEndpoint"].replace(
            "another#epoch0/", "nn1#epoch1/")
        plans[2]["occurrenceId"] = plans[2]["occurrenceId"].replace(
            "@TEST_RPC/", "@OTHER_RPC/")
        write_jsonl(case["plan"], plans)
        wrong_transport = self._summarize(case)
        self.assertEqual([], wrong_transport["contextBoundaryEdgeFamilies"])

        plans[2]["occurrenceId"] = plans[2]["occurrenceId"].replace(
            "@OTHER_RPC/", "@TEST_RPC/")
        write_jsonl(case["plan"], plans)
        rows.append({**sent, "seq": 8, "correlationId": "another-message",
                     "spanId": 51})
        write_jsonl(trace_file, rows)
        receipt = json.loads(case["receipt"].read_text())
        receipt.update(_closed_inputs(case["trace"], self.scope, self.graph,
                                      self.skeletons))
        case["receipt"].write_text(json.dumps(receipt) + "\n")
        reused_endpoint = self._summarize(case)
        self.assertEqual([], reused_endpoint["contextBoundaryEdgeFamilies"])

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

    def test_frozen_role_boundary_recordings_if_available(self) -> None:
        # The static sidecars were in /dev/shm and have been retired. Check
        # the saved Recorder pins and exact plan rows before reusing their
        # attested digests; no resolver, JUnit, or campaign process runs.
        runs = (
            ("SOLR-09", Path("/proj/silentfailure-PG0/mallory/solr09-native-prep-v1/campaign-prep/campaign/trials/r0000"), 5, 7, 5, 5, 17),
            ("SOLR-07", Path("/proj/silentfailure-PG0/mallory/solr07-native-prep-v1/campaign-prep/campaign/trials/r0000"), 21, 19, 17, 15, 129),
            ("HBASE-01", Path("/proj/silentfailure-PG0/ZhenyuLi/Mallory/HBASE-01-20261014-native-v5/campaign/trials/r0000"), 0, 0, 0, 0, 258),
        )
        if not all((root / "original-graph/summary.json").is_file()
                   for _, root, _, _, _, _, _ in runs):
            self.skipTest("frozen native recordings are unavailable")

        def digest(path: Path) -> str:
            result = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    result.update(block)
            return result.hexdigest()

        for (name, root, expected_pairs, expected_families, region_edges,
             closure_edges, legacy_unmapped) in runs:
            with self.subTest(name=name):
                graph_dir = root / "original-graph"
                original = json.loads((graph_dir / "summary.json").read_text())
                pins = original["provenance"]
                plan_path = graph_dir / "recorded/concolic_region_plan.jsonl"
                receipt = graph_dir / "target-occurrence.json"
                events = root / "iteration-native/fault-events.jsonl"
                trace = root / "iteration-native/trace"
                command = json.loads((graph_dir / "recorder-command.json").read_text())
                engine = Path(command[4].split(":", 1)[0])
                if not engine.is_file():
                    self.skipTest("frozen original engine is unavailable")
                for key, path in (
                    ("regionPlanSha256", plan_path),
                    ("runtimeTraceSha256", trace / "runtime_trace.jsonl"),
                    ("traceManifestSha256", trace / "streaming_trace_manifest.json"),
                    ("targetReceiptSha256", receipt),
                    ("faultEventsSha256", events),
                    ("engineJarSha256", engine),
                ):
                    self.assertEqual(pins[key], digest(path), (name, key))
                receipt_row = json.loads(receipt.read_text())
                selected_address = receipt_row["selectedOccurrenceAddress"]
                selected_id = original["targetEvidence"]["targetCheckOccurrenceIds"][0]
                recorded_ids = {row["occurrenceAddress"]: row["occurrenceId"]
                                for row in original.get("closureMembers", [])}

                def original_ids(_path, _jar, plans):
                    if recorded_ids:
                        self.assertEqual({p["occurrenceId"] for p in plans},
                                         set(recorded_ids))
                        return {recorded_ids[p["occurrenceId"]]: p for p in plans}
                    # Older frozen summaries predate ID publication. Only
                    # the selected target ID participates in this read-only
                    # summary; unrelated IDs need unique placeholders.
                    return {selected_id if p["occurrenceId"] == selected_address
                            else f"offline-{i}": p for i, p in enumerate(plans)}

                closed = {key: pins[key] for key in (
                    "traceManifestSha256", "runtimeTraceSha256", "scheduleSha256",
                    "scopeMapSha256", "candidateGraphSha256",
                    "regionSkeletonsSha256", "tracedRowsDigest")}
                with patch("Mallory.native_graphchecker_feedback.region_state_graph."
                           "_closed_inputs", return_value=closed), patch(
                           "Mallory.native_graphchecker_feedback.region_state_graph."
                           "_plan_identity_rows", side_effect=original_ids):
                    refreshed = summarize_region_state(
                        trace, plan_path, receipt, events, receipt, receipt,
                        receipt, original["targetSiteId"], engine_jar=engine)
                self.assertEqual(expected_pairs, refreshed["counts"][
                    "contextBoundaryPairedExchanges"])
                self.assertEqual(expected_families, len(refreshed[
                    "contextBoundaryEdgeFamilies"]))
                self.assertEqual(region_edges, len(refreshed["edgeFamilies"]))
                self.assertEqual(closure_edges, len(refreshed["closureEdgeFamilies"]))
                self.assertEqual(legacy_unmapped, refreshed["counts"][
                    "unmappedPairedExchanges"])
                self.assertEqual(original["nodeFamilies"], refreshed["nodeFamilies"])
                self.assertEqual(original["branchOutcomeIds"], refreshed[
                    "branchOutcomeIds"])

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
        if not ((base / "healthy/graph/recorded/concolic_region_plan.jsonl").is_file()
                and JAR.is_file()):
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
        self.assertGreater(len(delta["newEdgeFamilies"]), 0)
        self.assertGreater(len(delta["newBranchOutcomeIds"]), 0)


if __name__ == "__main__":
    unittest.main()
