"""Read-only evidence for RPC peer incarnation shared by a fault and target.

The result concerns *process incarnation*, not HDFS namespace identity.  A
NameNode restart can change the peer incarnation within one cluster, so a
``different`` result is useful for ranking/audit but must not prune a fault
sequence by itself.  All peer links require a unique recorded RPC exchange.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("correlationId", "")),
            str(row.get("attemptId", "")), str(row.get("half", "")))


def _ancestors(call_id: int, parent: dict[int, int]) -> set[int]:
    result: set[int] = set()
    while call_id and call_id not in result:
        result.add(call_id)
        call_id = parent.get(call_id, 0)
    return result


def peer_incarnation_relation(
    trace_path: Path, *, fault_method: str, fault_exception: str,
    fault_source_key: str, target_source_key: str,
    fault_throw_seq: int | None = None,
) -> dict[str, Any]:
    """Relate an exact faulting receiver instance to a target node's RPC peer.

    The caller must establish separately that the throw is the *applied* fault
    and ``target_source_key`` belongs to the selected target occurrence.  A
    unique matching method throw identifies the faulting receiver object; a
    prior or later successful RPC on that same receiver identifies its peer.
    Missing or ambiguous evidence returns ``unknown``.
    """
    enters: dict[int, dict[str, Any]] = {}
    parent: dict[int, int] = {}
    throws: list[dict[str, Any]] = []
    sends: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    receives: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    response_receives: dict[tuple[str, str], list[dict[str, Any]]] = (
        defaultdict(list))
    with trace_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            event = row.get("event")
            if event == "METHOD_ENTER" and isinstance(row.get("callId"), int):
                enters[row["callId"]] = row
                parent[row["callId"]] = row.get("parentCallId") or 0
            elif event == "METHOD_EXIT_THROW" and row.get("method") == fault_method:
                if row.get("runtimeType") == fault_exception:
                    throws.append(row)
            elif (row.get("transport") == "HADOOP_IPC" and
                  event == "EXCHANGE_RECEIVE" and
                  row.get("half") == "RESPONSE"):
                key = _key(row)
                if all(key):
                    response_receives[key[:2]].append(row)
            elif (row.get("transport") == "HADOOP_IPC" and
                  row.get("half") == "REQUEST" and
                  event in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE")):
                key = _key(row)
                if not all(key):
                    continue
                (sends if event == "EXCHANGE_SEND" else receives)[key].append(row)

    report: dict[str, Any] = {
        "relation": "unknown", "faultMethod": fault_method,
        "faultSourceKey": fault_source_key,
        "targetSourceKey": target_source_key,
        "faultPeerIncarnations": [], "targetPeerIncarnations": [],
    }
    candidates = [row for row in throws
                  if (fault_throw_seq is None or row.get("seq") == fault_throw_seq)
                  and enters.get(row.get("callId"), {}).get("sourceKey") ==
                  fault_source_key]
    if len(candidates) != 1:
        report["reason"] = "fault_throw_missing_or_ambiguous"
        return report
    fault_throw = candidates[0]
    fault_enter = enters[fault_throw["callId"]]
    handle = fault_enter.get("objectId")
    if not isinstance(handle, int) or handle <= 0:
        report["reason"] = "fault_receiver_identity_missing"
        return report
    report["faultThrowSeq"] = fault_throw.get("seq")
    report["faultReceiverObjectId"] = handle

    fault_peers: set[str] = set()
    target_peers: set[str] = set()
    fault_pairs: list[dict[str, Any]] = []
    target_pairs: list[dict[str, Any]] = []
    for key, send_rows in sends.items():
        recv_rows = receives.get(key, [])
        if len(send_rows) != 1 or len(recv_rows) != 1:
            continue
        send, receive = send_rows[0], recv_rows[0]
        peer = receive.get("sourceKey")
        if receive.get("sourceRole") != "NAMENODE" or not peer:
            continue
        evidence = {"correlationId": key[0], "attemptId": key[1],
                    "sendSeq": send.get("seq"),
                    "receiveSeq": receive.get("seq"), "peer": peer}
        if (send.get("sourceKey") == target_source_key and
                send.get("sourceRole") == "DATANODE"):
            target_peers.add(peer)
            target_pairs.append(evidence)
        if send.get("sourceKey") != fault_source_key:
            continue
        # HDFS's RpcRequestSender may write on a different thread, so its
        # callId can be 0.  The exact matching RESPONSE is attached on the
        # original caller thread and carries that caller's invocation.
        responses = [row for row in response_receives.get(key[:2], [])
                     if row.get("sourceKey") == fault_source_key]
        if len(responses) != 1:
            continue
        ancestors = _ancestors(responses[0].get("callId", 0), parent)
        if any((enters.get(call_id, {}).get("objectId") == handle and
                enters.get(call_id, {}).get("sourceKey") == fault_source_key and
                enters.get(call_id, {}).get("receiverType") ==
                fault_enter.get("receiverType")) for call_id in ancestors):
            fault_peers.add(peer)
            fault_pairs.append({**evidence,
                                "responseReceiveSeq": responses[0].get("seq"),
                                "responseCallId": responses[0].get("callId")})

    report["faultPeerIncarnations"] = sorted(fault_peers)
    report["targetPeerIncarnations"] = sorted(target_peers)
    report["faultPairCount"] = len(fault_pairs)
    report["targetPairCount"] = len(target_pairs)
    report["faultPairExamples"] = fault_pairs[:3]
    report["targetPairExamples"] = target_pairs[:3]
    if len(fault_peers) != 1 or len(target_peers) != 1:
        report["reason"] = "peer_identity_missing_or_ambiguous"
    elif fault_peers == target_peers:
        report["relation"] = "same"
        report["reason"] = "same_exact_namenode_source_epoch"
    else:
        report["relation"] = "different"
        report["reason"] = "different_exact_namenode_source_epoch"
    return report


DOOR_IDENTITY_FIELDS = ("siteId", "node", "actorEpochOrdinal",
                        "occurrenceId", "ordinal", "exceptionClass")


def _door_identity(row: dict[str, Any]) -> tuple[Any, ...] | None:
    values = tuple(row.get(field) for field in DOOR_IDENTITY_FIELDS)
    if any(value is None or value == "" for value in values):
        return None
    return values


def healthy_door_peer_relation(
    trace_path: Path, fault_events_path: Path, *,
    door_identity: dict[str, Any], target_source_key: str,
) -> dict[str, Any]:
    """Relate one healthy fault door to the selected DataNode's NN incarnation.

    This requires a generic ``NATIVE_FAULT_DOOR`` raw row carrying the exact
    GraphChecker six-field door identity and the enclosing raw call/receiver
    IDs.  Old traces have no such row and return ``unknown``; matching by the
    ordinal of a method entry would invent a join when a call skips or repeats
    the door.  The caller must obtain ``target_source_key`` from the selected
    target occurrence, not from any other target in the same test.
    """
    identity = _door_identity(door_identity)
    report: dict[str, Any] = {
        "relation": "unknown", "doorIdentity": door_identity,
        "targetSourceKey": target_source_key,
        "faultPeerIncarnations": [], "targetPeerIncarnations": [],
    }
    if identity is None or not target_source_key:
        report["reason"] = "door_or_target_identity_missing"
        return report

    event_digest = hashlib.sha256()
    receipts: list[dict[str, Any]] = []
    with fault_events_path.open("rb") as stream:
        for line in stream:
            event_digest.update(line)
            row = json.loads(line)
            if row.get("kind") == "FAULT_DOOR" and _door_identity(row) == identity:
                receipts.append(row)
    report["faultEventsSha256"] = event_digest.hexdigest()
    if len(receipts) != 1:
        report["reason"] = "door_receipt_missing_or_ambiguous"
        return report

    enters: dict[int, dict[str, Any]] = {}
    parent: dict[int, int] = {}
    native_rows: list[dict[str, Any]] = []
    sends: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    receives: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    responses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    trace_digest = hashlib.sha256()
    with trace_path.open("rb") as stream:
        for line in stream:
            trace_digest.update(line)
            row = json.loads(line)
            event = row.get("event")
            if event == "METHOD_ENTER" and isinstance(row.get("callId"), int):
                enters[row["callId"]] = row
                parent[row["callId"]] = row.get("parentCallId") or 0
            elif (event == "NATIVE_FAULT_DOOR" and
                  _door_identity(row) == identity):
                native_rows.append(row)
            elif (row.get("transport") == "HADOOP_IPC" and
                  event == "EXCHANGE_RECEIVE" and
                  row.get("half") == "RESPONSE"):
                key = _key(row)
                if all(key):
                    responses[key[:2]].append(row)
            elif (row.get("transport") == "HADOOP_IPC" and
                  row.get("half") == "REQUEST" and
                  event in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE")):
                key = _key(row)
                if all(key):
                    (sends if event == "EXCHANGE_SEND" else receives)[key].append(row)
    report["traceSha256"] = trace_digest.hexdigest()
    if len(native_rows) != 1:
        report["reason"] = "raw_door_identity_missing_or_ambiguous"
        return report
    native = native_rows[0]
    if native.get("identityStatus") != "owner_matches_active_receiver":
        report["reason"] = "raw_door_receiver_unproven"
        return report
    call_id = native.get("callId")
    receiver_id = native.get("receiverObjectId")
    enter = enters.get(call_id) if isinstance(call_id, int) and call_id > 0 else None
    if (enter is None or not isinstance(receiver_id, int) or receiver_id <= 0 or
            enter.get("objectId") != receiver_id or
            native.get("sourceKey") != enter.get("sourceKey") or
            native.get("sourceKey") !=
            (str(identity[1]) + "#epoch" + str(identity[2]))):
        report["reason"] = "raw_door_call_or_receiver_mismatch"
        return report
    report["faultCallId"] = call_id
    report["faultReceiverObjectId"] = receiver_id
    report["faultSourceKey"] = native["sourceKey"]

    fault_peers: set[str] = set()
    target_peers: set[str] = set()
    fault_pairs: list[dict[str, Any]] = []
    target_pairs: list[dict[str, Any]] = []
    for key, send_rows in sends.items():
        recv_rows = receives.get(key, [])
        if len(send_rows) != 1 or len(recv_rows) != 1:
            continue
        send, receive = send_rows[0], recv_rows[0]
        peer = receive.get("sourceKey")
        if receive.get("sourceRole") != "NAMENODE" or not peer:
            continue
        evidence = {"correlationId": key[0], "attemptId": key[1],
                    "sendSeq": send.get("seq"),
                    "receiveSeq": receive.get("seq"), "peer": peer}
        if (send.get("sourceKey") == target_source_key and
                send.get("sourceRole") == "DATANODE"):
            target_peers.add(peer)
            target_pairs.append(evidence)
        if send.get("sourceKey") != native["sourceKey"]:
            continue
        response_rows = [row for row in responses.get(key[:2], [])
                         if row.get("sourceKey") == native["sourceKey"]]
        if len(response_rows) != 1:
            continue
        if call_id in _ancestors(response_rows[0].get("callId", 0), parent):
            fault_peers.add(peer)
            fault_pairs.append({**evidence,
                                "responseReceiveSeq": response_rows[0].get("seq"),
                                "responseCallId": response_rows[0].get("callId")})

    report["faultPeerIncarnations"] = sorted(fault_peers)
    report["targetPeerIncarnations"] = sorted(target_peers)
    report["faultPairCount"] = len(fault_pairs)
    report["targetPairCount"] = len(target_pairs)
    report["faultPairExamples"] = fault_pairs[:3]
    report["targetPairExamples"] = target_pairs[:3]
    if len(fault_peers) != 1 or len(target_peers) != 1:
        report["reason"] = "peer_identity_missing_or_ambiguous"
    elif fault_peers == target_peers:
        report["relation"] = "same"
        report["reason"] = "same_exact_namenode_source_epoch"
    else:
        report["relation"] = "different"
        report["reason"] = "different_exact_namenode_source_epoch"
    return report


def healthy_door_peer_relations(
    trace_path: Path, fault_events_path: Path, *,
    queries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Batch the exact healthy-door relation without rereading the raw trace.

    Each query has ``doorIdentity`` (the six FAULT_DOOR fields) and
    ``targetSourceKey`` (from one selected target occurrence).  One raw trace
    pass indexes only method identity/parentage and compact HADOOP_IPC rows;
    one wire-pair pass supplies every queried door.  Results are in query
    order and retain the single-query fail-closed rules and file hashes.
    """
    if not queries:
        return []
    wanted = {_door_identity(q.get("doorIdentity", {})) for q in queries}
    wanted.discard(None)
    receipt_counts: dict[tuple[Any, ...], int] = defaultdict(int)
    event_digest = hashlib.sha256()
    with fault_events_path.open("rb") as stream:
        for line in stream:
            event_digest.update(line)
            row = json.loads(line)
            if row.get("kind") == "FAULT_DOOR":
                identity = _door_identity(row)
                if identity in wanted:
                    receipt_counts[identity] += 1

    enters: dict[int, tuple[Any, Any]] = {}
    parent: dict[int, int] = {}
    duplicate_calls: set[int] = set()
    native_rows: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    sends: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    receives: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    responses: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    trace_digest = hashlib.sha256()
    with trace_path.open("rb") as stream:
        for line in stream:
            trace_digest.update(line)
            row = json.loads(line)
            event = row.get("event")
            if event == "METHOD_ENTER" and isinstance(row.get("callId"), int):
                call_id = row["callId"]
                if call_id in enters:
                    duplicate_calls.add(call_id)
                enters[call_id] = (row.get("objectId"), row.get("sourceKey"))
                parent[call_id] = row.get("parentCallId") or 0
            elif event == "NATIVE_FAULT_DOOR":
                identity = _door_identity(row)
                if identity in wanted:
                    native_rows[identity].append({
                        "callId": row.get("callId"),
                        "receiverObjectId": row.get("receiverObjectId"),
                        "sourceKey": row.get("sourceKey"),
                        "identityStatus": row.get("identityStatus")})
            elif (row.get("transport") == "HADOOP_IPC" and
                  event == "EXCHANGE_RECEIVE" and
                  row.get("half") == "RESPONSE"):
                key = _key(row)
                if all(key):
                    responses[key[:2]].append({
                        "callId": row.get("callId"),
                        "sourceKey": row.get("sourceKey"),
                        "seq": row.get("seq")})
            elif (row.get("transport") == "HADOOP_IPC" and
                  row.get("half") == "REQUEST" and
                  event in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE")):
                key = _key(row)
                if all(key):
                    (sends if event == "EXCHANGE_SEND" else receives)[key].append({
                        "sourceKey": row.get("sourceKey"),
                        "sourceRole": row.get("sourceRole"),
                        "seq": row.get("seq")})

    event_sha = event_digest.hexdigest()
    trace_sha = trace_digest.hexdigest()
    eligible: dict[tuple[Any, ...], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for query in queries:
        door = query.get("doorIdentity", {})
        target = query.get("targetSourceKey", "")
        identity = _door_identity(door)
        report: dict[str, Any] = {
            "relation": "unknown", "doorIdentity": door,
            "targetSourceKey": target,
            "faultPeerIncarnations": [], "targetPeerIncarnations": [],
            "faultEventsSha256": event_sha, "traceSha256": trace_sha,
        }
        results.append(report)
        if identity is None or not target:
            report["reason"] = "door_or_target_identity_missing"
            continue
        if receipt_counts[identity] != 1:
            report["reason"] = "door_receipt_missing_or_ambiguous"
            continue
        candidates = native_rows[identity]
        if len(candidates) != 1:
            report["reason"] = "raw_door_identity_missing_or_ambiguous"
            continue
        native = candidates[0]
        if native.get("identityStatus") != "owner_matches_active_receiver":
            report["reason"] = "raw_door_receiver_unproven"
            continue
        call_id = native.get("callId")
        receiver_id = native.get("receiverObjectId")
        enter = enters.get(call_id) if isinstance(call_id, int) and call_id > 0 else None
        source = str(identity[1]) + "#epoch" + str(identity[2])
        if (enter is None or call_id in duplicate_calls or
                not isinstance(receiver_id, int) or receiver_id <= 0 or
                enter != (receiver_id, source) or native.get("sourceKey") != source):
            report["reason"] = "raw_door_call_or_receiver_mismatch"
            continue
        report["faultCallId"] = call_id
        report["faultReceiverObjectId"] = receiver_id
        report["faultSourceKey"] = source
        eligible[identity] = native

    requested_calls = {native["callId"] for native in eligible.values()}
    target_pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    caller_pairs: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for key, send_rows in sends.items():
        recv_rows = receives.get(key, [])
        if len(send_rows) != 1 or len(recv_rows) != 1:
            continue
        send, receive = send_rows[0], recv_rows[0]
        peer = receive["sourceKey"]
        if receive["sourceRole"] != "NAMENODE" or not peer:
            continue
        evidence = {"correlationId": key[0], "attemptId": key[1],
                    "sendSeq": send["seq"], "receiveSeq": receive["seq"],
                    "peer": peer}
        if send["sourceRole"] == "DATANODE":
            target_pairs[send["sourceKey"]].append(evidence)
        response_rows = [row for row in responses.get(key[:2], [])
                         if row["sourceKey"] == send["sourceKey"]]
        if len(response_rows) != 1:
            continue
        response = response_rows[0]
        if not isinstance(response["callId"], int):
            continue
        for ancestor in _ancestors(response["callId"], parent):
            if ancestor in requested_calls:
                caller_pairs[(ancestor, send["sourceKey"])].append({
                    **evidence, "responseReceiveSeq": response["seq"],
                    "responseCallId": response["callId"]})

    for report in results:
        if "reason" in report:
            continue
        identity = _door_identity(report["doorIdentity"])
        assert identity is not None
        native = eligible[identity]
        fault_pairs = caller_pairs[(native["callId"], native["sourceKey"])]
        target = target_pairs[report["targetSourceKey"]]
        fault_peers = {row["peer"] for row in fault_pairs}
        target_peers = {row["peer"] for row in target}
        report["faultPeerIncarnations"] = sorted(fault_peers)
        report["targetPeerIncarnations"] = sorted(target_peers)
        report["faultPairCount"] = len(fault_pairs)
        report["targetPairCount"] = len(target)
        report["faultPairExamples"] = fault_pairs[:3]
        report["targetPairExamples"] = target[:3]
        if len(fault_peers) != 1 or len(target_peers) != 1:
            report["reason"] = "peer_identity_missing_or_ambiguous"
        elif fault_peers == target_peers:
            report["relation"] = "same"
            report["reason"] = "same_exact_namenode_source_epoch"
        else:
            report["relation"] = "different"
            report["reason"] = "different_exact_namenode_source_epoch"
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--fault-method", required=True)
    parser.add_argument("--fault-exception", required=True)
    parser.add_argument("--fault-source-key", required=True)
    parser.add_argument("--target-source-key", required=True)
    parser.add_argument("--fault-throw-seq", type=int)
    args = parser.parse_args()
    print(json.dumps(peer_incarnation_relation(
        args.trace, fault_method=args.fault_method,
        fault_exception=args.fault_exception,
        fault_source_key=args.fault_source_key,
        target_source_key=args.target_source_key,
        fault_throw_seq=args.fault_throw_seq), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
