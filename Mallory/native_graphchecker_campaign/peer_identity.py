"""Conservative peer identity hints from an original GraphChecker trace.

These hints rank already observed, statically admitted fault doors. They never
add a door, a causal edge, or evidence that an injected exception took effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SITE_METHOD = re.compile(r"^(<[^>]+>)#u[0-9]+$")
PEER_RANK_VERSION = 1
UNKNOWN = "unknown"


def _actor_key(door: dict[str, Any]) -> str:
    return f"{door['node']}#epoch{door['actorEpochOrdinal']}"


def _site_method(site: str) -> str | None:
    match = SITE_METHOD.fullmatch(site)
    return match.group(1) if match else None


def rank_region_doors_by_peer(
    doors: list[dict[str, Any]], trace_path: Path, target_receipt_path: Path,
    static_rpc_sites: frozenset[str],
    observed_fault_doors: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Annotate exact doors when their RPC peer can be joined without a guess.

    A fault door has no RPC correlation ID. We therefore join a method's
    observed doors to its request sends only when one static site owns that
    method for this actor and their cardinalities and ordinals agree. The
    method is the last statically eligible method on the producer endpoint's
    call path, closest to the actual IPC send. Ambiguous joins stay unknown.
    """
    ranked = [{**door, "peer_relation": UNKNOWN} for door in doors]
    audit: dict[str, Any] = {
        "schemaVersion": PEER_RANK_VERSION,
        "status": "unknown",
        "traceSha256": None,
        "targetReceiptSha256": None,
        "targetActor": None,
        "targetSeq": None,
        "requestExchangePairs": 0,
        "unpairedExchangeKeys": 0,
        "ambiguousExchangeKeys": 0,
        "joinedDoorCount": 0,
        "ambiguousDoorCount": 0,
        "samePeerBeforeTargetCount": 0,
    }
    if not trace_path.is_file() or not target_receipt_path.is_file():
        audit["status"] = "missing_original_trace_or_target_receipt"
        return ranked, audit
    raw = target_receipt_path.read_bytes()
    receipt = json.loads(raw)
    audit["targetReceiptSha256"] = hashlib.sha256(raw).hexdigest()
    target_seq = receipt.get("selectedEventSeq")
    address = receipt.get("selectedOccurrenceAddress")
    reached = receipt.get("reachedEvents")
    if (not isinstance(target_seq, int) or isinstance(target_seq, bool) or
            target_seq <= 0 or not isinstance(address, str) or
            "/region/" not in address or not isinstance(reached, list)):
        audit["status"] = "invalid_target_receipt"
        return ranked, audit
    target_actor = address.split("/region/", 1)[0]
    if not any(isinstance(row, dict) and row.get("eventSeq") == target_seq
               and row.get("sourceKey") == target_actor for row in reached):
        audit["status"] = "selected_target_absent_from_receipt"
        return ranked, audit
    audit["targetActor"], audit["targetSeq"] = target_actor, target_seq

    site_methods: dict[str, set[str]] = defaultdict(set)
    for door in ranked:
        fault = door["fault"]
        site = fault.get("siteId")
        if site in static_rpc_sites:
            method = _site_method(site)
            if method:
                site_methods[method].add(site)
    if not site_methods:
        audit["status"] = "no_static_rpc_door"
        return ranked, audit

    # Retain only exchange rows; even large target traces have few of them.
    exchange: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = (
        defaultdict(lambda: {"send": [], "receive": []}))
    digest = hashlib.sha256()
    with trace_path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            row = json.loads(line)
            event = row.get("event")
            if event not in ("EXCHANGE_SEND", "EXCHANGE_RECEIVE"):
                continue
            key = (row.get("correlationId"), row.get("attemptId"),
                   row.get("half"))
            if not all(isinstance(value, str) and value for value in key):
                continue
            exchange[key]["send" if event == "EXCHANGE_SEND" else
                          "receive"].append(row)
    audit["traceSha256"] = digest.hexdigest()
    if receipt.get("runtimeTraceSha256") != audit["traceSha256"]:
        audit["status"] = "target_receipt_trace_hash_mismatch"
        return ranked, audit

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for halves in exchange.values():
        sends = halves["send"]
        receives = halves["receive"]
        if len(sends) != 1 or len(receives) != 1:
            # Per-actor sequence cannot prove which of several sends reached
            # which receiver. Do not zip equal-count repeated keys.
            audit["ambiguousExchangeKeys"] += 1
            if len(sends) != len(receives):
                audit["unpairedExchangeKeys"] += 1
            continue
        if sends[0].get("seq") is None or receives[0].get("seq") is None:
            audit["unpairedExchangeKeys"] += 1
            continue
        pairs.append((sends[0], receives[0]))
    requests = [(send, receive) for send, receive in pairs
                if send.get("half") == "REQUEST" and
                isinstance(send.get("seq"), int) and
                isinstance(receive.get("seq"), int) and
                isinstance(send.get("sourceKey"), str) and
                isinstance(receive.get("sourceKey"), str) and
                isinstance(receive.get("sourceRole"), str)]
    audit["requestExchangePairs"] = len(requests)

    # A parent call path can contain several RPC methods. The last eligible
    # method is closest to the IPC send. A cardinality check below prevents
    # silently using this order when the native door stream disagrees.
    sends_by_method_actor: dict[tuple[str, str], list[tuple[dict, dict]]] = (
        defaultdict(list))
    for send, receive in requests:
        endpoint = send.get("producerEndpoint") or ""
        candidates = [(endpoint.rfind(method), method)
                      for method in site_methods if method in endpoint]
        if candidates:
            method = max(candidates)[1]
            sends_by_method_actor[(method, send["sourceKey"])].append(
                (send, receive))

    # An after-fault eligible suffix can start at ordinal >1. Match against
    # the complete observed door stream, then annotate its eligible subset.
    # A failed RPC may remove its send and make the cardinality ambiguous;
    # in that case this remains an unknown ranking hint.
    observed = (observed_fault_doors if observed_fault_doors is not None else
                [door["fault"] for door in ranked])
    door_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fault in observed:
        if fault.get("kind", "FAULT_DOOR") != "FAULT_DOOR":
            continue
        method = _site_method(fault.get("siteId", ""))
        if method in site_methods:
            door_groups[(method, _actor_key(fault))].append(fault)
    eligible_by_group: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, door in enumerate(ranked):
        fault = door["fault"]
        method = _site_method(fault.get("siteId", ""))
        if method in site_methods:
            eligible_by_group[(method, _actor_key(fault))].append(index)

    target_peers_by_role: dict[str, set[str]] = defaultdict(set)
    for send, receive in requests:
        # Both sequence values below belong to the selected target actor.
        # They must never order a producer on another actor against the target.
        if send["sourceKey"] == target_actor and send["seq"] < target_seq:
            target_peers_by_role[receive["sourceRole"]].add(
                receive["sourceKey"])

    peer_by_selector: dict[tuple[str, str, int], str] = {}
    for (method, actor), observed_rows in door_groups.items():
        candidate = sends_by_method_actor.get((method, actor), [])
        ordinals = [fault.get("ordinal") for fault in observed_rows]
        if (len(site_methods[method]) != 1 or
                len(candidate) != len(observed_rows) or
                any(not isinstance(value, int) or isinstance(value, bool)
                    for value in ordinals) or
                sorted(ordinals) != list(range(1, len(observed_rows) + 1))):
            audit["ambiguousDoorCount"] += len(eligible_by_group[(method, actor)])
            continue
        for fault, (send, receive) in zip(
                sorted(observed_rows, key=lambda item: item["ordinal"]),
                sorted(candidate, key=lambda pair: pair[0]["seq"])):
            peers = target_peers_by_role.get(receive["sourceRole"], set())
            if len(peers) != 1:
                continue
            same_peer = receive["sourceKey"] in peers
            peer_by_selector[(fault["siteId"], actor,
                              fault["ordinal"])] = (
                                  "same_peer" if same_peer else "different_peer")
    for door in ranked:
        fault = door["fault"]
        peer = peer_by_selector.get((fault["siteId"], _actor_key(fault),
                                     fault["ordinal"]))
        phase = door.get("target_phase")
        if peer is None or phase not in ("before_selected_target",
                                         "after_selected_target"):
            continue
        # _region_doors derives phase from append order in the native hook
        # receipt. This is only a bounded scheduling heuristic, not a
        # cross-actor happens-before or a causal edge.
        relation = peer + ("_before_target" if phase ==
                           "before_selected_target" else "_after_target")
        door["peer_relation"] = relation
        audit["joinedDoorCount"] += 1
        if relation == "same_peer_before_target":
            audit["samePeerBeforeTargetCount"] += 1
    audit["status"] = "ranked"
    return ranked, audit
