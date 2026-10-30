"""Fault points: their runtime identity, typed variants and exact matching.

A fault point is one observed execution of a selected I/O callsite:
``{marker, siteId, occurrence, hitOrdinal}`` plus optional ``phase``
("after" for a completed call whose reply is lost), ``occurrenceOrdinal``,
``sourceKey`` (the I/O call it wraps), ``responseShape`` and
``exceptionClass``. A sequence is an ordered list of fault points.
"""

from __future__ import annotations

import re
from typing import Any

from .trace import TRACE_SCHEMA, fingerprint

FAULT_EVENTS = {"FAULT_POINT_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"}
ZOOKEEPER_CONNECTION_LOSS = "org.apache.zookeeper.KeeperException$ConnectionLossException"
ZOOKEEPER_CALLERS = ("org.apache.solr.common.cloud.SolrZkClient:",
                     "org.apache.zookeeper.ZooKeeper:")

Point = dict[str, Any]
Sequence = list[Point]


# --- reading points from the trace ---------------------------------------

def point_from_event(event: dict[str, Any]) -> Point | None:
    """The fault point an agent event names, or None when it is not exact."""
    if event.get("identityGap") is True:
        return None
    marker = event.get("marker", "")
    site = event.get("siteId", "")
    address = event.get("occurrenceAddress", "")
    ordinal = event.get("hitOrdinal", 0)
    occurrence_ordinal = event.get("occurrenceOrdinal")
    phase = event.get("phase", "before")
    if (event.get("event") not in FAULT_EVENTS or
            event.get("schemaVersion") != TRACE_SCHEMA or
            not isinstance(marker, str) or not marker.startswith("FAULT:") or
            not isinstance(site, str) or "#u" not in site or
            not isinstance(address, str) or not address.strip() or
            not isinstance(phase, str) or phase not in {"before", "after"} or
            not isinstance(ordinal, int) or ordinal < 1 or
            (occurrence_ordinal is not None and
             (not isinstance(occurrence_ordinal, int) or
              isinstance(occurrence_ordinal, bool) or occurrence_ordinal < 1))):
        return None
    point = {"marker": marker, "siteId": site,
             "occurrence": address, "hitOrdinal": ordinal}
    # A before-phase point carries no phase key, so its fingerprint is stable.
    if phase == "after":
        point["phase"] = phase
    if occurrence_ordinal is not None:
        point["occurrenceOrdinal"] = occurrence_ordinal
    if event.get("sourceKey"):
        point["sourceKey"] = event["sourceKey"]
    response_shape = event.get("responseShape")
    if (phase == "after" and isinstance(response_shape, str)
            and 0 < len(response_shape) <= 1024):
        point["responseShape"] = response_shape
    if event.get("exceptionClass"):
        point["exceptionClass"] = event["exceptionClass"]
    return point


def in_io_scope(point: Point, scope: dict[str, Any] | None) -> bool:
    """A coarse static hint may reduce the I/O corpus; identity stays exact."""
    if not scope:
        return True
    prefixes = scope.get("marker_prefixes", [])
    sites = scope.get("site_ids", [])
    source_keys = scope.get("source_keys", [])
    source_prefixes = scope.get("source_key_prefixes", [])
    source_key = point.get("sourceKey", "")
    return ((not prefixes or any(point["marker"].startswith(p) for p in prefixes))
            and (not sites or point["siteId"] in sites)
            and (not source_keys or source_key in source_keys)
            and (not source_prefixes or any(source_key.startswith(p)
                                            for p in source_prefixes)))


# --- which exception a fault throws ---------------------------------------

def _zookeeper_call(point: Point) -> bool:
    source = point.get("sourceKey", "")
    return any(caller in source for caller in ZOOKEEPER_CALLERS)


def fault_point_for_io(point: Point) -> Point:
    """The transport failure this callsite and phase understand.

    ZooKeeper calls lose their connection; everything else gets the agent's
    default IOException. After a completed call only a lost reply makes
    sense, never a callee-side rejection.
    """
    if point.get("phase") == "after":
        return {**point, "exceptionClass": (ZOOKEEPER_CONNECTION_LOSS
                                            if _zookeeper_call(point)
                                            else "java.io.IOException")}
    if _zookeeper_call(point):
        return {**point, "exceptionClass": ZOOKEEPER_CONNECTION_LOSS}
    return point


