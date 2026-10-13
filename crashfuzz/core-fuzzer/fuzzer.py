#!/usr/bin/env python3
"""Resumable, target-guided fault trials over one original cluster JUnit test.

The coverage_io mode uses observed I/O and method/branch coverage to explore
fault sequences. It uses exact runtime fault selectors and the same workload
for every trial.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from soot_selection import prepare as prepare_static_selection

SCHEMA = 1
TRACE_SCHEMA = 3
FAULT_EVENTS = {"FAULT_POINT_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"}
TERMINAL = {"quality_complete", "no_cluster_test", "source_excluded",
            "confirmed_bug"}


def rows(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    # A timed-out JVM can be terminated while writing its
                    # final event. All earlier newline-terminated events are
                    # still valid feedback for this attempted trial.
                    if not line.endswith("\n"):
                        return
                    raise ValueError(f"{path}:{number}: {exc}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{number}: expected JSON object")
                yield row


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        if path.name == "state.json":
            # The resumable queue can contain tens of thousands of observed
            # fault sequences. Compact checkpoints avoid repeatedly writing
            # the same large indentation buffer after every trial.
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        else:
            json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def fingerprint(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def fatal_guard_paths(target: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Alternative bytecode routes to one selected throw site.

    Each route is an ordered conjunction of branch outcomes; the routes are
    disjunctive. A TARGET_SITE scope-map row supplies one route unless a case
    provides independently checked alternatives.
    """
    paths = (target.get("fatal_guard_paths") if "fatal_guard_paths" in target
             else [target.get("fatal_guards")])
    if not isinstance(paths, list) or not paths:
        raise ValueError("target needs nonempty fatal guard paths")
    for path in paths:
        if not isinstance(path, list) or not path:
            raise ValueError("each fatal guard path must be nonempty")
        for guard in path:
            if (not isinstance(guard, dict) or
                    not isinstance(guard.get("siteId"), str) or
                    "#u" not in guard["siteId"] or
                    not isinstance(guard.get("outcome"), bool)):
                raise ValueError("each fatal guard needs siteId and boolean outcome")
    return paths


def point_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
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
    # Keep existing before-phase fingerprints and checkpoints replayable.
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


def fault_point_for_io(point: dict[str, Any]) -> dict[str, Any]:
    """Select a transport failure understood at this callsite and phase."""
    source = point.get("sourceKey", "")
    if point.get("phase") == "after":
        # A successful call may lose its reply, but cannot be changed into a
        # callee-side protocol rejection after the callee has accepted it.
        return {**point, "exceptionClass": (
            "org.apache.zookeeper.KeeperException$ConnectionLossException"
            if ("org.apache.solr.common.cloud.SolrZkClient:" in source or
                "org.apache.zookeeper.ZooKeeper:" in source)
            else "java.io.IOException")}
    if ("org.apache.solr.common.cloud.SolrZkClient:" in source or
            "org.apache.zookeeper.ZooKeeper:" in source):
        return {**point, "exceptionClass":
                "org.apache.zookeeper.KeeperException$ConnectionLossException"}
    return point


def fault_variants_for_io(point: dict[str, Any],
                          static_exceptions: dict[str, list[str]] | None = None
                          ) -> list[dict[str, Any]]:
    """Try typed failures before calls; use only reply loss after calls."""
    base = fault_point_for_io(point)
    variants = [base]
    if point.get("phase") == "after":
        return variants
    for name in (static_exceptions or {}).get(point["siteId"], []):
        typed = {**point, "exceptionClass": name}
        if typed not in variants:
            variants.append(typed)
    return variants


def in_io_scope(point: dict[str, Any], scope: dict[str, Any] | None) -> bool:
    """A coarse static hint may reduce the I/O corpus; identity remains exact."""
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


def trace_feedback(path: Path, target: dict[str, Any],
                   io_scope: dict[str, Any] | None = None) -> dict[str, Any]:
    target_occurrence = target.get("occurrence")
    points: dict[str, dict[str, Any]] = {}
    point_events: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    coverage: set[str] = set()
    target_reached = False
    target_reached_after_fault = False
    target_after_fault = False
    target_exception = False
    target_exception_count = 0
    target_fatal_exception_count = 0
    target_fatal_exception_nodes: list[dict[str, Any]] = []
    target_site_seen = False
    target_site_after_fault = False
    target_guard_seen = False
    target_guard_after_fault = False
    exceptions: list[dict[str, Any]] = []
    target_calls: set[int] = set()
    call_parents: dict[int, int] = {}
    target_entries: dict[int, int] = {}
    target_exits: dict[int, int] = {}
    summary: dict[str, Any] = {}
    static_selection_digests: list[str] = []
    throw_event = target.get("throw_event", "METHOD_EXIT_THROW")
    explicit_throw_lines = set(target.get("explicit_throw_lines", []))
    coverage_exclude_sites = set(target.get("coverage_exclude_sites", []))
    coverage_include_prefixes = target.get("coverage_include_prefixes", [])
    coverage_include_methods = set(target.get("coverage_include_methods", []))

    def coverage_in_scope(event: dict[str, Any]) -> bool:
        method = event.get("method") or event.get("siteId", "").split("#u", 1)[0]
        if coverage_include_methods:
            return isinstance(method, str) and method in coverage_include_methods
        if not coverage_include_prefixes:
            return True
        return isinstance(method, str) and any(
            method.startswith(prefix) for prefix in coverage_include_prefixes)

    events = list(rows(path))
    for event in events:
        kind = event.get("event")
        if kind in FAULT_EVENTS:
            point = point_from_event(event)
            if point and in_io_scope(point, io_scope):
                points[fingerprint(point)] = point
                if kind == "FAULT_POINT_OBSERVED":
                    point_events.append({"point": point, "seq": event.get("seq", -1)})
            if kind == "FAULT_MATCHED":
                matched.append(event)
            if kind == "FAULT_APPLIED":
                applied.append(event)
        elif kind == "FAULT_TRIAL_SUMMARY":
            summary = event
        elif kind == "STATIC_SELECTION_APPLIED":
            static_selection_digests.append(event.get("digest"))
        elif kind == "METHOD_ENTER":
            call_id = event.get("callId")
            if isinstance(call_id, int):
                call_parents[call_id] = event.get("parentCallId", 0)
            method = event.get("method")
            if method and coverage_in_scope(event):
                coverage.add("METHOD:" + method)
            if (method == target["method"] and
                    isinstance(call_id, int)):
                target_entries[call_id] = event.get("seq", -1)
            if (method == target["method"] and
                    (not target_occurrence or
                     event.get("occurrenceAddress") == target_occurrence) and
                    isinstance(call_id, int)):
                target_reached = True
                target_calls.add(call_id)
        elif kind == "BRANCH":
            site = event.get("siteId")
            if site and site not in coverage_exclude_sites and coverage_in_scope(event):
                coverage.add("BRANCH:" + site + ":" + str(event.get("outcome")))
        elif kind in {"CALL_SITE_ENTER", "CALL_SITE_RETURN", "CALL_SITE_THROW"}:
            site = event.get("siteId")
            if site and site not in coverage_exclude_sites and coverage_in_scope(event):
                coverage.add("CALL_SITE:" + site + ":" + kind)
        if kind == throw_event:
            if (event.get("method") == target.get("throw_method", target["method"])
                    and (throw_event != "EXPLICIT_THROW" or
                         ((target.get("explicit_throw_site_id") is None or
                           event.get("siteId") == target["explicit_throw_site_id"]) and
                          (not explicit_throw_lines or
                           event.get("sourceLine") in explicit_throw_lines)))):
                exceptions.append(event)
        if (kind in {"METHOD_EXIT_NORMAL", "METHOD_EXIT_THROW"} and
                event.get("method") == target["method"] and
                isinstance(event.get("callId"), int)):
            target_exits[event["callId"]] = event.get("seq", -1)
    def target_call_owner(call_id: Any) -> int | None:
        seen: set[int] = set()
        while isinstance(call_id, int) and call_id > 0 and call_id not in seen:
            if call_id in target_calls:
                return call_id
            seen.add(call_id)
            call_id = call_parents.get(call_id)
        return None

    def in_target_call(call_id: Any) -> bool:
        return target_call_owner(call_id) is not None

    def target_owner(event: dict[str, Any]) -> int | None:
        owner = target_call_owner(event.get("callId"))
        if owner is not None:
            return owner
        if event.get("method") != target["method"]:
            return None
        seq = event.get("seq", -1)
        enclosing = [call_id for call_id, entered in target_entries.items()
                     if entered <= seq <= target_exits.get(call_id, float("inf"))]
        return enclosing[0] if len(enclosing) == 1 and enclosing[0] in target_calls else None

    def in_target_event(event: dict[str, Any]) -> bool:
        if target_owner(event) is not None:
            return True
        # Some recorder hooks emit callId=0 for bytecode events. The exact
        # method and site still identify the selected check when no runtime
        # occurrence restriction was requested.
        if event.get("method") != target["method"]:
            return False
        if not target_occurrence or event.get("occurrenceAddress") == target_occurrence:
            return True
        return False

    call_site_enters: dict[tuple[Any, ...], list[int]] = {}
    for event in events:
        if (event.get("event") == "CALL_SITE_ENTER" and
                isinstance(event.get("invocationId"), int) and
                event["invocationId"] > 0):
            key = (event.get("method"), event.get("siteId"),
                   event["invocationId"], event.get("sourceKey"),
                   event.get("tid"))
            call_site_enters.setdefault(key, []).append(event.get("seq", -1))

    def paired_call_site(event: dict[str, Any]) -> bool:
        if event.get("event") == "CALL_SITE_ENTER":
            return isinstance(event.get("invocationId"), int) and event["invocationId"] > 0
        invocation = event.get("invocationId")
        key = (event.get("method"), event.get("siteId"), invocation,
               event.get("sourceKey"), event.get("tid"))
        return (isinstance(invocation, int) and invocation > 0 and
                any(seq < event.get("seq", -1)
                    for seq in call_site_enters.get(key, [])))

    applied_seq = max((e.get("seq", -1) for e in applied), default=-1)
    guard_paths = (fatal_guard_paths(target) if
                   ("fatal_guard_paths" in target or "fatal_guards" in target)
                   else [])
    configured_check_sites = target.get("check_site_ids") or []
    # Earlier guards can merely enter the function or an outer branch. The
    # final decision on a throw route is the selected check to retain after
    # the fault; Solr's alternative routes end at different branch sites.
    check_sites = (set(configured_check_sites) or
                   {path[-1]["siteId"] for path in guard_paths} or
                   ({target["site_id"]} if target.get("site_id") else set()))
    check_events = set(target.get("check_events", ["BRANCH"] if
                                  check_sites else []))
    branch_rows = sorted((e for e in events if e.get("event") == "BRANCH"),
                         key=lambda e: e.get("seq", -1))

    def path_last_seq(path: list[dict[str, Any]], call_id: Any,
                      upper_seq: int) -> int | None:
        """Latest final decision of a complete ordered route before throw."""
        cursors = {-1}
        for guard in path:
            cursors = {e["seq"] for e in branch_rows
                       if e.get("callId") == call_id and
                       e.get("siteId") == guard["siteId"] and
                       e.get("outcome") is guard["outcome"] and
                       isinstance(e.get("seq"), int) and
                       e["seq"] < upper_seq and
                       any(previous < e["seq"] for previous in cursors)}
            if not cursors:
                return None
        return max(cursors)

    check_rows = [e for e in events
                  if e.get("event") in check_events and
                  e.get("siteId") in check_sites and
                  in_target_event(e) and
                  (not e["event"].startswith("CALL_SITE_") or
                   paired_call_site(e))]
    target_site_seen = bool(check_rows)
    target_guard_seen = any(
        e.get("event") == "BRANCH" and
        e.get("siteId") in check_sites and
        in_target_event(e) for e in events) or target_site_seen
    # A target invocation that happened only before the injected fault cannot
    # validate this trial. The check itself must execute again after the last
    # applied fault, including when its method was entered before that fault.
    target_reached_after_fault = (
        any(e.get("seq", -1) > applied_seq >= 0 for e in check_rows)
        if check_events else
        any(e.get("event") in {"METHOD_ENTER", "BRANCH", "METHOD_EXIT_NORMAL",
                                  "METHOD_EXIT_THROW", "EXPLICIT_THROW"} and
            in_target_event(e) and e.get("seq", -1) > applied_seq >= 0
            for e in events))
    target_reached = target_site_seen if check_sites else target_reached
    if check_sites:
        target_site_after_fault = target_reached_after_fault

    def check_outcome(event: dict[str, Any]) -> Any:
        return (event.get("outcome") if event.get("event") == "BRANCH" else
                event.get("event"))

    target_outcomes = [check_outcome(e) for e in check_rows]
    target_outcomes_after_fault = [check_outcome(e) for e in check_rows
                                   if e.get("seq", -1) > applied_seq >= 0]
    required_throw_site = target.get("throw_site_id")
    if not required_throw_site and "CALL_SITE_THROW" in check_events:
        required_throw_site = target.get("site_id")
    site_throws = [e for e in events
                   if e.get("event") == "CALL_SITE_THROW" and
                   e.get("siteId") == required_throw_site and
                   in_target_event(e) and paired_call_site(e)]
    expected = target["exception_type"]

    def expected_type_seen(thrown: dict[str, Any]) -> bool:
        if expected is None:
            return False
        if thrown.get("runtimeType") == expected:
            return True
        if throw_event != "CALL_SITE_THROW":
            return False
        # The recorder's CALL_SITE_THROW currently carries no exception
        # class. Pair its invocation, then use the enclosing typed method
        # exit as the exception oracle.
        owner = target_owner(thrown)
        return owner is not None and any(
                   e.get("event") == "METHOD_EXIT_THROW" and
                   e.get("method") == target.get("throw_method", target["method"]) and
                   e.get("runtimeType") == expected and
                   target_owner(e) == owner and
                   e.get("seq", -1) > thrown.get("seq", -1)
                   for e in events)

    for thrown in exceptions:
        if (expected_type_seen(thrown) and in_target_event(thrown) and
                (throw_event != "CALL_SITE_THROW" or
                 (thrown.get("siteId") == required_throw_site and
                  paired_call_site(thrown)))):
            target_exception = True
            target_exception_count += 1
            completed_paths = [path_last_seq(path, thrown.get("callId"),
                                             thrown.get("seq", -1))
                               for path in guard_paths]
            guard_ok = (any(last is not None for last in completed_paths)
                        if guard_paths else True)
            site_before_throw = [e for e in site_throws
                                 if e.get("seq", -1) <= thrown.get("seq", -1) and
                                 target_owner(e) == target_owner(thrown)]
            fatal_in_call = guard_ok and (
                bool(site_before_throw) if required_throw_site else True)
            if fatal_in_call:
                target_fatal_exception_count += 1
                if thrown.get("logicalNodeId"):
                    target_fatal_exception_nodes.append({
                        "seq": thrown.get("seq", -1),
                        "logicalNodeId": thrown["logicalNodeId"]})
            if thrown.get("seq", -1) > applied_seq >= 0:
                target_after_fault = True
                guard_after = (any(last is not None and last > applied_seq
                                   for last in completed_paths)
                               if guard_paths else target_reached_after_fault)
                site_after = (any(e.get("seq", -1) > applied_seq
                                  for e in site_before_throw)
                              if required_throw_site else True)
                if guard_after and site_after:
                    target_guard_after_fault = True
                # An exact bytecode throw is itself proof that the selected
                # check ran. A separate CHECK_REACHED hook may be absent or
                # name a different unit in this invocation; that must not
                # discard the observed target exception.
                if (throw_event == "EXPLICIT_THROW" and fatal_in_call and
                        (target.get("explicit_throw_site_id") or
                         explicit_throw_lines)):
                    target_reached = True
                    target_reached_after_fault = True
                    target_site_seen = True
                    target_site_after_fault = True
                    target_guard_seen = True
                    target_guard_after_fault = True
    # If an exact target site is declared, a method-level throw alone is
    # insufficient: it could simply propagate an unrelated nested failure.
    oracle = bool(target_after_fault and target_reached and
                  target_guard_after_fault)
    return {
        "points": list(points.values()),
        "point_events": point_events,
        "coverage": sorted(coverage),
        "matched_count": len(matched),
        "applied_count": len(applied),
        "last_applied_seq": max((e.get("seq", -1) for e in applied), default=-1),
        "applied_points": [p for e in applied
                           if (p := point_from_event(e)) is not None],
        "applied_fault_ids": [e.get("faultId") for e in applied],
        "target_reached": target_reached,
        "target_reached_after_fault": target_reached_after_fault,
        "target_site_seen": target_site_seen,
        "target_site_after_fault": target_site_after_fault,
        "target_outcomes": target_outcomes,
        "target_outcomes_after_fault": target_outcomes_after_fault,
        "target_check_seqs": [e.get("seq", -1) for e in check_rows],
        "target_check_nodes": [
            {"seq": e.get("seq", -1), "logicalNodeId": e["logicalNodeId"]}
            for e in check_rows if e.get("logicalNodeId")],
        "target_guard_seen": target_guard_seen,
        "target_guard_after_fault": target_guard_after_fault,
        "target_exception": target_exception,
        "target_exception_count": target_exception_count,
        "target_fatal_exception_count": target_fatal_exception_count,
        "target_fatal_exception_nodes": target_fatal_exception_nodes,
        "target_after_fault": target_after_fault,
        "oracle": oracle,
        "fault_summary": summary,
        "static_selection_digests": static_selection_digests,
    }


