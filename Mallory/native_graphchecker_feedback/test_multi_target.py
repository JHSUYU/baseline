"""Small, deterministic repeated-target selection and recording fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from Mallory.native_graphchecker_feedback.multi_target import (
    delta_matching_anchors, record_multiple_region_states,
    record_pinned_region_states,
    select_target_occurrences,
)


def receipt(count: int = 75) -> dict:
    return {"schemaVersion": 1,
            "kind": "MALLORY_OBSERVED_TARGET_OCCURRENCE",
            "checkSiteId": "<Example: void check()>#u7",
            "fatalOutcome": True,
            "distinctReachedOccurrenceCount": count,
            "reachedEvents": [{"eventSeq": 10 * (index + 1),
                               "sourceKey": f"n{index % 3}#epoch0",
                               "occurrenceAddress": f"target-{index:02d}",
                               "observedOutcome": False}
                              for index in range(count)]}


class MultiTargetTest(unittest.TestCase):
    def test_initial_quantiles_and_rotation_span_repeated_activations(self) -> None:
        observed = receipt()
        first = select_target_occurrences(observed)
        self.assertEqual(["target-00", "target-25", "target-49", "target-74"],
                         [row["occurrenceAddress"] for row in first])
        seen = {row["occurrenceAddress"] for round_index in range(75)
                for row in select_target_occurrences(
                    observed, round_index=round_index)}
        self.assertEqual(75, len(seen))
        self.assertEqual(first, select_target_occurrences(observed))

    def test_only_exact_finalizer_graph_and_same_clock_typed_door_rank(self) -> None:
        observed = receipt()
        graph = {"closureMembershipAuthority":
                 "original_runtime_selected_region_finalizer",
                 "targetEvidence": {"selectedOccurrenceAddress": "target-02"},
                 "closureOccurrenceIds": ["a", "b"]}
        first = select_target_occurrences(observed, prior_graphs={
            "target-02": graph})
        self.assertEqual("target-02", first[0]["occurrenceAddress"])
        bad = dict(graph, targetEvidence={
            "selectedOccurrenceAddress": "some-other-target"})
        self.assertEqual("target-00", select_target_occurrences(
            observed, prior_graphs={"target-02": bad})[0]["occurrenceAddress"])
        door = {"kind": "FAULT_DOOR", "siteId": "<Rpc: void send()>#u1",
                "exceptionClass": "java.io.IOException", "node": "n2",
                "actorEpochOrdinal": 0, "nativeVmEventId": 29}
        self.assertEqual("target-02", select_target_occurrences(
            observed, typed_doors=[door])[0]["occurrenceAddress"])
        # A receipt sequence cannot substitute for a native VM event clock.
        door.pop("nativeVmEventId")
        door["seq"] = 29
        self.assertEqual("target-00", select_target_occurrences(
            observed, typed_doors=[door])[0]["occurrenceAddress"])

    def test_fail_closed_on_invalid_receipt_or_budget(self) -> None:
        observed = receipt(2)
        observed["reachedEvents"][0]["observedOutcome"] = True
        with self.assertRaisesRegex(ValueError, "fatal"):
            select_target_occurrences(observed)
        with self.assertRaisesRegex(ValueError, "bounded"):
            select_target_occurrences(receipt(), max_anchors=17)
        observed = receipt(2)
        observed["distinctReachedOccurrenceCount"] = 1
        with self.assertRaisesRegex(ValueError, "count differs"):
            select_target_occurrences(observed)

    def test_small_closed_fixture_runs_each_exact_graph_and_pins_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "fault-events.jsonl"
            events.write_text("", encoding="utf-8")
            calls = []

            def original_graph(_trace, output, **arguments):
                output.mkdir(parents=True)
                address = arguments.get("target_occurrence")
                calls.append(address)
                if address is None:
                    (output / "target-occurrence.json").write_text(
                        json.dumps(receipt(5)), encoding="utf-8")
                    summary = {"status": "target_reached", "targetReached": True}
                else:
                    (output / "target-occurrence.json").write_text(json.dumps({
                        "requestedOccurrenceAddress": address,
                        "selectedOccurrenceAddress": address}),
                        encoding="utf-8")
                    summary = {"status": "target_reached", "targetReached": True,
                               "closureMembershipAuthority":
                               "original_runtime_selected_region_finalizer",
                               "targetEvidence": {
                                   "selectedOccurrenceAddress": address},
                               "closureOccurrenceIds": [address]}
                (output / "summary.json").write_text(json.dumps(summary),
                                                      encoding="utf-8")
                return summary

            with patch("Mallory.native_graphchecker_feedback.multi_target."
                       "record_region_state", side_effect=original_graph):
                bundle = record_multiple_region_states(root, root / "graphs",
                    fault_events=events, max_anchors=3)
            self.assertEqual([None, "target-00", "target-02", "target-04"],
                             calls)
            self.assertEqual(3, len(bundle["anchors"]))
            self.assertTrue(all(len(row["summarySha256"]) == 64 and
                                len(row["targetReceiptSha256"]) == 64
                                for row in bundle["anchors"]))

    def test_cross_anchor_delta_is_never_compared(self) -> None:
        a = {"occurrenceAddress": "a", "targetReached": True,
             "summary": {"id": "healthy-a", "targetReached": True,
                         "closureMembershipAuthority":
                         "original_runtime_selected_region_finalizer",
                         "targetEvidence": {"selectedOccurrenceAddress": "a"}}}
        b = {"occurrenceAddress": "b", "targetReached": True,
             "summary": {"id": "fault-b", "targetReached": True,
                         "closureMembershipAuthority":
                         "original_runtime_selected_region_finalizer",
                         "targetEvidence": {"selectedOccurrenceAddress": "b"}}}
        with patch("Mallory.native_graphchecker_feedback.multi_target."
                   "delta_region_state") as delta:
            self.assertEqual({}, delta_matching_anchors(
                {"anchors": [a]}, {"anchors": [b]}))
            delta.assert_not_called()
            delta.return_value = {"newClosureEdgeFamilies": ["edge"]}
            self.assertEqual({"a": delta.return_value}, delta_matching_anchors(
                {"anchors": [a]}, {"anchors": [a]}))
            delta.assert_called_once_with(a["summary"], a["summary"])

    def test_raw_exact_oracle_is_independent_of_graph_absence(self) -> None:
        from Mallory.native_graphchecker_campaign.campaign import (
            _target_throw_observations,
        )
        target_site = "<Example: void check()>#u7"
        target_throw = {"siteId": "<Example: void check()>#u8",
                        "exceptionClass": "java.io.IOException"}
        rows = [{"kind": "FAULT_APPLIED", "seq": 1,
                 "node": "client", "actorEpochOrdinal": 0,
                 "occurrenceId": "fault"},
                {"kind": "TARGET_CHECK", "seq": 2,
                 "siteId": target_site, "node": "dn0",
                 "actorEpochOrdinal": 0, "occurrenceId": "exact-check"},
                {"kind": "TARGET_THROW", "seq": 3,
                 "siteId": target_throw["siteId"],
                 "exceptionClass": target_throw["exceptionClass"],
                 "node": "dn0", "actorEpochOrdinal": 0,
                 "occurrenceId": "exact-check"}]
        # campaign._run_trial invokes this existing oracle before graphs.
        raw = _target_throw_observations(rows, target_site, target_throw)
        self.assertEqual(1, len(raw))
        self.assertEqual("exact-check", raw[0]["occurrenceId"])
        self.assertEqual([], _target_throw_observations(
            rows[:2], target_site, target_throw))

    def test_missing_exact_occurrence_requests_retry_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "events.jsonl"
            events.write_text("", encoding="utf-8")
            calls = []

            def graph(_trace, output, **arguments):
                output.mkdir(parents=True)
                address = arguments.get("target_occurrence")
                calls.append(address)
                if address is None:
                    (output / "target-occurrence.json").write_text(
                        json.dumps(receipt(3)), encoding="utf-8")
                elif address != "target-01":
                    (output / "target-occurrence.json").write_text(json.dumps({
                        "requestedOccurrenceAddress": address,
                        "selectedOccurrenceAddress": address}),
                        encoding="utf-8")
                summary = {"status": "target_absent" if address == "target-01"
                           else "target_reached",
                           "targetReached": address != "target-01",
                           "closureMembershipAuthority":
                           "original_runtime_selected_region_finalizer",
                           "targetEvidence": {
                               "selectedOccurrenceAddress": address}}
                (output / "summary.json").write_text(json.dumps(summary),
                                                      encoding="utf-8")
                return summary

            with patch("Mallory.native_graphchecker_feedback.multi_target."
                       "record_region_state", side_effect=graph):
                bundle = record_multiple_region_states(root, root / "graphs",
                    fault_events=events, max_anchors=3)
            self.assertEqual([None, "target-00", "target-01", "target-02"], calls)
            self.assertEqual(["target-01"], bundle["retryExactOccurrences"])
            self.assertFalse(bundle["anchors"][1]["targetReached"])

    def test_faulted_replay_uses_only_healthy_exact_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            healthy = {"schemaVersion": 1, "anchors": [
                {"occurrenceAddress": address, "targetReached": True,
                 "summary": {"targetReached": True,
                    "closureMembershipAuthority":
                    "original_runtime_selected_region_finalizer",
                    "targetEvidence": {"selectedOccurrenceAddress": address}}}
                for address in ("target-00", "target-25", "target-49",
                                "target-74")]}
            calls = []

            def graph(_trace, output, **arguments):
                output.mkdir(parents=True)
                address = arguments["target_occurrence"]
                calls.append(address)
                present = address != "target-49"
                if present:
                    (output / "target-occurrence.json").write_text(json.dumps({
                        "requestedOccurrenceAddress": address,
                        "selectedOccurrenceAddress": address}),
                        encoding="utf-8")
                summary = {"status": "target_reached" if present else
                           "target_absent", "targetReached": present,
                           "closureMembershipAuthority":
                           "original_runtime_selected_region_finalizer",
                           "targetEvidence": {
                               "selectedOccurrenceAddress": address}}
                (output / "summary.json").write_text(json.dumps(summary),
                                                      encoding="utf-8")
                return summary

            with patch("Mallory.native_graphchecker_feedback.multi_target."
                       "record_region_state", side_effect=graph):
                result = record_pinned_region_states(
                    root, root / "fault-graphs", healthy_bundle=healthy)
            self.assertEqual([row["occurrenceAddress"] for row in
                              healthy["anchors"]], calls)
            self.assertEqual("retry_exact_missing", result["status"])
            self.assertEqual(["target-49"], result["retryExactOccurrences"])
            self.assertEqual(4, len(result["anchors"]))
            self.assertNotIn("target-01", calls)

            with self.assertRaisesRegex(ValueError, "invalid exact"):
                record_pinned_region_states(root, root / "bad",
                    healthy_bundle={"schemaVersion": 1, "anchors": [
                        {"occurrenceAddress": "target-00"},
                        {"occurrenceAddress": "target-00"}]})

    def test_existing_plan_key_is_bytewise_unchanged(self) -> None:
        from Mallory.native_graphchecker_campaign.campaign import _plan_key
        plan = [{"siteId": "<A: void rpc()>#u1",
                 "exceptionClass": "java.io.IOException", "node": "dn0",
                 "actorEpochOrdinal": 0, "ordinal": 1,
                 "sourceOccurrenceId": "x"}]
        self.assertEqual(
            "2b6291ad31bc6548fb0e63882687e8071ebf492ba7d564dce0049d40a6e4fdad",
            _plan_key(plan))

    def test_adapter_fixture_wires_exact_resolver_recorder_and_finalizer(self) -> None:
        """Exercise the real Python adapter and mock only Java/finalizer IO."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / "trace"
            trace.mkdir()
            (trace / "streaming_trace_manifest.json").write_text(json.dumps({
                "schemaVersion": 2, "kind": "STREAMING_RUNTIME_TRACE",
                "status": "CLOSED", "tracedRows": "fixture"}), encoding="utf-8")
            (trace / "runtime_trace.jsonl").write_text("", encoding="utf-8")
            (trace / "schedule.jsonl").write_text("", encoding="utf-8")
            files = [root / name for name in
                     ("scope.jsonl", "graph.jsonl", "regions.jsonl", "engine.jar",
                      "dependencies.txt", "events.jsonl")]
            for file in files:
                file.write_text("fixture\n", encoding="utf-8")
            scope, candidate, skeletons, engine, deps, events = files
            events.write_text("", encoding="utf-8")
            commands = []

            def fake_java(args, **_kwargs):
                commands.append(args)
                if any(arg.endswith("MalloryTargetOccurrenceResolver")
                       for arg in args):
                    selected = (args[args.index("--target-occurrence") + 1]
                                if "--target-occurrence" in args else "target-00")
                    output = Path(args[args.index("--output") + 1])
                    row = receipt(3)
                    row.update({"selectedOccurrenceAddress": selected,
                                "selectedEventSeq": 10,
                                "selectedCallId": 1})
                    if "--target-occurrence" in args:
                        row.update({"schemaVersion": 2,
                                    "selectionPolicy":
                                    "EXACT_REQUESTED_OCCURRENCE_THEN_EARLIEST_EVENT",
                                    "requestedOccurrenceAddress": selected})
                    output.write_text(json.dumps(row), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            def fake_finalizer(_trace, _plan, target_receipt, *_args, **_kwargs):
                selected = json.loads(target_receipt.read_text())[
                    "selectedOccurrenceAddress"]
                return {"status": "target_reached", "targetReached": True,
                        "closureMembershipAuthority":
                        "original_runtime_selected_region_finalizer",
                        "targetEvidence": {
                            "selectedOccurrenceAddress": selected},
                        "closureOccurrenceIds": [selected],
                        "provenance": {}}

            module = "Mallory.native_graphchecker_feedback.region_state_graph"
            with patch(module + ".DEPENDENCIES", deps), patch(
                    module + ".subprocess.run", side_effect=fake_java), patch(
                    module + ".summarize_region_state",
                    side_effect=fake_finalizer):
                bundle = record_multiple_region_states(trace, root / "graphs",
                    test_id="fixture", target_site="<Example: void check()>#u7",
                    fault_events=events, static_scope_map=scope,
                    candidate_graph=candidate, region_skeletons=skeletons,
                    engine_jar=engine, max_anchors=3)
            self.assertEqual([], bundle["retryExactOccurrences"])
            self.assertEqual(3, len(bundle["anchors"]))
            resolver = [cmd for cmd in commands if any(
                arg.endswith("MalloryTargetOccurrenceResolver") for arg in cmd)]
            recorder = [cmd for cmd in commands if any(
                arg.endswith("CausynthTraceRecorder") for arg in cmd)]
            self.assertEqual(4, len(resolver))
            self.assertEqual(4, len(recorder))
            self.assertEqual({"target-00", "target-01", "target-02"}, {
                cmd[cmd.index("--target-occurrence") + 1]
                for cmd in resolver if "--target-occurrence" in cmd})
            self.assertEqual({"target-00", "target-01", "target-02"}, {
                cmd[cmd.index("--target-occurrence") + 1]
                for cmd in recorder if "--target-occurrence" in cmd})


if __name__ == "__main__":
    unittest.main()