def fault_variants_for_io(point: Point,
                          static_exceptions: dict[str, list[str]] | None = None
                          ) -> list[Point]:
    """Typed failures a callsite declares before the call; reply loss after."""
    base = fault_point_for_io(point)
    variants = [base]
    if point.get("phase") == "after":
        return variants
    for name in (static_exceptions or {}).get(point["siteId"], []):
        typed = {**point, "exceptionClass": name}
        if typed not in variants:
            variants.append(typed)
    return variants


# --- replayable identity ----------------------------------------------------

def stable_occurrence(address: str) -> str:
    """An occurrence address with per-JVM names (ports, hashes, ids) masked."""
    node_end = address.find("/")
    site_start = address.rfind("/<")
    if node_end < 0 or site_start <= node_end:
        return address
    actor = address[node_end + 1:site_start]
    if actor.startswith("BP-") and " heartbeating to " in actor:
        actor = "BPServiceActor heartbeating"
    actor = re.sub(r"@[0-9a-fA-F]{3,}", "@instance", actor)
    actor = re.sub(r"\bDFSClient_[A-Z_]+-?[0-9]+_[0-9]+\b", "DFSClient_instance", actor)
    actor = re.sub(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                   "uuid", actor)
    actor = re.sub(r"\bBP-[0-9]+-[^\s:]+-[0-9]+\b", "BP-instance", actor)
    actor = re.sub(r"\bblk_[0-9]+_[0-9]+\b", "blk-instance", actor)
    actor = re.sub(r"\b([A-Za-z][A-Za-z0-9]*Thread)-[0-9]{10,}\b", r"\1-instance", actor)
    actor = re.sub(
        r"(?i)(\b(?:[a-z][a-z0-9_.-]*|(?:[0-9]{1,3}\.){3}[0-9]{1,3})):[0-9]{2,5}(?![0-9.])",
        r"\1:port", actor)
    actor = re.sub(r"(\[[0-9a-fA-F:]+\]):[0-9]{2,5}\b", r"\1:port", actor)
    actor = re.sub(r"(?i)\b(localhost|127\.0\.0\.1)/[0-9]{2,5}\b", r"\1/port", actor)
    actor = re.sub(r"\bport=[0-9]{2,5}\b", "port=port", actor)
    actor = re.sub(r"\bport\s+[0-9]{2,5}\b", "port port", actor)
    # A run of ten or more digits is a per-run identifier (a ZooKeeper session id,
    # a hash code, a timestamp), never a stable name (the agent masks it alike).
    actor = re.sub(r"(?<![0-9])[0-9]{10,}(?![0-9])", "id", actor)
    # The JVM names an unnamed thread Thread-<n>, n counting every unnamed thread made
    # before it: no role; its calls of one site are told apart by occurrenceOrdinal.
    actor = re.sub(r"^Thread-[0-9]+(?=\||$)", "Thread-anonymous", actor)
    return address[:node_end + 1] + actor + address[site_start:]


def sequence_id(sequence: Sequence) -> str:
    return fingerprint(sequence)


def actor_of(point: Point) -> str:
    """The runtime actor of an occurrence: the address before its site."""
    return point["occurrence"].rsplit("/<", 1)[0]


# --- did the trial apply exactly what was asked? ----------------------------

def strict_injection(result: dict[str, Any], sequence: Sequence) -> bool:
    """Every requested selector applied in order (any order for a fanout)."""
    expected = [fingerprint(point) for point in sequence]

    def stable(point: Point, requested: Point) -> Point:
        normalized = {**point, "occurrence": stable_occurrence(point["occurrence"])}
        if normalized.get("phase", "before") == "before":
            normalized.pop("phase", None)
        # A selector without occurrenceOrdinal matches regardless of it.
        if "occurrenceOrdinal" not in requested:
            normalized.pop("occurrenceOrdinal", None)
        return normalized

    observed = result.get("applied_points", [])
    if independent_reply_fanout(sequence):
        applied_ids = result.get("applied_fault_ids", [])
        if (len(expected) != result.get("applied_count") or
                result.get("matched_count", 0) < len(expected) or
                len(observed) != len(sequence) or
                len(applied_ids) != len(expected) or
                sorted(applied_ids) != sorted(expected)):
            return False
        requested_by_id = {fingerprint(point): point for point in sequence}
        return all(stable(actual, requested_by_id[fault_id]) ==
                   stable(requested_by_id[fault_id], requested_by_id[fault_id])
                   for actual, fault_id in zip(observed, applied_ids))
    return (len(expected) == result.get("applied_count") and
            result.get("matched_count", 0) >= len(expected) and
            len(observed) == len(sequence) and
            all(stable(actual, requested) == stable(requested, requested)
                for actual, requested in zip(observed, sequence)) and
            result.get("applied_fault_ids") == expected)


