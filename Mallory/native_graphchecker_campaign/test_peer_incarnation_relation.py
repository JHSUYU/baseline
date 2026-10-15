"""Small exact-pair fixtures for read-only RPC peer incarnation evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_campaign.peer_incarnation_relation import (
    healthy_door_peer_relation,
    peer_incarnation_relation,
)


FAULT_METHOD = "<ClientTranslator: Response rpc()>"
FAULT_EXCEPTION = "ServiceException"
CLIENT = "workload#epoch0"
TARGET = "dn2#epoch0"
DOOR = {"siteId": FAULT_METHOD + "#u4", "node": CLIENT.split("#epoch")[0],
        "actorEpochOrdinal": 0, "occurrenceId": "door-region-1",
        "ordinal": 2, "exceptionClass": FAULT_EXCEPTION}


class PeerIncarnationRelationTest(unittest.TestCase):
    def _events(self):
        return [
            {"event": "METHOD_ENTER", "seq": 1, "callId": 10,
             "parentCallId": 0, "method": FAULT_METHOD,
             "objectId": 11, "receiverType": "ClientTranslator",
             "sourceKey": CLIENT},
            {"event": "METHOD_ENTER", "seq": 2, "callId": 12,
             "parentCallId": 10, "method": "<RPC: void send()>",
             "objectId": 13, "receiverType": "RPC", "sourceKey": CLIENT},
            {"event": "EXCHANGE_SEND", "seq": 3, "callId": 12,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
            {"event": "EXCHANGE_RECEIVE", "seq": 4,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": "nn0#epoch0", "sourceRole": "NAMENODE"},
            {"event": "EXCHANGE_RECEIVE", "seq": 4,
             "callId": 10, "transport": "HADOOP_IPC", "half": "RESPONSE",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
            {"event": "METHOD_ENTER", "seq": 5, "callId": 20,
             "parentCallId": 0, "method": FAULT_METHOD,
             "objectId": 11, "receiverType": "ClientTranslator",
             "sourceKey": CLIENT},
            {"event": "METHOD_EXIT_THROW", "seq": 6, "callId": 20,
             "method": FAULT_METHOD, "runtimeType": FAULT_EXCEPTION},
            {"event": "EXCHANGE_SEND", "seq": 7,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-b", "attemptId": "0",
             "sourceKey": TARGET, "sourceRole": "DATANODE"},
            {"event": "EXCHANGE_RECEIVE", "seq": 8,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-b", "attemptId": "0",
             "sourceKey": "nn0#epoch0", "sourceRole": "NAMENODE"},
        ]

    def _run(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            return peer_incarnation_relation(
                path, fault_method=FAULT_METHOD,
                fault_exception=FAULT_EXCEPTION, fault_source_key=CLIENT,
                target_source_key=TARGET, **kwargs)

    def test_same_exact_peer_with_fault_call_that_did_not_send(self):
        result = self._run(self._events())
        self.assertEqual("same", result["relation"])
        self.assertEqual(["nn0#epoch0"], result["faultPeerIncarnations"])
        self.assertEqual(11, result["faultReceiverObjectId"])
        self.assertEqual(1, result["faultPairCount"])

    def test_different_peer_epochs_despite_same_workload_actor(self):
        rows = self._events()
        rows[-1]["sourceKey"] = "nn0#epoch1"
        result = self._run(rows)
        self.assertEqual("different", result["relation"])
        self.assertEqual(["nn0#epoch1"], result["targetPeerIncarnations"])

    def test_ambiguous_client_handle_is_unknown(self):
        rows = self._events()
        rows += [
            {"event": "EXCHANGE_SEND", "seq": 9, "callId": 12,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-c", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
            {"event": "EXCHANGE_RECEIVE", "seq": 10,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-c", "attemptId": "0",
             "sourceKey": "nn0#epoch1", "sourceRole": "NAMENODE"},
            {"event": "EXCHANGE_RECEIVE", "seq": 11, "callId": 10,
             "transport": "HADOOP_IPC", "half": "RESPONSE",
             "correlationId": "rpc-c", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
        ]
        result = self._run(rows)
        self.assertEqual("unknown", result["relation"])
        self.assertEqual("peer_identity_missing_or_ambiguous", result["reason"])

    def test_duplicate_wire_key_does_not_establish_peer(self):
        rows = self._events()
        rows.append(dict(rows[3], seq=11))
        result = self._run(rows)
        self.assertEqual("unknown", result["relation"])
        self.assertEqual([], result["faultPeerIncarnations"])

    def test_missing_or_multiple_fault_throws_are_unknown(self):
        rows = self._events()
        rows.remove(next(row for row in rows if row["event"] ==
                         "METHOD_EXIT_THROW"))
        self.assertEqual("unknown", self._run(rows)["relation"])
        rows = self._events()
        rows.append(dict(next(row for row in rows if row["event"] ==
                              "METHOD_EXIT_THROW"), seq=12))
        self.assertEqual("unknown", self._run(rows)["relation"])
        self.assertEqual("same", self._run(rows, fault_throw_seq=6)["relation"])

    def test_missing_or_duplicate_caller_response_is_unknown(self):
        rows = self._events()
        response = next(row for row in rows if row.get("half") == "RESPONSE")
        rows.remove(response)
        self.assertEqual("unknown", self._run(rows)["relation"])
        rows = self._events()
        response = next(row for row in rows if row.get("half") == "RESPONSE")
        rows.append(dict(response, seq=12))
        self.assertEqual("unknown", self._run(rows)["relation"])

    def test_receiver_identity_is_scoped_to_source_actor(self):
        rows = self._events()
        rows[0]["sourceKey"] = "other-client#epoch0"
        result = self._run(rows)
        self.assertEqual("unknown", result["relation"])
        self.assertEqual([], result["faultPeerIncarnations"])


class HealthyDoorPeerRelationTest(unittest.TestCase):
    @staticmethod
    def _rows():
        return [
            {"event": "METHOD_ENTER", "callId": 20, "parentCallId": 0,
             "objectId": 11, "sourceKey": CLIENT, "method": FAULT_METHOD},
            {"event": "NATIVE_FAULT_DOOR", **DOOR, "callId": 20,
             "receiverObjectId": 11, "sourceKey": CLIENT,
             "identityStatus": "owner_matches_active_receiver"},
            {"event": "EXCHANGE_SEND", "seq": 3, "callId": 0,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
            {"event": "EXCHANGE_RECEIVE", "seq": 4,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": "nn0#epoch0", "sourceRole": "NAMENODE"},
            {"event": "EXCHANGE_RECEIVE", "seq": 5, "callId": 20,
             "transport": "HADOOP_IPC", "half": "RESPONSE",
             "correlationId": "rpc-a", "attemptId": "0",
             "sourceKey": CLIENT, "sourceRole": "CLIENT"},
            {"event": "EXCHANGE_SEND", "seq": 6,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-b", "attemptId": "0",
             "sourceKey": TARGET, "sourceRole": "DATANODE"},
            {"event": "EXCHANGE_RECEIVE", "seq": 7,
             "transport": "HADOOP_IPC", "half": "REQUEST",
             "correlationId": "rpc-b", "attemptId": "0",
             "sourceKey": "nn0#epoch0", "sourceRole": "NAMENODE"},
        ]

    def _run(self, rows=None, receipts=None, target=TARGET):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            events = Path(directory) / "fault-events.jsonl"
            trace.write_text("".join(json.dumps(row) + "\n" for row in
                                     (rows if rows is not None else self._rows())))
            events.write_text("".join(json.dumps(row) + "\n" for row in
                                      (receipts if receipts is not None else
                                       [{"kind": "FAULT_DOOR", **DOOR}])))
            return healthy_door_peer_relation(
                trace, events, door_identity=DOOR, target_source_key=target)

    def test_exact_native_identity_and_response_pair(self):
        result = self._run()
        self.assertEqual("same", result["relation"])
        self.assertEqual(20, result["faultCallId"])
        self.assertEqual(11, result["faultReceiverObjectId"])
        self.assertEqual(["nn0#epoch0"], result["faultPeerIncarnations"])
        self.assertEqual(64, len(result["traceSha256"]))

    def test_different_target_incarnation(self):
        rows = self._rows()
        rows[-1]["sourceKey"] = "nn0#epoch1"
        self.assertEqual("different", self._run(rows)["relation"])

    def test_old_trace_without_native_row_is_unknown(self):
        rows = self._rows()
        rows.pop(1)
        result = self._run(rows)
        self.assertEqual("unknown", result["relation"])
        self.assertEqual("raw_door_identity_missing_or_ambiguous", result["reason"])

    def test_unproven_or_mismatched_receiver_is_unknown(self):
        rows = self._rows()
        rows[1]["identityStatus"] = "unproven"
        self.assertEqual("raw_door_receiver_unproven", self._run(rows)["reason"])
        rows = self._rows()
        rows[1]["receiverObjectId"] = 12
        self.assertEqual("raw_door_call_or_receiver_mismatch",
                         self._run(rows)["reason"])

    def test_six_field_identity_is_unique_and_receipted(self):
        rows = self._rows()
        rows.append(dict(rows[1]))
        self.assertEqual("raw_door_identity_missing_or_ambiguous",
                         self._run(rows)["reason"])
        receipts = [{"kind": "FAULT_DOOR", **DOOR},
                    {"kind": "FAULT_DOOR", **DOOR}]
        self.assertEqual("door_receipt_missing_or_ambiguous",
                         self._run(receipts=receipts)["reason"])

    def test_response_must_descend_from_exact_door_call(self):
        rows = self._rows()
        rows[4]["callId"] = 99
        self.assertEqual("peer_identity_missing_or_ambiguous",
                         self._run(rows)["reason"])

    def test_ambiguous_wire_or_target_peer_is_unknown(self):
        rows = self._rows()
        rows.append(dict(rows[3]))
        self.assertEqual("peer_identity_missing_or_ambiguous",
                         self._run(rows)["reason"])
        rows = self._rows()
        rows += [dict(rows[-2], correlationId="rpc-c"),
                 dict(rows[-1], correlationId="rpc-c", sourceKey="nn0#epoch1")]
        self.assertEqual("peer_identity_missing_or_ambiguous",
                         self._run(rows)["reason"])


if __name__ == "__main__":
    unittest.main()