def sequence_id(sequence: list[dict[str, Any]]) -> str:
    return fingerprint(sequence)


def stable_occurrence(address: str) -> str:
    node_end = address.find("/")
    site_start = address.rfind("/<")
    if node_end < 0 or site_start <= node_end:
        return address
    actor = address[node_end + 1:site_start]
    if actor.startswith("BP-") and " heartbeating to " in actor:
        actor = "BPServiceActor heartbeating"
    actor = re.sub(r"@[0-9a-fA-F]{3,}", "@instance", actor)
    actor = re.sub(r"\bDFSClient_[A-Z_]+-?[0-9]+_[0-9]+\b", "DFSClient_instance", actor)
    actor = re.sub(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "uuid", actor)
    actor = re.sub(r"\bBP-[0-9]+-[^\s:]+-[0-9]+\b", "BP-instance", actor)
    actor = re.sub(r"\bblk_[0-9]+_[0-9]+\b", "blk-instance", actor)
    actor = re.sub(r"\b([A-Za-z][A-Za-z0-9]*Thread)-[0-9]{10,}\b",
                   r"\1-instance", actor)
    actor = re.sub(
        r"(?i)(\b(?:[a-z][a-z0-9_.-]*|(?:[0-9]{1,3}\.){3}[0-9]{1,3})):[0-9]{2,5}(?![0-9.])",
        r"\1:port", actor)
    actor = re.sub(r"(\[[0-9a-fA-F:]+\]):[0-9]{2,5}\b", r"\1:port", actor)
    actor = re.sub(r"(?i)\b(localhost|127\.0\.0\.1)/[0-9]{2,5}\b",
                   r"\1/port", actor)
    actor = re.sub(r"\bport=[0-9]{2,5}\b", "port=port", actor)
    actor = re.sub(r"\bport\s+[0-9]{2,5}\b", "port port", actor)
    return address[:node_end + 1] + actor + address[site_start:]


def strict_injection(result: dict[str, Any],
                     sequence: list[dict[str, Any]]) -> bool:
    """Prove every selector, allowing order only for independent fanout."""
    expected = [fingerprint(point) for point in sequence]
    def stable(point: dict[str, Any], requested: dict[str, Any]) -> dict[str, Any]:
        normalized = {**point, "occurrence": stable_occurrence(point["occurrence"])}
        if normalized.get("phase", "before") == "before":
            normalized.pop("phase", None)
        # Checkpoints made before occurrenceOrdinal existed still have a valid
        # exact actor/site/hit selector. The runtime reports the new field,
        # but it was not part of their requested fault identity.
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