def strict_applied_prefix(result: dict[str, Any], sequence: Sequence) -> Sequence:
    """The exact realized prefix of a partially matched plan, else [].

    A later selector can vanish after an earlier fault; the run is then a
    valid shorter sequence when every applied point matches the requested
    prefix in order. An unordered fanout has no prefix.
    """
    count = result.get("applied_count", 0)
    if not isinstance(count, int) or not 0 < count < len(sequence):
        return []
    if independent_reply_fanout(sequence):
        return []
    prefix = sequence[:count]
    return prefix if strict_injection(result, prefix) else []


def retry_lost_target(result: dict[str, Any], sequence: Sequence,
                      attempt: int, max_retries: int) -> bool:
    """Retry a matched multi-fault plan whose last fault came after the check."""
    return (len(sequence) > 1 and attempt <= max_retries and
            strict_injection(result, sequence) and
            result.get("target_reached", False) and
            not result.get("target_reached_after_fault", False))


# --- grouping keys -----------------------------------------------------------

def fault_family(point: Point) -> str:
    """Stable fault identity; protocol exception types are distinct behaviors."""
    family = {key: point.get(key) for key in
              ("marker", "siteId", "sourceKey", "exceptionClass", "responseShape")}
    if point.get("phase") == "after":
        family["phase"] = "after"
    return fingerprint(family)


def _ordinal_bucket(point: Point) -> int:
    ordinal = point.get("hitOrdinal")
    return (min(ordinal.bit_length() - 1, 4)
            if isinstance(ordinal, int) and ordinal > 0 else 0)


def temporal_diversity_key(point: Point) -> tuple[str, int]:
    """A fault family and the logarithmic bucket of its hit ordinal.

    A callsite can execute before and after a distributed state change;
    buckets separate early and late calls without treating every heartbeat
    or retry as its own family.
    """
    return fault_family(point), _ordinal_bucket(point)


def temporal_site_key(point: Point) -> tuple[str, str, int]:
    """Repeat executions grouped by callsite, phase and coarse time bucket."""
    return point["siteId"], point.get("phase", "before"), _ordinal_bucket(point)


def exact_temporal_site_key(point: Point) -> tuple[str, str, int]:
    """Distinct late calls even when they share a logarithmic bucket."""
    return point["siteId"], point.get("phase", "before"), point.get("hitOrdinal", 1)


def observed_identity(point: Point) -> tuple[Any, ...]:
    """A recorded I/O call, independent of its typed fault variant."""
    return tuple(point.get(key) for key in
                 ("siteId", "occurrence", "hitOrdinal", "occurrenceOrdinal",
                  "phase", "sourceKey", "responseShape"))


# --- shapes of fault sequences the scheduler gives bounded shares ------------

def object_array_response(point: Point) -> bool:
    """A lost reply whose returned object holds an object-array field."""
    shape = point.get("responseShape")
    if not isinstance(shape, str) or point.get("phase") != "after":
        return False
    return any(value.startswith("[") and value != "[]"
               for field in shape.split("|")[1:]
               for _, separator, value in [field.partition("=")]
               if separator)


def repeated_reply_loss(sequence: Sequence) -> bool:
    """The last two faults lose later replies of one actor at one callsite."""
    if len(sequence) < 2:
        return False
    first, second = sequence[-2:]
    return (first.get("phase") == second.get("phase") == "after" and
            first["siteId"] == second["siteId"] and
            actor_of(first) == actor_of(second) and
            second.get("hitOrdinal", 0) > first.get("hitOrdinal", 0))


def consecutive_reply_streak(sequence: Sequence) -> int:
    """Length of a chain losing adjacent replies of one actor and callsite."""
    if len(sequence) < 2 or any(point.get("phase") != "after" for point in sequence):
        return 0
    actor = actor_of(sequence[0])
    site = sequence[0]["siteId"]
    if any(point["siteId"] != site or actor_of(point) != actor for point in sequence):
        return 0
    ordinals = [point.get("hitOrdinal", 0) for point in sequence]
    return (len(sequence) if all(b == a + 1 for a, b in zip(ordinals, ordinals[1:]))
            else 0)


