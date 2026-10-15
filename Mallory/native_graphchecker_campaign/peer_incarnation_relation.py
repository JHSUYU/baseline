"""Read-only evidence for RPC peer incarnation shared by a fault and target.

The result concerns *process incarnation*, not HDFS namespace identity.  A
NameNode restart can change the peer incarnation within one cluster, so a
``different`` result is useful for ranking/audit but must not prune a fault
sequence by itself.  All peer links require a unique recorded RPC exchange.
"""

from __future__ import annotations

import argparse
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
        ancestors = _ancestors(send.get("callId", 0), parent)
        if any((enters.get(call_id, {}).get("objectId") == handle and
                enters.get(call_id, {}).get("sourceKey") == fault_source_key and
                enters.get(call_id, {}).get("receiverType") ==
                fault_enter.get("receiverType")) for call_id in ancestors):
            fault_peers.add(peer)
            fault_pairs.append(evidence)

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