def strict_applied_prefix(result: dict[str, Any],
                          sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the exact realized prefix of a partially matched fault plan.

    A later selector can disappear after an earlier fault. The observed
    execution is still a valid shorter fault sequence when every applied
    point matches the requested prefix in order. Never infer a prefix from
    only an applied count or from non-prefix matches.
    """
    count = result.get("applied_count", 0)
    if not isinstance(count, int) or not 0 < count < len(sequence):
        return []
    # A subset of an unordered fanout plan is not necessarily its prefix.
    if independent_reply_fanout(sequence):
        return []
    prefix = sequence[:count]
    return prefix if strict_injection(result, prefix) else []


def retry_lost_target(result: dict[str, Any], sequence: list[dict[str, Any]],
                      attempt: int, max_retries: int) -> bool:
    """Retry a matched multi-fault plan whose last fault passed the check."""
    return (len(sequence) > 1 and attempt <= max_retries and
            strict_injection(result, sequence) and
            result.get("target_reached", False) and
            not result.get("target_reached_after_fault", False))


def enqueue(state: dict[str, Any], sequence: list[dict[str, Any]],
            priority: int = 0, target_proximity: int = 0) -> None:
    # Old checkpoints stored these IDs in a list. Once the queue grows to
    # tens of thousands of observed I/O continuations, repeated list scans
    # dominate the campaign runtime. A JSON object keeps resumability and
    # gives constant-time duplicate checks.
    if isinstance(state["seen_sequences"], list):
        state["seen_sequences"] = dict.fromkeys(state["seen_sequences"], True)
    name = sequence_id(sequence)
    if name in state["seen_sequences"]:
        return
    state["seen_sequences"][name] = True
    state["queue"].append({"id": name, "sequence": sequence,
                           "priority": priority, "created": time.time(),
                           "target_proximity": target_proximity})


def fault_family(point: dict[str, Any]) -> str:
    """Stable fault identity; protocol exception types are distinct behaviors."""
    family = {key: point.get(key) for key in
              ("marker", "siteId", "sourceKey", "exceptionClass",
               "responseShape")}
    if point.get("phase") == "after":
        family["phase"] = "after"
    return fingerprint(family)


def object_array_response(point: dict[str, Any]) -> bool:
    """A returned object contains at least one object-array element class."""
    shape = point.get("responseShape")
    if not isinstance(shape, str) or point.get("phase") != "after":
        return False
    return any(value.startswith("[") and value != "[]"
               for field in shape.split("|")[1:]
               for _, separator, value in [field.partition("=")]
               if separator)


def temporal_diversity_key(point: dict[str, Any]) -> tuple[str, int]:
    """Distinguish early and later executions of a recurring I/O site.

    A single call stack can execute before and after a distributed state
    update.  Logarithmic buckets preserve CrashFuzz's call-stack grouping
    without treating every heartbeat or retry as a separate I/O family.
    """
    ordinal = point.get("hitOrdinal")
    bucket = (min(ordinal.bit_length() - 1, 4)
              if isinstance(ordinal, int) and ordinal > 0 else 0)
    return fault_family(point), bucket


def temporal_site_key(point: dict[str, Any]) -> tuple[str, str, int]:
    """Group repeat executions by callsite, phase, and coarse time bucket."""
    ordinal = point.get("hitOrdinal")
    bucket = (min(ordinal.bit_length() - 1, 4)
              if isinstance(ordinal, int) and ordinal > 0 else 0)
    return point["siteId"], point.get("phase", "before"), bucket


def observed_identity(point: dict[str, Any]) -> tuple[Any, ...]:
    """Match a recorded I/O call to its typed fault variants."""
    return tuple(point.get(key) for key in
                 ("siteId", "occurrence", "hitOrdinal", "occurrenceOrdinal",
                  "phase", "sourceKey", "responseShape"))


def target_proximity_score(io_seq: int, check_seqs: list[int]) -> int:
    """Give bounded preference to I/O immediately preceding a target check."""
    distance = min((check - io_seq for check in check_seqs if check > io_seq),
                   default=None)
    if distance is None:
        return 0
    if distance <= 64:
        return 80
    if distance <= 256:
        return 50
    if distance <= 1024:
        return 20
    return 0


def observed_proximity(feedback: dict[str, Any]) -> dict[tuple[Any, ...], int]:
    checks = feedback.get("target_check_seqs", [])
    scores: dict[tuple[Any, ...], int] = {}
    for observed in feedback.get("point_events", []):
        point = observed["point"]
        key = observed_identity(point)
        scores[key] = max(scores.get(key, 0),
                          target_proximity_score(observed.get("seq", -1), checks))
    return scores


def exact_temporal_site_key(point: dict[str, Any]) -> tuple[str, str, int]:
    """Keep distinct late calls even when they share a logarithmic bucket."""
    return (point["siteId"], point.get("phase", "before"),
            point.get("hitOrdinal", 1))


def repeated_reply_loss(sequence: list[dict[str, Any]]) -> bool:
    """Two later replies lost by the same actor at one observed callsite."""
    if len(sequence) < 2:
        return False
    first, second = sequence[-2:]
    return (first.get("phase") == second.get("phase") == "after" and
            first["siteId"] == second["siteId"] and
            first["occurrence"].rsplit("/<", 1)[0] ==
            second["occurrence"].rsplit("/<", 1)[0] and
            second.get("hitOrdinal", 0) > first.get("hitOrdinal", 0))


def consecutive_reply_streak(sequence: list[dict[str, Any]]) -> int:
    """Length of a multi-fault chain losing adjacent replies of one actor."""
    if len(sequence) < 2 or any(point.get("phase") != "after"
                                for point in sequence):
        return 0
    actor = sequence[0]["occurrence"].rsplit("/<", 1)[0]
    site = sequence[0]["siteId"]
    if any(point["siteId"] != site or
           point["occurrence"].rsplit("/<", 1)[0] != actor
           for point in sequence):
        return 0
    ordinals = [point.get("hitOrdinal", 0) for point in sequence]
    return (len(sequence) if all(b == a + 1
                                 for a, b in zip(ordinals, ordinals[1:]))
            else 0)


def same_actor_followup(sequence: list[dict[str, Any]]) -> bool:
    """The next fault interrupts a different I/O used by the same actor."""
    if len(sequence) < 2:
        return False
    first, second = sequence[-2:]
    return (first["siteId"] != second["siteId"] and
            first["occurrence"].rsplit("/<", 1)[0] ==
            second["occurrence"].rsplit("/<", 1)[0])


def fault_actors(sequence: list[dict[str, Any]]) -> tuple[str, ...]:
    """Stable runtime nodes affected by one observed fault sequence.

    The runtime identity suffix after ``|`` names the logical node. Threads
    such as a heartbeat actor and a DataXceiver can belong to that same node;
    counting them as different nodes would dilute cross-node exploration.
    Older traces without the suffix retain their observed actor identity.
    """
    return tuple(sorted({point["occurrence"].rsplit("/<", 1)[0].rsplit("|", 1)[-1]
                         for point in sequence}))


def confirmed_fault_nodes(sequence: list[dict[str, Any]]) -> tuple[str, ...]:
    """Logical node IDs explicitly carried by observed runtime identities."""
    nodes = set()
    for point in sequence:
        prefix = point["occurrence"].rsplit("/<", 1)[0]
        if "|" in prefix:
            nodes.add(prefix.rsplit("|", 1)[1])
    return tuple(sorted(nodes))


def reply_fanout_degree(sequence: list[dict[str, Any]]) -> int:
    """Count nodes receiving the same observed nonempty RPC reply shape.

    A command-like reply can update several nodes independently. Losing it
    on just one node may leave the other nodes able to repair the operation.
    Require runtime node identity and a matching callsite/response shape so
    unrelated replies do not form a synthetic fanout group.
    """
    groups: dict[tuple[str, str], set[str]] = {}
    for point in sequence:
        if not object_array_response(point):
            continue
        actor = point["occurrence"].rsplit("/<", 1)[0]
        if "|" not in actor:
            continue
        node = actor.rsplit("|", 1)[1]
        key = (point["siteId"], point["responseShape"])
        groups.setdefault(key, set()).add(node)
    return max((len(nodes) for nodes in groups.values()), default=0)


def repeated_nonempty_reply_profile(
        sequence: list[dict[str, Any]]) -> tuple[int, int]:
    """Count distinct state-bearing replies lost on one observed node.

    A later successful reply can repair a lost state update before another
    actor uses that state.  Keep the callsite, response shape, and runtime
    node together; no protocol or command name is assumed.
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
        node = actor.rsplit("|", 1)[1]
        key = (point["siteId"], point.get("sourceKey", ""),
               point["responseShape"], node)
        groups.setdefault(key, set()).add(ordinal)
    return max(((len(ordinals), max(ordinals))
                for ordinals in groups.values()), default=(0, 0))


def independent_reply_fanout(sequence: list[dict[str, Any]]) -> bool:
    """A whole fault plan targets one reply shape on distinct known nodes."""
    if len(sequence) < 2 or not all(object_array_response(p) for p in sequence):
        return False
    fields = ("marker", "siteId", "sourceKey", "exceptionClass",
              "phase", "responseShape")
    family = tuple(sequence[0].get(field) for field in fields)
    nodes: set[str] = set()
    for point in sequence:
        if tuple(point.get(field) for field in fields) != family:
            return False
        occurrence = point.get("occurrence", "")
        actor, separator, _ = occurrence.rpartition("/<")
        if not separator or "|" not in actor:
            return False
        node = actor.rsplit("|", 1)[1]
        if not node or node in nodes:
            return False
        nodes.add(node)
    return True


def identity_priority(point: dict[str, Any]) -> int:
    """Favor replayable observed actors without weakening exact matching."""
    occurrence = point.get("occurrence", "")
    source = point.get("sourceKey", "")
    score = 0
    if re.search(r"(?:port=|localhost:|127\.0\.0\.1:|qtp)\d+", occurrence):
        score -= 40
    if re.search(r"/Thread-\d+/", occurrence):
        score -= 20
    if any(name in source for name in ("ClientProtocol:", "DatanodeProtocol:",
                                       "BlockingService:", "SolrZkClient:",
                                       "ZooKeeper:")):
        score += 30
    if "java.io.FileInputStream:" in source or "java.io.FileOutputStream:" in source:
        score += 15
    if source.endswith(" close()>") or "org.apache.hadoop.util.Shell:" in occurrence:
        score -= 20
    return score


def static_reason_priority(reason: str) -> int:
    if reason.startswith("target_short_writer_caller"):
        return 100
    if reason.startswith("target_writer_actor_callee"):
        return 95
    if reason.startswith("target_direct_field_writer"):
        return 90
    if reason.startswith("target_actor_io_family"):
        return 85
    if reason.startswith("target_short_field_writer"):
        return 80
    if reason.startswith("target_short_call_path"):
        return 60
    if reason.startswith(("field_may_writer", "rpc_wire_may_producer",
                          "thread_handoff_may_launcher")):
        return 50
    return 0


def selected_target_throw_lines(selection: dict[str, Any],
                                target: dict[str, Any]) -> list[int]:
    """Find typed throws controlled by the selected check in the Soot result.

    Soot unit ordinals and ASM bytecode ordinals are different coordinates.
    Match their common source line only after Soot establishes the target
    branch-to-throw relationship; the runtime event supplies the actual type.
    """
    method = target["method"]
    check_line = selection.get("target_check_line")
    selected_line = selection.get("target_selected_line")
    guard_ids = {row.get("site_id") for row in selection.get("branches", [])
                 if row.get("method") == method and row.get("line") == check_line}
    typed_sites = [site for site in selection.get("target_throw_sites", [])
                   if site.get("method") == method and
                   site.get("thrown_type") == target["exception_type"] and
                   isinstance(site.get("line"), int) and site["line"] > 0]
    # A branch can also control later throws when one of its paths terminates
    # early. The checklist's exact throw line resolves adjacent checks of the
    # same type in a method before using the broader control relation.
    exact_lines = {site["line"] for site in typed_sites
                   if site["line"] == selected_line}
    if exact_lines:
        return sorted(exact_lines)
    lines: set[int] = set()
    for site in typed_sites:
        line = site.get("line")
        controlled = set(site.get("controlled_by", []))
        if (guard_ids & controlled or
                site.get("soot_site_id") == target.get("site_id") or
                (not guard_ids and line == selected_line)):
            lines.add(line)
    return sorted(lines)


def selected_target_control_branches(selection: dict[str, Any],
                                     target: dict[str, Any],
                                     throw_lines: list[int]) -> list[str]:
    """Use Soot's branch-to-throw relation to observe an exact target check.

    A Soot throw unit is not necessarily an ASM branch or a source-line check
    probe.  Its controlling branches are independently recorded at runtime.
    Restrict the relation to the same typed, selected throw as the oracle.
    """
    if not throw_lines:
        return []
    branches = {row.get("site_id"): row.get("line")
                for row in selection.get("branches", [])
                if row.get("method") == target["method"] and
                isinstance(row.get("line"), int)}
    selected = [site for site in selection.get("target_throw_sites", [])
                if site.get("method") == target["method"] and
                site.get("thrown_type") == target["exception_type"] and
                site.get("line") in throw_lines and
                (site.get("soot_site_id") == target.get("site_id") or
                 site.get("line") == selection.get("target_selected_line"))]
    controlled = {branch for site in selected
                  for branch in site.get("controlled_by", [])
                  if branch in branches}
    if not controlled:
        return []
    check_line = selection.get("target_check_line")
    if not isinstance(check_line, int):
        check_line = selection.get("target_selected_line")
    if not isinstance(check_line, int):
        return sorted(controlled)
    nearest = min(abs(branches[branch] - check_line) for branch in controlled)
    return sorted(branch for branch in controlled
                  if abs(branches[branch] - check_line) == nearest)


def enqueue_extensions(state: dict[str, Any], sequence: list[dict[str, Any]],
                       result: dict[str, Any], max_faults: int,
                       static_priorities: dict[str, int] | None = None,
                       static_exceptions: dict[str, list[str]] | None = None) -> None:
    """Extend an admitted run with one I/O actually seen after its final fault."""
    if (len(sequence) >= max_faults or result.get("status") not in
            {"checked", "target_exception_candidate",
             "partial_target_exception_candidate",
             "baseline_exception_recurrence", "target_exception_unlinked"}):
        return
    new_io = set(result.get("new_io_families", []))
    checks = result.get("target_check_seqs", [])
    for observed in result.get("point_events", []):
        if observed.get("seq", -1) <= result.get("last_applied_seq", -1):
            continue
        for point in fault_variants_for_io(observed["point"], static_exceptions):
            if point not in sequence:
                enqueue(state, sequence + [point],
                        priority=10 * result.get("new_coverage_count", 0) +
                        (50 if fault_family(point) in new_io else 0) +
                        (3 if result["status"] == "target_exception_candidate" else 0) +
                        (static_priorities or {}).get(point["siteId"], 0) +
                        (15 if point.get("exceptionClass") in
                         (static_exceptions or {}).get(point["siteId"], []) else 0) +
                        identity_priority(point) +
                        target_proximity_score(observed["seq"], checks),
                        target_proximity=target_proximity_score(
                            observed["seq"], checks))


def completed_sequences(state: dict[str, Any]) -> Iterable[list[dict[str, Any]]]:
    """Read old checkpoints without replaying their completed trials."""
    for completed in state["completed"]:
        sequence = completed.get("sequence")
        if sequence is None:
            selector = Path(completed["result"]).parent / "fault-trial.json"
            if selector.is_file():
                sequence = json.loads(selector.read_text()).get("faults")
        if isinstance(sequence, list) and sequence:
            yield sequence


def budget_has_room(state: dict[str, Any], budget: dict[str, Any]) -> bool:
    """Spend extra trials only when the base run has reached the target."""
    completed = state["completed"]
    if len(completed) >= budget["max_trials"]:
        return False
    minimum = budget.get("min_target_retained_trials")
    if minimum is None or len(completed) < budget["base_trials"]:
        return True
    retained = sum(item["status"] in {"checked", "target_exception_candidate",
                                      "partial_target_exception_candidate",
                                      "baseline_exception_recurrence",
                                      "target_exception_unlinked"}
                   for item in completed)
    # Zero post-fault target observations indicates a workload/scope problem;
    # spending another large block of trials on it is not a coverage gain.
    return 0 < retained < minimum


def choose_next_sequence(state: dict[str, Any],
                         static_priorities: dict[str, int] | None = None) -> int:
    """Balance new I/O sites with deeper sequences and diversify roots.

    Coverage remains a priority within each diversity tier. This prevents
    one coverage-rich seed from filling a bounded campaign with descendants
    before other observed fault sites have been tested.
    """
    previous = list(completed_sequences(state))
    # A nonempty response observed on several nodes may carry the same state
    # update to each. Give its multi-node loss a bounded share of trials,
    # favoring the widest observed fanout without naming a protocol or site.
    if (state.get("reply_fanout_diversity_version", 0) >= 1 and
            len(previous) % 10 == 3):
        fanout = [(index, item, reply_fanout_degree(item["sequence"]))
                  for index, item in enumerate(state["queue"])]
        fanout = [entry for entry in fanout if entry[2] >= 2]
        if fanout:
            return min(fanout, key=lambda entry: (
                -entry[2], len(entry[1]["sequence"]),
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    # Repeated losses on one node can keep a state-bearing reply absent until
    # a later selected I/O consumes it. Sample these deeper observed chains
    # periodically, without hardcoding the receiver, callsite, or command.
    if (state.get("reply_chain_diversity_version", 0) >= 1 and
            len(previous) % 13 == 8):
        chains = [(index, item, repeated_nonempty_reply_profile(
            item["sequence"])) for index, item in enumerate(state["queue"])]
        chains = [entry for entry in chains if entry[2][0] >= 3]
        if chains:
            return min(chains, key=lambda entry: (
                -min(entry[2][0], 4),
                len(entry[1]["sequence"]),
                -entry[2][1],
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    # A successful RPC may carry a state-changing command. Reserve a bounded
    # share for observed object-array response variants, without naming any
    # system, command class, or fault callsite in the selector.
    if (state.get("response_shape_diversity_version", 0) >= 1 and
            len(previous) % 7 == 5):
        shaped = [(index, item) for index, item in enumerate(state["queue"])
                  if len(item["sequence"]) == 1 and
                  object_array_response(item["sequence"][0])]
        if shaped:
            tried: dict[tuple[Any, ...], int] = {}
            def response_key(point: dict[str, Any]) -> tuple[Any, ...]:
                return (point["siteId"], point["responseShape"],
                        fault_actors([point]), point.get("hitOrdinal"))
            for sequence in previous:
                point = sequence[-1]
                if object_array_response(point):
                    key = response_key(point)
                    tried[key] = tried.get(key, 0) + 1
            return min(shaped, key=lambda entry: (
                tried.get(response_key(entry[1]["sequence"][0]), 0),
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    # A lost control-plane reply on one actor can affect a data operation on
    # another actor. Reserve a bounded share for observed multi-actor plans;
    # keep shorter, less-tested actor combinations ahead of long repeats.
    if (state.get("cross_actor_diversity_version", 0) >= 1 and
            len(previous) % 11 == 10):
        cross = [(index, item) for index, item in enumerate(state["queue"])
                 if len(confirmed_fault_nodes(item["sequence"])) >= 2]
        actor_key = confirmed_fault_nodes
        if not cross:
            # Older or generic traces may have actor names but no explicit
            # logical-node suffix. Preserve their broader exploration.
            cross = [(index, item) for index, item in enumerate(state["queue"])
                     if len(fault_actors(item["sequence"])) >= 2]
            actor_key = fault_actors
        if cross:
            tried: dict[tuple[str, ...], int] = {}
            for sequence in previous:
                actors = actor_key(sequence)
                if len(actors) >= 2:
                    tried[actors] = tried.get(actors, 0) + 1
            return min(cross, key=lambda entry: (
                tried.get(actor_key(entry[1]["sequence"]), 0),
                len(entry[1]["sequence"]),
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    # A lost reply can be repaired by the next RPC. Reserve a bounded share
    # for losing a second observed reply from the same actor and callsite.
    if (state.get("repeated_reply_loss_version", 0) >= 1 and
            len(previous) % 7 == 6):
        repeated = [(index, item) for index, item in enumerate(state["queue"])
                    if repeated_reply_loss(item["sequence"])]
        if repeated:
            return min(repeated, key=lambda entry: (
                entry[1]["sequence"][-1]["hitOrdinal"] -
                entry[1]["sequence"][-2]["hitOrdinal"],
                -entry[1]["sequence"][-2]["hitOrdinal"],
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    # An actor may repair a failed watch, RPC, or file read through a
    # different I/O call. Try one observed same-actor follow-up periodically.
    if (state.get("same_actor_followup_version", 0) >= 1 and
            len(previous) % 9 == 8):
        followups = [(index, item)
                     for index, item in enumerate(state["queue"])
                     if same_actor_followup(item["sequence"])]
        if followups:
            tried_roots: dict[Any, int] = {}
            for sequence in previous:
                root = temporal_diversity_key(sequence[0])
                tried_roots[root] = tried_roots.get(root, 0) + 1
            return min(followups, key=lambda entry: (
                tried_roots.get(temporal_diversity_key(
                    entry[1]["sequence"][0]), 0),
                -entry[1].get("target_proximity", 0),
                -(entry[1]["sequence"][-2]["siteId"].split(":", 1)[0] ==
                  entry[1]["sequence"][-1]["siteId"].split(":", 1)[0]),
                -entry[1]["priority"], len(entry[1]["sequence"]),
                entry[1]["created"], entry[0]))[0]
    # Exception effects can overlap across several actors. Give retained
    # three-or-more-fault descendants a bounded share of the budget instead
    # of letting their numerous one/two-fault siblings fill the campaign.
    if (state.get("deep_sequence_version", 0) >= 1 and
            len(previous) % 8 == 7):
        deep = [(index, item) for index, item in enumerate(state["queue"])
                if len(item["sequence"]) >= 3]
        if deep:
            return min(deep, key=lambda entry: (
                -consecutive_reply_streak(entry[1]["sequence"]),
                -entry[1].get("target_proximity", 0),
                -entry[1]["priority"], len(entry[1]["sequence"]),
                entry[1]["created"], entry[0]))[0]
    # A short JUnit can perform several protocol steps in one logarithmic
    # occurrence bucket. Periodically sample another exact invocation of a
    # repeated site after the coarse buckets have been represented.
    if (state.get("exact_late_occurrence_version", 0) >= 1 and
            len(previous) % 12 == 11):
        tried_exact = {exact_temporal_site_key(sequence[-1])
                       for sequence in previous}
        exact_late = [(index, item) for index, item in enumerate(state["queue"])
                      if len(item["sequence"]) == 1 and
                      item["sequence"][-1].get("hitOrdinal", 1) > 1 and
                      exact_temporal_site_key(item["sequence"][-1]) not in tried_exact]
        if exact_late:
            return min(exact_late, key=lambda entry: (
                -entry[1]["priority"],
                entry[1]["sequence"][-1]["hitOrdinal"],
                entry[1]["created"], entry[0]))[0]
    # A repeated I/O call can execute after a control-plane state change.
    # Reserve a bounded slot for a later observed occurrence of one callsite;
    # fault-type and actor variants must not starve this temporal exploration.
    if (state.get("late_occurrence_diversity_version", 0) >= 1 and
            len(previous) % 6 == 5):
        tried_buckets = {temporal_site_key(sequence[-1])
                         for sequence in previous}
        late = [(index, item) for index, item in enumerate(state["queue"])
                if len(item["sequence"]) == 1 and
                item["sequence"][-1].get("hitOrdinal", 1) > 1 and
                temporal_site_key(item["sequence"][-1]) not in tried_buckets]
        if late:
            return min(late, key=lambda entry: (
                -entry[1]["priority"], entry[1]["created"], entry[0]))[0]
    single_done = sum(len(sequence) == 1 for sequence in previous)
    multi_done = len(previous) - single_done
    preferred_length = 1 if single_done <= multi_done else 2
    eligible = [(index, item) for index, item in enumerate(state["queue"])
                if (len(item["sequence"]) == 1) == (preferred_length == 1)]
    if not eligible:
        eligible = list(enumerate(state["queue"]))
    # Keep a bounded share for I/O just before an observed target check. A
    # later fault may still be valuable, so the other rounds remain broad.
    if len(previous) % 5 == 4:
        near = [(index, item) for index, item in eligible
                if item.get("target_proximity", 0) >= 50]
        if near:
            eligible = near
    # Reserve every third trial for a target-side field writer or actor I/O
    # found by static analysis. Diversity still ranks sequences within that
    # tier; the remaining trials can explore all observed I/O families.
    if len(previous) % 3 == 2 and static_priorities:
        focused = [(index, item) for index, item in eligible
                   if max(static_priorities.get(point["siteId"], 0)
                          for point in (item["sequence"][0],
                                        item["sequence"][-1])) >= 80]
        if focused:
            eligible = focused
    diversity_key = (temporal_diversity_key
                     if state.get("temporal_diversity_version", 1) >= 2
                     else fault_family)
    family_counts: dict[Any, int] = {}
    # A failed request and a lost reply have different effects on remote
    # state. Count them separately when reserving untried I/O sites.
    site_counts: dict[tuple[str, str], int] = {}
    root_counts: dict[Any, int] = {}
    for sequence in previous:
        last = diversity_key(sequence[-1])
        root = diversity_key(sequence[0])
        family_counts[last] = family_counts.get(last, 0) + 1
        site = (sequence[-1]["siteId"],
                sequence[-1].get("phase", "before"))
        site_counts[site] = site_counts.get(site, 0) + 1
        root_counts[root] = root_counts.get(root, 0) + 1
    # CrashFuzz first favors new I/O points. A phase, exception class, or
    # occurrence bucket is still worth exploring, but should not consume most
    # of a bounded campaign while other observed callsites remain untested.
    # Keep every fourth choice for the existing temporal-family preference.
    prefer_new_site = (state.get("site_diversity_version", 1) >= 2 and
                       len(previous) % 4 != 3)

    def rank(entry: tuple[int, dict[str, Any]]) -> tuple[Any, ...]:
        index, item = entry
        sequence = item["sequence"]
        root_penalty = (root_counts.get(diversity_key(sequence[0]), 0)
                        if len(sequence) > 1 else 0)
        site = (sequence[-1]["siteId"],
                sequence[-1].get("phase", "before"))
        return ((site_counts.get(site, 0)
                 if prefer_new_site else 0),
                family_counts.get(diversity_key(sequence[-1]), 0),
                root_penalty,
                -item["priority"], item["created"], index)

    return min(eligible, key=rank)[0]


def write_trial(path: Path, sequence: list[dict[str, Any]],
                target: dict[str, Any]) -> None:
    trial = {"schemaVersion": 1, "faults": [
        {"faultId": fingerprint(point), **point,
         "phase": point.get("phase", "before"), "value": True}
        for point in sequence]}
    if target.get("site_id"):
        trial["targetSiteId"] = target["site_id"]
    atomic_json(path, trial)


def substitute(args: list[str], context: dict[str, str]) -> list[str]:
    return [value.format_map(context) for value in args]


def run_command(args: list[str], context: dict[str, str],
                cwd: Path, env: dict[str, str], log_dir: Path,
                timeout: int) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    command = substitute(args, context)
    started = time.monotonic()
    with (log_dir / "stdout.log").open("wb") as stdout, \
            (log_dir / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env,
                                   stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        timed_out = False
        try:
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    code = process.wait()
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            raise
    return {"command": command, "exit": code, "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def ensure_seed(config: dict[str, Any], state: dict[str, Any],
                case_dir: Path) -> None:
    seed = config["seed"]
    trace = Path(seed["trace"])
    seed_command_seconds = None
    if not trace.is_file():
        command = seed.get("command")
        if not command:
            raise FileNotFoundError(f"seed trace missing: {trace}")
        context = {"case_dir": str(case_dir), "trace_dir": str(trace.parent)}
        environment = {**os.environ, **config.get("env", {}),
                       "TMPDIR": config["workspaces"]["temp"],
                       "CAUSYNTH_LOCAL_SCRATCH": config["workspaces"]["temp"],
                       "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace.parent)}
        if config.get("_static_selection_artifact"):
            environment["CRASHFUZZ_STATIC_SELECTION"] = config[
                "_static_selection_artifact"]
        result = run_command(command, context, Path(config["cwd"]),
                             environment, case_dir / "seed-command",
                             config["timeout_seconds"])
        atomic_json(case_dir / "seed-command" / "result.json", result)
        seed_command_seconds = result["elapsed_seconds"]
        state["active_runtime_seconds"] += seed_command_seconds
        state["seed_runtime_seconds"] += seed_command_seconds
        if result["exit"] == 0 and not result["timed_out"]:
            state["seed_timing_recorded"] = True
        atomic_json(case_dir / "state.json", state)
        if result["exit"] != 0 or result["timed_out"]:
            raise RuntimeError("healthy JUnit recording failed")
    if seed_command_seconds is None:
        previous_command = case_dir / "seed-command" / "result.json"
        timing = seed.get("timing_manifest")
        if previous_command.is_file():
            seed_command_seconds = float(json.loads(previous_command.read_text())
                                         ["elapsed_seconds"])
        elif timing:
            data = json.loads(Path(timing).read_text())
            seed_command_seconds = sum(float(data.get(stage, {}).get("seconds", 0))
                                       for stage in ("compile", "weave", "runtime"))
        else:
            seed_command_seconds = float(seed["elapsed_seconds"])
        if not state.get("seed_timing_recorded"):
            state["active_runtime_seconds"] += seed_command_seconds
            state["seed_runtime_seconds"] += seed_command_seconds
            state["seed_timing_recorded"] = True
            atomic_json(case_dir / "state.json", state)
    feedback = trace_feedback(trace, config["target"], config.get("io_scope"))
    if config.get("_static_selection_digest") and feedback[
            "static_selection_digests"] != [config["_static_selection_digest"]]:
        raise RuntimeError("healthy JUnit did not apply the selected instrumentation")
    state["seed"] = {"trace": str(trace), "feedback": feedback,
                     "target_reached": feedback["target_reached"],
                     "recorded_at": time.time(),
                     "elapsed_seconds": seed_command_seconds}
    state["coverage"] = feedback["coverage"]
    state["io_families"] = sorted({fault_family(p) for p in feedback["points"]})
    if not feedback["points"]:
        state["status"] = "no_io_fault_points"
        return
    state["status"] = "fuzzing"
    static_priorities = config.get("_static_io_priority", {})
    proximity = observed_proximity(feedback)
    for observed in feedback["points"]:
        for point in fault_variants_for_io(
                observed, config.get("_static_io_exceptions")):
            near = proximity.get(observed_identity(point), 0)
            enqueue(state, [point], priority=20 + identity_priority(point) +
                    static_priorities.get(point["siteId"], 0) +
                    (15 if point.get("exceptionClass") in config.get(
                        "_static_io_exceptions", {}).get(point["siteId"], [])
                     else 0) + near, target_proximity=near)


def process_trial(config: dict[str, Any], state: dict[str, Any],
                  case_dir: Path, active: dict[str, Any]) -> None:
    trial_dir = case_dir / "trials" / f"{active['number']:04d}-{active['id']}"
    result_file = trial_dir / "result.json"
    if result_file.is_file():
        result = json.loads(result_file.read_text())
    else:
        trial_dir.mkdir(parents=True, exist_ok=True)
        selector_file = trial_dir / "fault-trial.json"
        write_trial(selector_file, active["sequence"], config["target"])
        active["attempt"] = active.get("attempt", 0) + 1
        atomic_json(case_dir / "state.json", state)
        attempt_dir = trial_dir / f"attempt-{active['attempt']:02d}"
        trace_dir = attempt_dir / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)
        trial_name = (f"{config['case_id']}-{active['number']:04d}-"
                      f"{active['id'][:12]}-a{active['attempt']:02d}")
        context = {"case_id": config["case_id"],
                   "sequence_id": active["id"],
                   "attempt": str(active["attempt"]),
                   "trial_name": trial_name,
                   "case_dir": str(case_dir), "trial_dir": str(trial_dir),
                   "trace_dir": str(trace_dir), "fault_trial": str(selector_file)}
        env = {**os.environ, **config.get("env", {}),
               "TMPDIR": config["workspaces"]["temp"],
               "CAUSYNTH_LOCAL_SCRATCH": config["workspaces"]["temp"],
               "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace_dir),
               "CAUSYNTH_FAULT_TRIAL": str(selector_file)}
        if config.get("_static_selection_artifact"):
            env["CRASHFUZZ_STATIC_SELECTION"] = config[
                "_static_selection_artifact"]
        env.update({key: value.format_map(context)
                    for key, value in config["trial"].get("env", {}).items()})
        options = env.get("CAUSYNTH_WORKLOAD_JAVA_OPTS", "")
        env["CAUSYNTH_WORKLOAD_JAVA_OPTS"] = (
            options + " -Dcausynth.fault.trial=" + str(selector_file)).strip()
        result = run_command(config["trial"]["command"], context,
                             Path(config["cwd"]), env, attempt_dir,
                             config["timeout_seconds"])
        state["active_runtime_seconds"] += result["elapsed_seconds"]
        state["fault_runtime_seconds"] += result["elapsed_seconds"]
        atomic_json(case_dir / "state.json", state)
        trace = Path(config["trial"].get(
            "trace_path", "{trace_dir}/runtime_trace.jsonl").format_map(context))
        allowed_trace_roots = [case_dir.resolve()] + [
            Path(value).resolve() for value in config["workspaces"].values()]
        resolved_trace = trace.resolve()
        if not trace.is_absolute() or not any(
                resolved_trace == root or root in resolved_trace.parents
                for root in allowed_trace_roots):
            raise ValueError(f"trial trace must stay in a per-case workspace: {trace}")
        if trace.is_file():
            result.update(trace_feedback(trace, config["target"],
                                         config.get("io_scope")))
            result["trace"] = str(trace)
            if config.get("_static_selection_digest") and result[
                    "static_selection_digests"] != [config["_static_selection_digest"]]:
                raise RuntimeError("fault trial did not apply the selected instrumentation")
        else:
            result.update({"trace": None, "matched_count": 0,
                           "applied_count": 0, "target_reached": False,
                           "target_reached_after_fault": False,
                           "oracle": False, "coverage": [], "points": []})
        result["sequence_id"] = active["id"]
        result["fault_count"] = len(active["sequence"])
        result["attempt"] = active["attempt"]
        result["completed_at"] = time.time()
        atomic_json(attempt_dir / "result.json", result)
    selector_matched = strict_injection(result, active["sequence"])
    if (not selector_matched and not result_file.is_file() and
            active.get("attempt", 0) <= config["budget"].get(
                "max_unmatched_retries", 1)):
        # Re-execute a selector whose observed I/O was absent in this run.
        # Each attempt and its runtime cost remain in the checkpoint.
        atomic_json(case_dir / "state.json", state)
        process_trial(config, state, case_dir, active)
        return
    if (not result_file.is_file() and
            retry_lost_target(result, active["sequence"],
                              active.get("attempt", 0),
                              config["budget"].get("max_lost_target_retries", 1))):
        # Asynchronous callbacks can put the last fault after the check on
        # one run and before it on another. Keep retries strictly bounded.
        atomic_json(case_dir / "state.json", state)
        process_trial(config, state, case_dir, active)
        return
    result["selector_matched"] = selector_matched
    result["strict_injection"] = selector_matched
    realized_prefix = (strict_applied_prefix(result, active["sequence"])
                       if not selector_matched else [])
    result["strict_applied_prefix"] = bool(realized_prefix)
    result["realized_fault_count"] = (len(active["sequence"])
                                      if selector_matched else len(realized_prefix))
    baseline_fatal_count = state["seed"]["feedback"].get(
        "target_fatal_exception_count", 0)
    result["baseline_target_fatal_exception_count"] = baseline_fatal_count
    result["differential_target_exception"] = bool(
        result.get("target_fatal_exception_count", 0) > baseline_fatal_count)
    baseline_outcomes = set(state["seed"]["feedback"].get("target_outcomes", []))
    result["target_outcome_changed"] = bool(
        set(result.get("target_outcomes_after_fault", [])) - baseline_outcomes)
    if (realized_prefix and result["oracle"] and
            result["differential_target_exception"]):
        status = "partial_target_exception_candidate"
    elif not selector_matched:
        status = "unmatched"
    elif not result.get("target_reached_after_fault"):
        status = "lost_target"
    elif result["oracle"] and result["differential_target_exception"]:
        status = "target_exception_candidate"
    elif result["oracle"]:
        status = "baseline_exception_recurrence"
    elif result.get("target_after_fault"):
        status = "target_exception_unlinked"
    elif result["timed_out"]:
        status = "timeout"
    else:
        status = "checked"
    old_coverage = set(state["coverage"])
    observed_coverage = set(result.get("coverage", [])) - old_coverage
    old_io = set(state.get("io_families", []))
    observed_io = {fault_family(point) for point in result.get("points", [])} - old_io
    admitted = status in {"checked", "target_exception_candidate",
                          "partial_target_exception_candidate",
                          "baseline_exception_recurrence",
                          "target_exception_unlinked"}
    new_coverage = observed_coverage if admitted else set()
    new_io = observed_io if admitted else set()
    result["observed_new_coverage_count"] = len(observed_coverage)
    result["new_coverage_count"] = len(new_coverage)
    result["observed_new_io_count"] = len(observed_io)
    result["new_io_count"] = len(new_io)
    result["new_io_families"] = sorted(new_io)
    result["status"] = status
    if (config.get("archive_completed_trials") and status not in
            {"target_exception_candidate", "partial_target_exception_candidate"}):
        result["archived_artifacts"] = sorted(set(
            result.get("archived_artifacts", []) +
            archive_trial_attempts(trial_dir, result)))
    atomic_json(result_file, result)
    if admitted:
        state["coverage"] = sorted(old_coverage | set(result.get("coverage", [])))
        state["io_families"] = sorted(old_io | {
            fault_family(point) for point in result.get("points", [])})
    state["completed"].append({"id": active["id"], "number": active["number"],
                               "status": status, "result": str(result_file),
                               "elapsed_seconds": result["elapsed_seconds"],
                               "sequence": active["sequence"]})
    enqueue_extensions(state, realized_prefix or active["sequence"], result,
                       config["budget"]["max_faults"],
                       config.get("_static_io_priority"),
                       config.get("_static_io_exceptions"))
    state["active"] = None


def archive_trial_attempts(trial_dir: Path, final_result: dict[str, Any]) -> list[str]:
    """Compress every completed retry, including attempts before the last one."""
    archived = []
    for attempt_dir in sorted(trial_dir.glob("attempt-*")):
        attempt_result_path = attempt_dir / "result.json"
        if not attempt_result_path.is_file():
            continue
        attempt_result = json.loads(attempt_result_path.read_text())
        manifest_path = attempt_dir / "trace" / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
        changed = False
        manifest_changed = False
        attempt_archived = []
        for name in ("runtime_trace.jsonl", "junit.log", "jacoco.exec"):
            path = attempt_dir / "trace" / name
            target = path.with_name(path.name + ".gz")
            if path.is_file():
                temporary = target.with_name(target.name + f".tmp.{os.getpid()}")
                try:
                    source_digest = hashlib.sha256()
                    with path.open("rb") as source, gzip.open(
                            temporary, "wb", compresslevel=3) as sink:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            source_digest.update(chunk)
                            sink.write(chunk)
                    restored_digest = hashlib.sha256()
                    with gzip.open(temporary, "rb") as restored:
                        for chunk in iter(lambda: restored.read(1024 * 1024), b""):
                            restored_digest.update(chunk)
                    if restored_digest.digest() != source_digest.digest():
                        raise IOError(f"compressed artifact differs from source: {path}")
                    os.replace(temporary, target)
                    path.unlink()
                finally:
                    temporary.unlink(missing_ok=True)
            elif not target.is_file():
                continue
            archived.append(str(target))
            attempt_archived.append(str(target))
            for record in (attempt_result, final_result):
                for key in ("trace", "junit_log", "jacoco_exec"):
                    if record.get(key) == str(path):
                        record[key] = str(target)
                        changed = True
            if manifest is not None:
                for key in ("trace", "junit_log", "jacoco_exec"):
                    if manifest.get(key) == str(path):
                        manifest[key] = str(target)
                        manifest_changed = True
            if str(target) not in attempt_result.get("archived_artifacts", []):
                changed = True
        if changed:
            attempt_result["archived_artifacts"] = sorted(set(
                attempt_result.get("archived_artifacts", []) + attempt_archived))
            atomic_json(attempt_result_path, attempt_result)
        if manifest_changed:
            atomic_json(manifest_path, manifest)
    return archived


def validate(config: dict[str, Any]) -> None:
    if config.get("selection_mode", "coverage_io") != "coverage_io":
        raise ValueError("only selection_mode=coverage_io is supported")
    needed = {"case_id", "system", "test_class", "test_method", "target",
              "cwd", "seed", "trial", "budget", "timeout_seconds",
              "workspaces"}
    missing = needed - config.keys()
    if missing:
        raise ValueError(f"missing config keys: {sorted(missing)}")
    target = config["target"]
    if not target.get("method") or "exception_type" not in target:
        raise ValueError("target requires exact method and exception_type field")
    if target["exception_type"] is not None and not isinstance(
            target["exception_type"], str):
        raise ValueError("target.exception_type must be an exact class or null")
    if target.get("throw_site_id"):
        throw_method = target["throw_site_id"].split("#u", 1)[0]
        if target.get("throw_method") and target["throw_method"] != throw_method:
            raise ValueError("throw_method differs from throw_site_id's method")
        target["throw_method"] = throw_method
    check_events = target.get("check_events")
    allowed_checks = {"BRANCH", "CHECK_REACHED", "CALL_SITE_ENTER", "CALL_SITE_RETURN",
                      "CALL_SITE_THROW"}
    if check_events is not None and (
            not isinstance(check_events, list) or not check_events or
            any(event not in allowed_checks for event in check_events)):
        raise ValueError("target.check_events must list supported check events")
    check_site_ids = target.get("check_site_ids", [])
    if (not isinstance(check_site_ids, list) or
            any(not isinstance(site, str) or "#u" not in site
                for site in check_site_ids)):
        raise ValueError("target.check_site_ids needs exact site IDs")
    has_guards = "fatal_guards" in target or "fatal_guard_paths" in target
    if check_events and not (target.get("site_id") or check_site_ids or has_guards):
        raise ValueError("target.check_events requires exact check site IDs")
    throw_event = target.get("throw_event", "METHOD_EXIT_THROW")
    if throw_event not in {"METHOD_EXIT_THROW", "EXPLICIT_THROW", "CALL_SITE_THROW"}:
        raise ValueError("target.throw_event must name a supported throw event")
    if throw_event == "CALL_SITE_THROW" and not (
            target.get("throw_site_id") or target.get("site_id")):
        raise ValueError("CALL_SITE_THROW requires throw_site_id or site_id")
    if throw_event == "EXPLICIT_THROW":
        explicit_site = target.get("explicit_throw_site_id")
        lines = target.get("explicit_throw_lines", [])
        if (not isinstance(lines, list) or
                any(not isinstance(line, int) or isinstance(line, bool) or line < 1
                    for line in lines)):
            raise ValueError("explicit_throw_lines needs positive source lines")
        if explicit_site is None and not lines:
            raise ValueError("EXPLICIT_THROW needs an exact site or selected lines")
        if explicit_site is not None:
            method = target.get("throw_method", target["method"])
            if (not isinstance(explicit_site, str) or
                    not explicit_site.startswith(method + "#")):
                raise ValueError("explicit_throw_site_id differs from throw_method")
            if target.get("throw_site_id") and explicit_site != target["throw_site_id"]:
                raise ValueError("explicit_throw_site_id differs from throw_site_id")
    if has_guards:
        fatal_guard_paths(target)
    coverage_exclude_sites = target.get("coverage_exclude_sites", [])
    if (not isinstance(coverage_exclude_sites, list) or
            any(not isinstance(site, str) or "#u" not in site
                for site in coverage_exclude_sites)):
        raise ValueError("target.coverage_exclude_sites needs exact site IDs")
    coverage_include_prefixes = target.get("coverage_include_prefixes", [])
    if (not isinstance(coverage_include_prefixes, list) or
            any(not isinstance(prefix, str) or not prefix
                for prefix in coverage_include_prefixes)):
        raise ValueError("target.coverage_include_prefixes needs nonempty strings")
    coverage_include_methods = target.get("coverage_include_methods", [])
    if (not isinstance(coverage_include_methods, list) or
            any(not isinstance(method, str) or not method.startswith("<")
                for method in coverage_include_methods)):
        raise ValueError("target.coverage_include_methods needs Soot signatures")
    if has_guards and any(guard["siteId"] in coverage_exclude_sites
                          for path in fatal_guard_paths(target)
                          for guard in path):
        raise ValueError("cannot exclude a fatal target guard from coverage")
    scope = config.get("io_scope", {})
    if not isinstance(scope, dict) or any(
            not isinstance(scope.get(key, []), list) or
            any(not isinstance(item, str) or not item
                for item in scope.get(key, []))
            for key in ("marker_prefixes", "site_ids")):
        raise ValueError("io_scope needs marker_prefixes/site_ids string lists")
    if not isinstance(config["trial"].get("command"), list):
        raise ValueError("trial.command must be an argv list, never a shell string")
    if (not config["seed"].get("command") and
            "elapsed_seconds" not in config["seed"] and
            "timing_manifest" not in config["seed"]):
        raise ValueError("precomputed seed requires elapsed_seconds or timing_manifest")
    budget = config["budget"]
    budget.setdefault("max_trials", 80)
    budget.setdefault("max_faults", 8)
    if budget["max_trials"] < 1 or budget["max_faults"] < 1:
        raise ValueError("budgets must be positive")
    if "min_target_retained_trials" in budget:
        if (not isinstance(budget["min_target_retained_trials"], int) or
                budget["min_target_retained_trials"] < 1 or
                not isinstance(budget.get("base_trials"), int) or
                not 1 <= budget["base_trials"] <= budget["max_trials"]):
            raise ValueError("adaptive budget needs positive target trials and valid base_trials")
    if (not isinstance(budget.get("max_unmatched_retries", 1), int) or
            budget.get("max_unmatched_retries", 1) < 0):
        raise ValueError("max_unmatched_retries must be nonnegative")
    if (not isinstance(budget.get("max_lost_target_retries", 1), int) or
            budget.get("max_lost_target_retries", 1) < 0):
        raise ValueError("max_lost_target_retries must be nonnegative")
    workspaces = config["workspaces"]
    required = ("system_test", "temp")
    for name in required:
        if name not in workspaces or not Path(workspaces[name]).is_absolute():
            raise ValueError(f"workspaces.{name} must be an absolute per-case path")
    paths = [Path(value).resolve() for value in workspaces.values()]
    if len(set(paths)) != len(paths):
        raise ValueError("per-case workspaces must differ")
    shared = [Path(value).resolve() for value in config.get("shared_readonly_roots", [])]
    for path in paths:
        if any(path == root or root in path.parents for root in shared):
            raise ValueError(f"workspace must be outside shared source: {path}")
    if Path(config["cwd"]).resolve() not in paths:
        raise ValueError("cwd must be a per-case workspace")


def write_case_result(case_dir: Path, state: dict[str, Any]) -> None:
    completed = state["completed"]
    sequences = list(completed_sequences(state))
    results = [json.loads(Path(item["result"]).read_text())
               for item in completed]
    candidates = [item for item, result in zip(completed, results)
                  if result.get("status") in
                  {"target_exception_candidate",
                   "partial_target_exception_candidate"}]
    status = state.get("status", "recorded_seed")
    if candidates and status not in TERMINAL:
        status = "candidate_review"
    elif completed and not state.get("finished"):
        status = "fuzzing"
    seed = state.get("seed") or {}
    seed_coverage = set(seed.get("feedback", {}).get("coverage", []))
    coverage_delta = set(state.get("coverage", [])) - seed_coverage
    coverage_gain_by_kind = {
        "methods": sum(identifier.startswith("METHOD:") for identifier in coverage_delta),
        "branch_outcomes": sum(identifier.startswith("BRANCH:") for identifier in coverage_delta),
        "call_site_events": sum(identifier.startswith("CALL_SITE:") for identifier in coverage_delta),
    }
    setup_seconds = float(state.get("setup_seconds", 0))
    build_seconds = float(state.get("build_seconds", 0))
    seed_seconds = float(state.get("seed_runtime_seconds", 0))
    fault_seconds = float(state.get("fault_runtime_seconds", 0))
    total_seconds = round(setup_seconds + build_seconds + seed_seconds +
                          fault_seconds, 3)
    record = {
        "schema_version": SCHEMA,
        "case_id": state["case_id"], "system": state["system"],
        "cluster_test": state["test_class"] + "#" + state["test_method"],
        "target_method": state.get("target_method"),
        "target_throw_method": state.get("target_throw_method"),
        "target_throw_site_id": state.get("target_throw_site_id"),
        "target_source_file": state.get("target_source_file"),
        "target_source_line": state.get("target_source_line"),
        "target_code": state.get("target_code"),
        "coverage_exclude_sites": state.get("coverage_exclude_sites", []),
        "status": status,
        "target_reached": seed.get("target_reached"),
        "fault_trials": len(completed),
        "single_fault_trials": sum(len(sequence) == 1 for sequence in sequences),
        "multi_fault_trials": sum(len(sequence) > 1 for sequence in sequences),
        "first_fault_families_tested": len({
            fault_family(sequence[0]) for sequence in sequences}),
        "last_fault_families_tested": len({
            fault_family(sequence[-1]) for sequence in sequences}),
        "strict_injections": sum(bool(result.get("strict_injection"))
                                 for result in results),
        "strict_applied_prefixes": sum(bool(result.get("strict_applied_prefix"))
                                        for result in results),
        "post_fault_target_reach_trials": sum(
            bool(result.get("strict_injection") and
                 result.get("target_reached_after_fault")) for result in results),
        "lost_target_trials": sum(result.get("status") == "lost_target"
                                  for result in results),
        "target_after_fault": sum(bool(result.get("target_after_fault"))
                                  for result in results),
        "target_exception_after_fault_trials": sum(
            bool(result.get("strict_injection") and result.get("oracle"))
            for result in results),
        "target_outcome_changed_trials": sum(
            bool(result.get("target_outcome_changed")) for result in results),
        "oracle_candidates": len(candidates),
        "partial_target_exception_candidates": sum(
            result.get("status") == "partial_target_exception_candidate"
            for result in results),
        "coverage_gain": len(coverage_delta),
        "coverage_gain_by_kind": coverage_gain_by_kind,
        "coverage_include_prefixes": state.get("coverage_include_prefixes", []),
        "static_selection_digest": state.get("static_selection_digest"),
        "static_selection_artifact": state.get("static_selection_artifact"),
        "temporal_diversity_version": state.get("temporal_diversity_version", 1),
        "cross_actor_diversity_version": state.get("cross_actor_diversity_version", 0),
        "io_family_gain": max(0, len(state.get("io_families", [])) - len({
            fault_family(point) for point in
            seed.get("feedback", {}).get("points", [])})),
        "setup_seconds": round(setup_seconds, 3),
        "build_seconds": round(build_seconds, 3),
        "seed_seconds": round(seed_seconds, 3),
        "fault_seconds": round(fault_seconds, 3),
        "total_elapsed_seconds": total_seconds,
        "elapsed_seconds": total_seconds,
        "bug_mark": "candidate" if candidates else "none",
        "evidence": candidates[0]["result"] if candidates else
                    (completed[-1]["result"] if completed else None),
        "started_at": state.get("started"),
        "updated_at": time.time(),
    }
    atomic_json(case_dir / "result.json", record)


class CaseLease:
    """One host-local owner; stale takeover requires TTL and free flock."""

    def __init__(self, case_dir: Path, ttl: int = 120, interval: int = 15):
        self.case_dir = case_dir
        self.ttl = ttl
        self.interval = interval
        self.owner = str(uuid.uuid4())
        self.directory = case_dir / "claim.d"
        self.path = self.directory / "lease.json"
        self.lock = None
        self.stop = threading.Event()
        self.thread = None
        self.started = time.time()

    def _record(self) -> dict[str, Any]:
        return {"owner": self.owner, "host": socket.gethostname(),
                "pid": os.getpid(), "started_at": self.started,
                "heartbeat": time.time(), "ttl_seconds": self.ttl}

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.interval):
            atomic_json(self.path, self._record())

    def __enter__(self) -> "CaseLease":
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.lock = (self.case_dir / ".lock").open("w")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise RuntimeError(f"case already claimed: {self.case_dir}") from exc
        try:
            if self.directory.exists():
                old = json.loads(self.path.read_text()) if self.path.exists() else {}
                if time.time() - old.get("heartbeat", 0) <= self.ttl:
                    raise RuntimeError(f"case lease still live: {self.case_dir}")
                stale = self.case_dir / f"claim.stale.{int(time.time())}.{self.owner}.d"
                os.rename(self.directory, stale)
            # mkdir is the cross-host exclusive claim; flock above serializes
            # an expired-claim takeover on a shared NFS mount.
            self.directory.mkdir()
            atomic_json(self.path, self._record())
        except BaseException:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            raise
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=self.interval + 1)
        if self.path.exists():
            lease = json.loads(self.path.read_text())
            if lease.get("owner") == self.owner:
                self.path.unlink()
                self.directory.rmdir()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()


def config_identity(config: dict[str, Any]) -> str:
    """Checkpoint identity excludes knobs that may grow on resume."""
    return fingerprint({key: value for key, value in config.items()
                        if key not in {"budget", "timeout_seconds",
                                       "archive_completed_trials",
                                       "_static_io_priority",
                                       "_static_io_exceptions"}})


def campaign(config: dict[str, Any], root: Path) -> dict[str, Any]:
    validate(config)
    case_dir = root / config["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    Path(config["workspaces"]["temp"]).mkdir(parents=True, exist_ok=True)
    with CaseLease(case_dir):
        selection = prepare_static_selection(config, case_dir)
        if selection is not None:
            selected_lines = selected_target_throw_lines(selection, config["target"])
            target = {**config["target"],
                      "coverage_include_methods": selection["coverage_methods"]}
            if selected_lines and "throw_event" not in target:
                target.update(throw_event="EXPLICIT_THROW",
                              explicit_throw_lines=selected_lines)
            controls = (selected_target_control_branches(selection, target,
                        selected_lines) if target.get("check_events") ==
                        ["CHECK_REACHED"] else [])
            config = {**config, "target": target,
                      "io_scope": {"site_ids": [row["site_id"]
                                               for row in selection["io_calls"]]},
                      "_static_io_priority": {
                          row["site_id"]: static_reason_priority(
                              row.get("selection_reason", ""))
                          for row in selection["io_calls"]},
                      "_static_io_exceptions": {
                          row["site_id"]: row.get("exception_candidates", [])
                          for row in selection["io_calls"]
                          if row.get("exception_candidates")},
                      "_static_selection_digest": selection.get(
                          "input_digest", selection.get("artifact_sha256")),
                      "_static_selection_artifact": selection["artifact_path"]}
            if controls:
                check_target = {**target,
                                "check_events": ["CHECK_REACHED", "BRANCH"],
                                "check_site_ids": sorted(set(
                                    target.get("check_site_ids", []) + controls +
                                    ([target["site_id"]]
                                     if target.get("site_id") else [])))}
                checkpoint = case_dir / "state.json"
                # A previous checkpoint retains its original observation
                # contract. New campaigns gain the Soot-derived branch, while
                # campaigns already using it resume with the same digest.
                if (not checkpoint.is_file() or
                        json.loads(checkpoint.read_text()).get("config_digest") !=
                        config_identity(config)):
                    config = {**config, "target": check_target}
            validate(config)
            if not config["io_scope"]["site_ids"]:
                raise ValueError("static selection found no I/O callsites")
        path = case_dir / "state.json"
        # Budgets can grow without changing the JUnit/test/target identity of
        # already completed trials.  A changed workload or fault selector
        # contract still requires a new case directory.
        config_digest = config_identity(config)
        if path.exists():
            state = json.loads(path.read_text())
            if state["config_digest"] != config_digest:
                raise ValueError("case config changed; use a new case directory")
            if state.get("typed_zookeeper_fault_version", 0) < 1:
                # Promote pending selectors in place; completed sequences keep
                # their original identity and are never rerun on resume.
                seen = set(state.get("seen_sequences", []))
                queue = []
                queue_ids = set()
                for queued in state.get("queue", []):
                    sequence = [fault_point_for_io(point)
                                for point in queued["sequence"]]
                    new_id = sequence_id(sequence)
                    if new_id in queue_ids:
                        continue
                    queue.append({**queued, "id": new_id,
                                  "sequence": sequence})
                    queue_ids.add(new_id)
                    seen.add(new_id)
                state["queue"] = queue
                state["seen_sequences"] = dict.fromkeys(sorted(seen), True)
                state["typed_zookeeper_fault_version"] = 1
            state.setdefault("active_runtime_seconds", 0.0)
            state.setdefault("seed_runtime_seconds", 0.0)
            state.setdefault("fault_runtime_seconds", 0.0)
            state.setdefault("io_families", [])
            # Preserve the selection order of a campaign that started before
            # temporal buckets were introduced, including after a restart.
            state.setdefault("temporal_diversity_version", 1)
            state.setdefault("late_occurrence_diversity_version", 1)
            state.setdefault("exact_late_occurrence_version", 1)
            state.setdefault("repeated_reply_loss_version", 1)
            state.setdefault("deep_sequence_version", 1)
            state.setdefault("same_actor_followup_version", 1)
            state.setdefault("cross_actor_diversity_version", 1)
            state.setdefault("response_shape_diversity_version", 1)
            state.setdefault("reply_fanout_diversity_version", 1)
            state.setdefault("reply_chain_diversity_version", 1)
            if state.get("fault_family_version", 0) < 2:
                observed = state.get("seed", {}).get("feedback", {}).get(
                    "points", []) if state.get("seed") else []
                families = {fault_family(point) for point in observed}
                for completed in state.get("completed", []):
                    result_path = Path(completed["result"])
                    if result_path.is_file():
                        result = json.loads(result_path.read_text())
                        families.update(fault_family(point)
                                        for point in result.get("points", []))
                state["io_families"] = sorted(families)
                state["fault_family_version"] = 2
            if state.get("identity_priority_version", 0) < 1:
                for queued in state.get("queue", []):
                    queued["priority"] += identity_priority(
                        queued["sequence"][-1])
                state["identity_priority_version"] = 1
            if state.get("static_priority_version", 0) < 1:
                priorities = config.get("_static_io_priority", {})
                for queued in state.get("queue", []):
                    queued["priority"] += priorities.get(
                        queued["sequence"][-1]["siteId"], 0)
                state["static_priority_version"] = 1
            if state.get("target_proximity_version", 0) < 1:
                seed_trace = Path((state.get("seed") or {}).get("trace", ""))
                proximity = (observed_proximity(trace_feedback(
                    seed_trace, config["target"], config.get("io_scope")))
                    if seed_trace.is_file() else {})
                for queued in state.get("queue", []):
                    near = proximity.get(observed_identity(
                        queued["sequence"][-1]), 0)
                    queued["priority"] += near
                    queued["target_proximity"] = near
                state["target_proximity_version"] = 1
            state.setdefault("setup_seconds", float(config.get("setup_seconds", 0)))
            state.setdefault("build_seconds", float(config.get("build_seconds", 0)))
            state.setdefault("target_method", config["target"]["method"])
            state.setdefault("target_throw_method", config["target"].get(
                "throw_method", config["target"]["method"]))
            state.setdefault("target_throw_site_id", config["target"].get(
                "throw_site_id"))
            state.setdefault("target_source_file", config["target"].get("source_file"))
            state.setdefault("target_source_line", config["target"].get("source_line"))
            state.setdefault("target_code", config["target"].get("code"))
            state.setdefault("coverage_exclude_sites",
                             config["target"].get("coverage_exclude_sites", []))
            state.setdefault("coverage_include_prefixes",
                             config["target"].get("coverage_include_prefixes", []))
            state.setdefault("static_selection_digest", config.get(
                "_static_selection_digest"))
            state.setdefault("static_selection_artifact", config.get(
                "_static_selection_artifact"))
            if state.get("status") in TERMINAL:
                return state
        else:
            state = {"schemaVersion": SCHEMA, "case_id": config["case_id"],
                     "system": config["system"], "test_class": config["test_class"],
                     "test_method": config["test_method"],
                     "target_method": config["target"]["method"],
                     "target_throw_method": config["target"].get(
                         "throw_method", config["target"]["method"]),
                     "target_throw_site_id": config["target"].get("throw_site_id"),
                     "target_source_file": config["target"].get("source_file"),
                     "target_source_line": config["target"].get("source_line"),
                     "target_code": config["target"].get("code"),
                     "coverage_exclude_sites": config["target"].get(
                         "coverage_exclude_sites", []),
                     "coverage_include_prefixes": config["target"].get(
                         "coverage_include_prefixes", []),
                     "static_selection_digest": config.get(
                         "_static_selection_digest"),
                     "static_selection_artifact": config.get(
                         "_static_selection_artifact"),
                     "config_digest": config_digest, "seed": None,
                     "coverage": [], "queue": [], "seen_sequences": {},
                     "io_families": [], "active_runtime_seconds": 0.0,
                     "identity_priority_version": 1,
                     "fault_family_version": 2,
                     "static_priority_version": 1,
                     "target_proximity_version": 1,
                     "temporal_diversity_version": 2,
                     "late_occurrence_diversity_version": 1,
                     "exact_late_occurrence_version": 1,
                     "repeated_reply_loss_version": 1,
                     "deep_sequence_version": 1,
                     "same_actor_followup_version": 1,
                    "cross_actor_diversity_version": 1,
                    "response_shape_diversity_version": 1,
                    "reply_fanout_diversity_version": 1,
                    "reply_chain_diversity_version": 1,
                     "site_diversity_version": 2,
                     "typed_zookeeper_fault_version": 1,
                     "seed_runtime_seconds": 0.0,
                     "fault_runtime_seconds": 0.0,
                     "setup_seconds": float(config.get("setup_seconds", 0)),
                     "build_seconds": float(config.get("build_seconds", 0)),
                     "active": None, "completed": [], "started": time.time()}
            if config.get("status") in TERMINAL:
                state["status"] = config["status"]
            atomic_json(path, state)
            if state.get("status") in TERMINAL:
                write_case_result(case_dir, state)
                return state
        external = case_dir / "result.json"
        if external.is_file():
            review = json.loads(external.read_text())
            if review.get("status") in TERMINAL:
                state["status"] = review["status"]
                atomic_json(path, state)
                return state
        if state["seed"] is None:
            ensure_seed(config, state, case_dir)
            atomic_json(path, state)
            write_case_result(case_dir, state)
        elif state.get("status") == "healthy_target_unreached":
            # Older checkpoints stopped before trying faults when the clean
            # run did not enter the check. A fault can expose that branch.
            priorities = config.get("_static_io_priority", {})
            for observed in state["seed"]["feedback"].get("points", []):
                for point in fault_variants_for_io(
                        observed, config.get("_static_io_exceptions")):
                    enqueue(state, [point], priority=20 + identity_priority(point) +
                            priorities.get(point["siteId"], 0))
            state["status"] = "fuzzing"
            state["finished"] = False
            atomic_json(path, state)
            write_case_result(case_dir, state)
        if state.get("status") in {"no_io_fault_points",
                                   "healthy_target_unreached"}:
            state["finished"] = False
            atomic_json(path, state)
            write_case_result(case_dir, state)
            return state
        # A larger max_faults budget can grow from saved actual traces even
        # when the previous run ended exactly at its old depth limit.
        for completed in state["completed"]:
            sequence = completed.get("sequence")
            if isinstance(sequence, list) and sequence:
                result = json.loads(Path(completed["result"]).read_text())
                enqueue_extensions(state, sequence, result,
                                   config["budget"]["max_faults"],
                                   config.get("_static_io_priority"),
                                   config.get("_static_io_exceptions"))
        max_runtime = config["budget"].get("max_seconds", 1e18)
        can_resume = (budget_has_room(state, config["budget"]) and
                      (state["active"] or state["active_runtime_seconds"] < max_runtime) and
                      (state["queue"] or state["active"]))
        if can_resume and state.get("finished"):
            # A larger budget may reopen an exhausted checkpoint. Publish the
            # active state before its next trial so mirrors do not mistake it
            # for a terminal result from the previous budget.
            state["finished"] = False
            if state.get("status") in {"budget_or_queue_complete",
                                       "no_valid_target_trial"}:
                state["status"] = "fuzzing"
            atomic_json(path, state)
            write_case_result(case_dir, state)
        while (budget_has_room(state, config["budget"]) and
               (state["active"] or state["active_runtime_seconds"] < max_runtime) and
               (state["queue"] or state["active"])):
            if state["active"] is None:
                item = state["queue"].pop(choose_next_sequence(
                    state, config.get("_static_io_priority")))
                state["active"] = {**item, "number": len(state["completed"]) + 1}
                atomic_json(path, state)
            process_trial(config, state, case_dir, state["active"])
            atomic_json(path, state)
            write_case_result(case_dir, state)
        state["last_updated"] = time.time()
        state["finished"] = bool(not state["active"] and
                                 (not state["queue"] or
                                  not budget_has_room(state, config["budget"]) or
                                  state["active_runtime_seconds"] >= max_runtime))
        if state["finished"] and state.get("status") not in TERMINAL:
            valid_trial_statuses = {"checked", "target_exception_candidate",
                                    "partial_target_exception_candidate",
                                    "baseline_exception_recurrence"}
            state["status"] = (
                "budget_or_queue_complete" if any(
                    item["status"] in valid_trial_statuses
                    for item in state["completed"])
                else "no_valid_target_trial")
        atomic_json(path, state)
        write_case_result(case_dir, state)
        return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    result = campaign(config, args.root)
    print(json.dumps({"case_id": result["case_id"],
                      "trials": len(result["completed"]),
                      "candidates": sum(c["status"] == "target_exception_candidate"
                                        for c in result["completed"]),
                      "remaining": len(result["queue"]),
                      "finished": result["finished"]}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"fuzzer: {error}", file=sys.stderr)
        sys.exit(2)