def same_actor_followup(sequence: Sequence) -> bool:
    """The last fault interrupts a different I/O of the previous fault's actor."""
    if len(sequence) < 2:
        return False
    first, second = sequence[-2:]
    return first["siteId"] != second["siteId"] and actor_of(first) == actor_of(second)


def fault_actors(sequence: Sequence) -> tuple[str, ...]:
    """The logical nodes a sequence touches.

    The actor suffix after ``|`` names the logical node, so a heartbeat
    thread and a DataXceiver of one DataNode count once; actors without the
    suffix count as themselves.
    """
    return tuple(sorted({actor_of(point).rsplit("|", 1)[-1] for point in sequence}))


def confirmed_fault_nodes(sequence: Sequence) -> tuple[str, ...]:
    """The logical nodes a sequence names explicitly (``actor|node``)."""
    nodes = set()
    for point in sequence:
        actor = actor_of(point)
        if "|" in actor:
            nodes.add(actor.rsplit("|", 1)[1])
    return tuple(sorted(nodes))


def reply_fanout_degree(sequence: Sequence) -> int:
    """How many known nodes lose the same callsite's object-array reply.

    A command-like reply can update several nodes independently; losing it
    on one node may leave the others to repair the operation.
    """
    groups: dict[tuple[str, str], set[str]] = {}
    for point in sequence:
        if not object_array_response(point):
            continue
        actor = actor_of(point)
        if "|" not in actor:
            continue
        groups.setdefault((point["siteId"], point["responseShape"]), set()).add(
            actor.rsplit("|", 1)[1])
    return max((len(nodes) for nodes in groups.values()), default=0)


def repeated_nonempty_reply_profile(sequence: Sequence) -> tuple[int, int]:
    """(distinct lost state-bearing replies on one node, their latest ordinal).

    A later successful reply can repair a lost state update before another
    actor uses it.
    """
    groups: dict[tuple[str, str, str, str], set[int]] = {}
    for point in sequence:
        if not object_array_response(point):
            continue
        actor = point.get("occurrence", "").rsplit("/<", 1)[0]
        if "|" not in actor:
            continue
        ordinal = point.get("hitOrdinal")
        if not isinstance(ordinal, int) or ordinal <= 0:
            continue
        key = (point["siteId"], point.get("sourceKey", ""), point["responseShape"],
               actor.rsplit("|", 1)[1])
        groups.setdefault(key, set()).add(ordinal)
    return max(((len(ordinals), max(ordinals)) for ordinals in groups.values()),
               default=(0, 0))


def logical_node(point: Point) -> str:
    """An occurrence's logical node: its actor's ``|node`` suffix, else the actor."""
    return actor_of(point).split("/", 1)[-1].rsplit("|", 1)[-1]


def concurrent_calls(sequence: Sequence) -> bool:
    """A whole plan failing one call site before the call, each fault on a distinct node.

    Every node makes that call for the same event (each node's watch on one
    changed store node fires), concurrently: which comes first is a race, not
    part of the plan, so its faults apply in any order (the agent alike).
    """
    if len(sequence) < 2:
        return False
    fields = ("marker", "siteId", "sourceKey", "exceptionClass")
    family = tuple(sequence[0].get(field) for field in fields)
    nodes = [logical_node(point) for point in sequence]
    return (all(point.get("phase", "before") == "before" and
                tuple(point.get(field) for field in fields) == family for point in sequence) and
            len(set(nodes)) == len(nodes))


def independent_reply_fanout(sequence: Sequence) -> bool:
    """A plan without an order of its own: one reply shape lost on distinct known nodes,
    or one call failed on distinct nodes (``concurrent_calls``)."""
    if concurrent_calls(sequence):
        return True
    if len(sequence) < 2 or not all(object_array_response(p) for p in sequence):
        return False
    fields = ("marker", "siteId", "sourceKey", "exceptionClass", "phase", "responseShape")
    family = tuple(sequence[0].get(field) for field in fields)
    nodes: set[str] = set()
    for point in sequence:
        if tuple(point.get(field) for field in fields) != family:
            return False
        actor, separator, _ = point.get("occurrence", "").rpartition("/<")
        if not separator or "|" not in actor:
            return False
        node = actor.rsplit("|", 1)[1]
        if not node or node in nodes:
            return False
        nodes.add(node)
    return True
