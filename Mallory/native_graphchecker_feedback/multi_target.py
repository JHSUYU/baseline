"""Bounded, evidence-pinned selection of repeated target check activations.

This module does not merge GraphChecker closures.  Every selected activation
is resolved, recorded, and finalized independently by the original engine.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_feedback.region_state_graph import (
    delta_region_state, record_region_state,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_rows(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    if (receipt.get("kind") != "MALLORY_OBSERVED_TARGET_OCCURRENCE" or
            receipt.get("schemaVersion") not in (1, 2) or
            not isinstance(receipt.get("fatalOutcome"), bool) or
            not isinstance(receipt.get("reachedEvents"), list)):
        raise ValueError("target candidates require an original resolver receipt")
    rows: dict[str, dict[str, Any]] = {}
    for row in receipt["reachedEvents"]:
        if not isinstance(row, dict):
            raise ValueError("invalid reached target event")
        address, event_seq = row.get("occurrenceAddress"), row.get("eventSeq")
        if (not isinstance(address, str) or not address or
                not isinstance(event_seq, int) or isinstance(event_seq, bool) or
                event_seq < 0 or not isinstance(row.get("sourceKey"), str) or
                not row["sourceKey"] or
                not isinstance(row.get("observedOutcome"), bool) or
                row.get("observedOutcome") == receipt.get("fatalOutcome")):
            raise ValueError("invalid or fatal target candidate")
        if address not in rows or event_seq < rows[address]["eventSeq"]:
            rows[address] = row
    if not rows:
        raise ValueError("resolver receipt has no nonfatal target candidates")
    if len(rows) != receipt.get("distinctReachedOccurrenceCount"):
        raise ValueError("resolver distinct occurrence count differs")
    return sorted(rows.values(), key=lambda row: (
        row["eventSeq"], row["occurrenceAddress"]))


def continuation_signatures(trace_dir: Path, receipt: dict[str, Any], *,
                            method_window: int = 40) -> dict[str, set[str]]:
    """Fingerprint bounded same-lane work after each observed target check.

    The original runtime trace supplies the lane and method identities. A
    method must recur across several activations to be useful; methods common
    to almost every activation carry no context information. These hints
    cannot admit a fault into an original GraphChecker closure.
    """
    if (not isinstance(method_window, int) or isinstance(method_window, bool)
            or not 1 <= method_window <= 256):
        raise ValueError("invalid bounded continuation method window")
    rows = _candidate_rows(receipt)
    trace_dir = Path(trace_dir)
    raw = trace_dir / "runtime_trace.jsonl"
    compressed = trace_dir / "runtime_trace.jsonl.gz"
    if raw.is_file():
        opener, path = open, raw
    elif compressed.is_file():
        opener, path = gzip.open, compressed
    else:
        return {}
    target_calls = {row.get("callId") for row in rows}
    if any(not isinstance(call, int) or isinstance(call, bool)
           for call in target_calls):
        return {}
    target_entries: dict[int, dict[str, Any]] = {}
    methods_by_lane: dict[int, list[tuple[int, str]]] = defaultdict(list)
    with opener(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event") != "METHOD_ENTER":
                continue
            lane, seq, method = (event.get("laneId"), event.get("seq"),
                                 event.get("method"))
            if (not isinstance(lane, int) or isinstance(lane, bool) or
                    not isinstance(seq, int) or isinstance(seq, bool) or
                    not isinstance(method, str) or not method):
                continue
            methods_by_lane[lane].append((seq, method))
            if event.get("callId") in target_calls:
                target_entries[event["callId"]] = event
    raw_signatures: dict[str, set[str]] = {}
    for row in rows:
        entry = target_entries.get(row["callId"])
        if (entry is None or entry.get("sourceKey") != row["sourceKey"] or
                entry["seq"] > row["eventSeq"]):
            continue
        future = [method for seq, method in methods_by_lane[entry["laneId"]]
                  if seq > row["eventSeq"]][:method_window]
        if future:
            raw_signatures[row["occurrenceAddress"]] = set(future)
    count = len(raw_signatures)
    if count < 3:
        return {}
    frequency = Counter(method for methods in raw_signatures.values()
                        for method in methods)
    minimum = max(2, math.ceil(count * 0.04))
    maximum = math.floor(count * 0.80)
    return {address: {method for method in methods
                      if minimum <= frequency[method] <= maximum}
            for address, methods in raw_signatures.items()}


def _continuation_distance(left: set[str], right: set[str],
                           frequency: Counter[str], count: int) -> int:
    if not left or not right:
        return 0
    union = left | right
    total = sum(math.log((count + 1) / (frequency[method] + 1))
                for method in union)
    if total <= 0:
        return 0
    common = sum(math.log((count + 1) / (frequency[method] + 1))
                 for method in left & right)
    return round(1000 * (1 - common / total))


def select_target_occurrences(receipt: dict[str, Any], *, max_anchors: int = 4,
                              round_index: int = 0,
                              prior_graphs: dict[str, dict[str, Any]] | None = None,
                              typed_doors: list[dict[str, Any]] | None = None,
                              signatures: dict[str, set[str]] | None = None
                              ) -> list[dict[str, Any]]:
    """Sample first/quantile/last target activations, rotating across rounds.

    Previously finalized graphs may promote an activation inside its temporal
    quantile neighborhood.  A graph lacking the original Finalizer authority
    or exact selected address is ignored, never treated as closure evidence.
    """
    if (not isinstance(max_anchors, int) or isinstance(max_anchors, bool) or
            not 1 <= max_anchors <= 16 or
            not isinstance(round_index, int) or isinstance(round_index, bool) or
            round_index < 0):
        raise ValueError("bounded anchor count and nonnegative round required")
    rows = _candidate_rows(receipt)
    count = min(max_anchors, len(rows))
    if count == 1:
        indices = [round_index % len(rows)]
    else:
        # The first round covers the full lifetime of the unchanged workload.
        # Later rounds advance every quantile without changing static checks.
        indices = [((len(rows) - 1) * i + (count - 1) // 2) // (count - 1)
                   for i in range(count)]
        indices = [(index + round_index) % len(rows) for index in indices]
    prior_graphs = prior_graphs or {}
    typed_doors = typed_doors or []
    signatures = signatures or {}
    frequency = Counter(method for methods in signatures.values()
                        for method in methods)
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    radius = max(1, len(rows) // (2 * count))
    for center in indices:
        neighborhood = [rows[(center + offset) % len(rows)]
                        for offset in range(-radius, radius + 1)]

        def score(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
            address = row["occurrenceAddress"]
            graph = prior_graphs.get(address, {})
            target_evidence = graph.get("targetEvidence")
            trusted = (graph.get("closureMembershipAuthority") ==
                       "original_runtime_selected_region_finalizer" and
                       isinstance(target_evidence, dict) and
                       target_evidence.get("selectedOccurrenceAddress") == address)
            closure = graph.get("closureOccurrenceIds", []) if trusted else []
            # Only exact Finalizer output can change priority.  Quantile
            # proximity breaks ties so the initial round is reproducible.
            evidence = len(closure) if isinstance(closure, list) else 0
            signature = signatures.get(address, set())
            diversity = (min(_continuation_distance(
                signature, signatures.get(earlier, set()), frequency,
                len(signatures)) for earlier in used)
                if used and signature else 0)
            # Compare only the same actor's native VM event clock.  The
            # fault-receipt `seq` is a different clock and is never used.
            nearest_door = min((row["eventSeq"] - door["nativeVmEventId"]
                for door in typed_doors if
                door.get("kind") == "FAULT_DOOR" and
                isinstance(door.get("siteId"), str) and door["siteId"] and
                isinstance(door.get("exceptionClass"), str) and
                door["exceptionClass"] and
                isinstance(door.get("nativeVmEventId"), int) and
                not isinstance(door["nativeVmEventId"], bool) and
                0 < door["nativeVmEventId"] < row["eventSeq"] and
                (f"{door.get('node')}#epoch{door.get('actorEpochOrdinal')}" ==
                 row["sourceKey"])), default=None)
            door_evidence = (0 if nearest_door is None else
                             max(1, 1000000 - nearest_door))
            position = rows.index(row)
            distance = min((position - center) % len(rows),
                           (center - position) % len(rows))
            return (evidence, diversity, door_evidence, -distance,
                    -row["eventSeq"], address)

        available = [row for row in neighborhood if
                     row["occurrenceAddress"] not in used]
        if not available:
            available = [row for row in rows if
                         row["occurrenceAddress"] not in used]
        selected = max(available, key=score)
        used.add(selected["occurrenceAddress"])
        chosen.append({"occurrenceAddress": selected["occurrenceAddress"],
                       "eventSeq": selected["eventSeq"],
                       "sourceKey": selected["sourceKey"],
                       "quantileIndex": center})
    return chosen


def record_multiple_region_states(trace_dir: Path, output_dir: Path, *,
                                  max_anchors: int = 4, round_index: int = 0,
                                  prior_graphs: dict[str, dict[str, Any]] | None = None,
                                  **recording: Any) -> dict[str, Any]:
    """Discover anchors on a healthy trace and run one original graph each.

    Faulted traces must use :func:`record_pinned_region_states` with this
    healthy bundle; rediscovering anchors after injection would compare
    different dynamic contexts and invalidate graph deltas.
    """
    if "target_occurrence" in recording:
        raise ValueError("multi-target selection cannot override an exact pin")
    output_dir = Path(output_dir)
    initial_dir = output_dir / "initial"
    initial = record_region_state(trace_dir, initial_dir, **recording)
    receipt_file = initial_dir / "target-occurrence.json"
    if not receipt_file.is_file():
        return {"schemaVersion": 1, "status": initial.get("status"),
                "initial": initial, "anchors": []}
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    fault_events = Path(recording["fault_events"])
    with fault_events.open(encoding="utf-8") as stream:
        typed_doors = [json.loads(line) for line in stream if line.strip()]
    signatures = continuation_signatures(trace_dir, receipt)
    candidates = select_target_occurrences(
        receipt, max_anchors=max_anchors, round_index=round_index,
        prior_graphs=prior_graphs, typed_doors=typed_doors,
        signatures=signatures)
    anchors = []
    for index, candidate in enumerate(candidates):
        anchor_dir = output_dir / f"anchor-{index:02d}"
        summary = record_region_state(
            trace_dir, anchor_dir,
            target_occurrence=candidate["occurrenceAddress"], **recording)
        evidence = summary.get("targetEvidence", {})
        if summary.get("targetReached") and (
                summary.get("closureMembershipAuthority") !=
                "original_runtime_selected_region_finalizer" or
                evidence.get("selectedOccurrenceAddress") !=
                candidate["occurrenceAddress"]):
            raise ValueError("selected graph lost exact original closure authority")
        anchor_receipt = anchor_dir / "target-occurrence.json"
        if anchor_receipt.is_file():
            observed = json.loads(anchor_receipt.read_text(encoding="utf-8"))
            if (observed.get("requestedOccurrenceAddress") !=
                    candidate["occurrenceAddress"] or
                    observed.get("selectedOccurrenceAddress") !=
                    candidate["occurrenceAddress"]):
                raise ValueError("exact target resolver selected another activation")
        anchors.append({**candidate, "status": summary.get("status"),
                        "targetReached": summary.get("targetReached"),
                        "summary": summary,
                        "summarySha256": _sha(anchor_dir / "summary.json"),
                        "targetReceiptSha256": (_sha(anchor_receipt)
                                                if anchor_receipt.is_file() else None)})
    return {"schemaVersion": 1, "status": "multi_target_recorded",
            "initialSummarySha256": _sha(initial_dir / "summary.json"),
            "initialReceiptSha256": _sha(receipt_file),
            "roundIndex": round_index,
            "selectionEvidence": {"strategy":
                "bounded_continuation_idf_then_exact_original_graph",
                "methodWindow": 40, "signatureCount": len(signatures),
                "signatureSha256": hashlib.sha256(json.dumps(
                    {address: sorted(methods) for address, methods in
                     signatures.items()}, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()},
            "retryExactOccurrences": [row["occurrenceAddress"] for row in anchors
                                      if not row["targetReached"]],
            "anchors": anchors}


def record_pinned_region_states(trace_dir: Path, output_dir: Path, *,
                                healthy_bundle: dict[str, Any],
                                **recording: Any) -> dict[str, Any]:
    """Replay healthy exact anchors in a faulted trace without substitution.

    Missing addresses remain named retry requests.  Each present address
    must still pass the original Resolver, Recorder, and Finalizer authority
    checks before its graph can contribute feedback.
    """
    if "target_occurrence" in recording:
        raise ValueError("pinned replay cannot override a healthy anchor")
    healthy = healthy_bundle.get("anchors")
    if (healthy_bundle.get("schemaVersion") != 1 or
            not isinstance(healthy, list) or not healthy or
            len(healthy) > 16):
        raise ValueError("fault replay requires a bounded healthy anchor bundle")
    addresses = [row.get("occurrenceAddress") for row in healthy
                 if isinstance(row, dict)]
    if (len(addresses) != len(healthy) or
            any(not isinstance(address, str) or not address
                for address in addresses) or
            len(addresses) != len(set(addresses))):
        raise ValueError("healthy anchor bundle has invalid exact identities")
    for row in healthy:
        if not _authoritative_anchor(row):
            raise ValueError("healthy anchor lacks original exact closure authority")
    output_dir = Path(output_dir)
    anchors = []
    for index, address in enumerate(addresses):
        anchor_dir = output_dir / f"anchor-{index:02d}"
        summary = record_region_state(
            trace_dir, anchor_dir, target_occurrence=address, **recording)
        evidence = summary.get("targetEvidence", {})
        if summary.get("targetReached") and (
                summary.get("closureMembershipAuthority") !=
                "original_runtime_selected_region_finalizer" or
                evidence.get("selectedOccurrenceAddress") != address):
            raise ValueError("pinned graph lost exact original closure authority")
        receipt_file = anchor_dir / "target-occurrence.json"
        if receipt_file.is_file():
            actual = json.loads(receipt_file.read_text(encoding="utf-8"))
            if (actual.get("requestedOccurrenceAddress") != address or
                    actual.get("selectedOccurrenceAddress") != address):
                raise ValueError("pinned Resolver substituted another activation")
        anchors.append({"occurrenceAddress": address,
                        "status": summary.get("status"),
                        "targetReached": summary.get("targetReached"),
                        "summary": summary,
                        "summarySha256": _sha(anchor_dir / "summary.json"),
                        "targetReceiptSha256": (_sha(receipt_file)
                                                if receipt_file.is_file() else None)})
    missing = [row["occurrenceAddress"] for row in anchors
               if not row["targetReached"]]
    return {"schemaVersion": 1,
            "status": "retry_exact_missing" if missing else "pinned_recorded",
            "healthyAnchorAddresses": addresses,
            "retryExactOccurrences": missing,
            "anchors": anchors}


def delta_matching_anchors(healthy: dict[str, Any], faulted: dict[str, Any]
                           ) -> dict[str, dict[str, Any]]:
    """Compare only identical exact target addresses across two executions."""
    baseline = {row["occurrenceAddress"]: row for row in healthy["anchors"]}
    result = {}
    for row in faulted["anchors"]:
        address = row["occurrenceAddress"]
        if address in baseline and row["targetReached"] and baseline[address][
                "targetReached"]:
            if not _authoritative_anchor(row) or not _authoritative_anchor(
                    baseline[address]):
                raise ValueError("cross-run graph lacks exact closure authority")
            result[address] = delta_region_state(baseline[address]["summary"],
                                                 row["summary"])
    return result


def _authoritative_anchor(row: dict[str, Any]) -> bool:
    summary = row.get("summary")
    return (row.get("targetReached") is True and
            isinstance(summary, dict) and
            summary.get("targetReached") is True and
            summary.get("closureMembershipAuthority") ==
            "original_runtime_selected_region_finalizer" and
            isinstance(summary.get("targetEvidence"), dict) and
            summary["targetEvidence"].get("selectedOccurrenceAddress") ==
            row.get("occurrenceAddress"))
