"""Offline peer ranking checks; no JUnit or fault injection is launched."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign.peer_identity import rank_region_doors_by_peer


METHOD = "<example.Client: void producer()>"
SITE = METHOD + "#u4"


def _pair(seq: int, source: str, receiver: str, role: str,
          endpoint: str = "") -> list[dict]:
    common = {"correlationId": f"rpc-{seq}", "attemptId": "0",
              "half": "REQUEST"}
    return [
        {**common, "event": "EXCHANGE_SEND", "seq": seq,
         "sourceKey": source, "producerEndpoint": endpoint},
        {**common, "event": "EXCHANGE_RECEIVE", "seq": seq + 1,
         "sourceKey": receiver, "sourceRole": role},
    ]


def _door(ordinal: int, site: str = SITE,
          phase: str = "before_selected_target") -> dict:
    return {"fault": {"siteId": site, "node": "client",
                      "actorEpochOrdinal": 0, "ordinal": ordinal,
                      "exceptionClass": "example.RpcException"},
            "tier": "static_producer_frontier", "seq": ordinal,
            "target_phase": phase}


def _files(root: Path, *, ambiguous_peer: bool = False,
           missing_exchange: bool = False,
           target_epoch: int = 1) -> tuple[Path, Path]:
    target_actor = f"dn#epoch{target_epoch}"
    rows = []
    rows += _pair(1, target_actor, "nn#epoch1", "CONTROL")
    if ambiguous_peer:
        rows += _pair(7, target_actor, "nn#epoch0", "CONTROL")
    for seq, peer in ((3, "nn#epoch0"), (5, "nn#epoch1"),
                      (11, "nn#epoch1"), (13, "nn#epoch1")):
        if missing_exchange and seq == 13:
            continue
        rows += _pair(seq, "client#epoch0", peer, "CONTROL",
                      "ctx/<example.Earlier: void call()>@0/" +
                      METHOD + "@0/<example.Transport: void send()>@0")
    trace = root / "runtime_trace.jsonl"
    trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
    receipt = root / "target-occurrence.json"
    receipt.write_text(json.dumps({
        "selectedEventSeq": 9,
        "selectedOccurrenceAddress": target_actor + "/region/R/ctx",
        "reachedEvents": [{"eventSeq": 9, "sourceKey": target_actor}],
        "runtimeTraceSha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
    }))
    return trace, receipt


class PeerIdentityTest(unittest.TestCase):
    def test_exact_rpc_pairs_rank_actual_peer_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            doors = [_door(i, phase=("before_selected_target" if i <= 2
                                      else "after_selected_target"))
                     for i in range(1, 5)]
            doors.append(_door(1, "<example.File: void read()>#u2"))
            ranked, audit = rank_region_doors_by_peer(
                doors, trace, receipt, frozenset({SITE}))
            self.assertEqual("ranked", audit["status"])
            self.assertEqual(5, audit["requestExchangePairs"])
            self.assertEqual(0, audit["unpairedExchangeKeys"])
            self.assertEqual(1, audit["samePeerBeforeTargetCount"])
            self.assertEqual([
                "different_peer_before_target", "same_peer_before_target",
                "same_peer_after_target", "same_peer_after_target", "unknown",
            ], [item["peer_relation"] for item in ranked])
            self.assertEqual([door["tier"] for door in doors],
                             [door["tier"] for door in ranked])

    def test_peer_identity_does_not_compare_actor_epoch_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory), target_epoch=0)
            ranked, audit = rank_region_doors_by_peer(
                [_door(i) for i in range(1, 5)], trace, receipt,
                frozenset({SITE}))
            self.assertEqual("dn#epoch0", audit["targetActor"])
            self.assertEqual("same_peer_before_target",
                             ranked[1]["peer_relation"])

    def test_after_fault_suffix_uses_full_observed_ordinals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            observed = [{"kind": "FAULT_DOOR", **_door(i)["fault"]}
                        for i in range(1, 5)]
            ranked, audit = rank_region_doors_by_peer(
                [_door(3, phase="after_selected_target"),
                 _door(4, phase="after_selected_target")],
                trace, receipt, frozenset({SITE}),
                observed)
            self.assertEqual(2, audit["joinedDoorCount"])
            self.assertEqual(["same_peer_after_target"] * 2,
                             [item["peer_relation"] for item in ranked])

    def test_producer_lower_local_seq_after_append_order_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            target_site = "Keys#check#u3"
            summary = {
                "targetSiteId": target_site,
                "closureMembershipAuthority":
                    "original_runtime_selected_region_finalizer",
                "closureOccurrenceIds": [],
                "targetEvidence": {
                    "targetCheckOccurrenceIds": ["selected-target"],
                    "physicalActor": "dn", "actorEpochOrdinal": 1},
            }
            observed = [{"kind": "FAULT_DOOR", **_door(i)["fault"],
                         "seq": i, "occurrenceId": f"door-{i}"}
                        for i in range(1, 5)]
            check = {"kind": "TARGET_CHECK", "siteId": target_site,
                     "node": "dn", "actorEpochOrdinal": 1,
                     "seq": 9, "occurrenceId": "selected-target"}
            # Producer's RPC local seq 5 is less than the target actor's 9,
            # while native receipt append order puts door 2 after the check.
            native = [observed[0], check, *observed[1:]]
            doors = campaign._region_doors(
                native, summary, static_may_rpc_sites=frozenset({SITE}))
            self.assertEqual("after_selected_target", doors[1]["target_phase"])
            ranked, audit = rank_region_doors_by_peer(
                doors, trace, receipt, frozenset({SITE}), observed)
            self.assertEqual("ranked", audit["status"])
            self.assertEqual("same_peer_after_target",
                             ranked[1]["peer_relation"])
            self.assertEqual(0, audit["samePeerBeforeTargetCount"])

    def test_missing_native_phase_cannot_gain_peer_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            doors = [_door(i, phase=("before_selected_target" if i <= 2
                                      else "after_selected_target"))
                     for i in range(1, 5)]
            doors[1]["target_phase"] = "unknown"
            ranked, audit = rank_region_doors_by_peer(
                doors, trace, receipt, frozenset({SITE}))
            self.assertEqual("unknown", ranked[1]["peer_relation"])
            self.assertEqual(0, audit["samePeerBeforeTargetCount"])

    def test_ambiguous_peer_or_missing_door_exchange_stays_unknown(self) -> None:
        for kwargs in ({"ambiguous_peer": True}, {"missing_exchange": True}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                trace, receipt = _files(Path(directory), **kwargs)
                ranked, audit = rank_region_doors_by_peer(
                    [_door(i) for i in range(1, 5)], trace, receipt,
                    frozenset({SITE}))
                self.assertEqual(["unknown"] * 4,
                                 [item["peer_relation"] for item in ranked])
                if kwargs.get("missing_exchange"):
                    self.assertEqual(4, audit["ambiguousDoorCount"])

    def test_receipt_trace_hash_mismatch_gives_no_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            value = json.loads(receipt.read_text())
            value["runtimeTraceSha256"] = "0" * 64
            receipt.write_text(json.dumps(value))
            ranked, audit = rank_region_doors_by_peer(
                [_door(1)], trace, receipt, frozenset({SITE}))
            self.assertEqual("target_receipt_trace_hash_mismatch", audit["status"])
            self.assertEqual("unknown", ranked[0]["peer_relation"])

    def test_unpaired_correlation_cannot_supply_peer_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            rows = [json.loads(line) for line in trace.read_text().splitlines()]
            for row in rows:
                if row["event"] == "EXCHANGE_RECEIVE" and row["seq"] == 6:
                    row["correlationId"] = "unrelated-request"
            trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
            value = json.loads(receipt.read_text())
            value["runtimeTraceSha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
            receipt.write_text(json.dumps(value))
            ranked, audit = rank_region_doors_by_peer(
                [_door(i) for i in range(1, 5)], trace, receipt,
                frozenset({SITE}))
            self.assertGreater(audit["unpairedExchangeKeys"], 0)
            self.assertEqual(["unknown"] * 4,
                             [item["peer_relation"] for item in ranked])

    def test_repeated_equal_count_correlation_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace, receipt = _files(Path(directory))
            rows = [json.loads(line) for line in trace.read_text().splitlines()]
            for row in rows:
                if row["seq"] in (5, 6):
                    row["correlationId"] = "rpc-3"
            trace.write_text("".join(json.dumps(row) + "\n" for row in rows))
            value = json.loads(receipt.read_text())
            value["runtimeTraceSha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
            receipt.write_text(json.dumps(value))
            ranked, audit = rank_region_doors_by_peer(
                [_door(i) for i in range(1, 5)], trace, receipt,
                frozenset({SITE}))
            self.assertEqual(1, audit["ambiguousExchangeKeys"])
            self.assertEqual(0, audit["unpairedExchangeKeys"])
            self.assertEqual(["unknown"] * 4,
                             [item["peer_relation"] for item in ranked])

    def test_terminal_audit_verifies_durable_peer_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = root / "trials" / "r0000"
            trial.mkdir(parents=True)
            receipt = trial / "peer-ranking-receipt.json"
            receipt.write_text('{"status":"ranked"}\n')
            result = {"peer_ranking_receipt_sha256": hashlib.sha256(
                receipt.read_bytes()).hexdigest()}
            (trial / "result.json").write_text(json.dumps(result))
            state = {"healthy": {"result": "trials/r0000/result.json"},
                     "trials": []}
            campaign._verify_terminal_peer_ranking_receipts(root, state)
            receipt.write_text('{"status":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "peer ranking receipt"):
                campaign._verify_terminal_peer_ranking_receipts(root, state)

    def test_bounded_peer_slot_prioritizes_matched_rpc_without_reclassifying(self) -> None:
        producer = _door(1)
        other = _door(1, "<example.Local: void write()>#u2")
        producer["peer_relation"] = "same_peer_before_target"
        other["tier"] = "observed_closure"
        other["peer_relation"] = "same_peer_before_target"
        state = {"queue": [], "seen_plan_keys": [],
                 "budget": {"max_faults_per_trial": 4},
                 "completed_fault_trials": 4, "scheduler_version": 8,
                 "fault_id_attempts": {}, "fault_id_successes": {}}
        campaign._enqueue(state, [other, producer], [], 0)
        self.assertEqual(2, len(state["queue"]))
        selected = campaign._pick(state)
        self.assertEqual(SITE, selected["faults"][-1]["siteId"])
        self.assertEqual("static_producer_frontier", selected["tier"])
        self.assertEqual("same_peer_before_target", selected["peer_relation"])
        self.assertEqual("observed_closure", state["queue"][0]["tier"])


if __name__ == "__main__":
    unittest.main()
