"""What one JUnit run says about the selected check.

``trace_feedback`` reads a runtime trace and reports: the fault points the
run observed and applied, its coverage, whether the target check executed
(and again after the last applied fault), and the oracle -- the target's
typed exception, on a complete fatal guard route, inside the target call,
after the last applied fault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .faults import FAULT_EVENTS, in_io_scope, point_from_event
from .trace import fingerprint, rows

Event = dict[str, Any]
CHECK_EVENT_KINDS = {"BRANCH", "CHECK_REACHED", "CALL_SITE_ENTER", "CALL_SITE_RETURN",
                     "CALL_SITE_THROW"}
THROW_EVENT_KINDS = {"METHOD_EXIT_THROW", "EXPLICIT_THROW", "CALL_SITE_THROW"}


def fatal_guard_paths(target: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Alternative bytecode routes to one selected throw site.

    Each route is an ordered conjunction of branch outcomes; routes are
    disjunctive. A TARGET_SITE row supplies one route unless a case states
    independently checked alternatives.
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


class _TargetCalls:
    """Which events belong to an invocation of the target method."""

    def __init__(self, events: list[Event], target: dict[str, Any]):
        self.method = target["method"]
        self.occurrence = target.get("occurrence")
        self.calls: set[int] = set()          # target invocations (call ids)
        self.parents: dict[int, int] = {}     # call id -> parent call id
        self.entries: dict[int, int] = {}     # target call id -> entry seq
        self.exits: dict[int, int] = {}       # target call id -> exit seq
        self.reached = False                  # a target invocation at the occurrence
        for event in events:
            kind = event.get("event")
            call_id = event.get("callId")
            if kind == "METHOD_ENTER" and isinstance(call_id, int):
                self.parents[call_id] = event.get("parentCallId", 0)
                if event.get("method") == self.method:
                    self.entries[call_id] = event.get("seq", -1)
                    if (not self.occurrence or
                            event.get("occurrenceAddress") == self.occurrence):
                        self.reached = True
                        self.calls.add(call_id)
            if (kind in {"METHOD_EXIT_NORMAL", "METHOD_EXIT_THROW"} and
                    event.get("method") == self.method and isinstance(call_id, int)):
                self.exits[call_id] = event.get("seq", -1)

    def owner_of_call(self, call_id: Any) -> int | None:
        """The target invocation a call id runs inside, walking parents."""
        seen: set[int] = set()
        while isinstance(call_id, int) and call_id > 0 and call_id not in seen:
            if call_id in self.calls:
                return call_id
            seen.add(call_id)
            call_id = self.parents.get(call_id)
        return None

    def owner(self, event: Event) -> int | None:
        """The target invocation an event belongs to, if exactly one."""
        owner = self.owner_of_call(event.get("callId"))
        if owner is not None:
            return owner
        if event.get("method") != self.method:
            return None
        seq = event.get("seq", -1)
        enclosing = [call_id for call_id, entered in self.entries.items()
                     if entered <= seq <= self.exits.get(call_id, float("inf"))]
        return enclosing[0] if len(enclosing) == 1 and enclosing[0] in self.calls else None

    def contains(self, event: Event) -> bool:
        if self.owner(event) is not None:
            return True
        # Some recorder hooks emit callId=0 for bytecode events; the exact
        # method still identifies the check when no occurrence is required.
        if event.get("method") != self.method:
            return False
        return not self.occurrence or event.get("occurrenceAddress") == self.occurrence


def _coverage_filter(target: dict[str, Any]):
    include_prefixes = target.get("coverage_include_prefixes", [])
    include_methods = set(target.get("coverage_include_methods", []))

    def in_scope(event: Event) -> bool:
        method = event.get("method") or event.get("siteId", "").split("#u", 1)[0]
        if include_methods:
            return isinstance(method, str) and method in include_methods
        if not include_prefixes:
            return True
        return isinstance(method, str) and any(method.startswith(prefix)
                                               for prefix in include_prefixes)
    return in_scope


def trace_feedback(path: Path, target: dict[str, Any],
                   io_scope: dict[str, Any] | None = None) -> dict[str, Any]:
    events = list(rows(path))
    calls = _TargetCalls(events, target)
    covered = _coverage_filter(target)
    excluded_sites = set(target.get("coverage_exclude_sites", []))
    throw_event = target.get("throw_event", "METHOD_EXIT_THROW")
    explicit_lines = set(target.get("explicit_throw_lines", []))

    # One pass: fault points, coverage, and candidate target throws.
    points: dict[str, dict[str, Any]] = {}
    point_events: list[dict[str, Any]] = []
    matched: list[Event] = []
    applied: list[Event] = []
    coverage: set[str] = set()
    thrown_candidates: list[Event] = []
    summary: dict[str, Any] = {}
    selection_digests: list[str] = []
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
            selection_digests.append(event.get("digest"))
        elif kind == "METHOD_ENTER":
            if event.get("method") and covered(event):
                coverage.add("METHOD:" + event["method"])
        elif kind == "BRANCH":
            site = event.get("siteId")
            if site and site not in excluded_sites and covered(event):
                coverage.add("BRANCH:" + site + ":" + str(event.get("outcome")))
        elif kind in {"CALL_SITE_ENTER", "CALL_SITE_RETURN", "CALL_SITE_THROW"}:
            site = event.get("siteId")
            if site and site not in excluded_sites and covered(event):
                coverage.add("CALL_SITE:" + site + ":" + kind)
        if (kind == throw_event and
                event.get("method") == target.get("throw_method", target["method"]) and
                (throw_event != "EXPLICIT_THROW" or
                 ((target.get("explicit_throw_site_id") is None or
                   event.get("siteId") == target["explicit_throw_site_id"]) and
                  (not explicit_lines or event.get("sourceLine") in explicit_lines)))):
            thrown_candidates.append(event)

    # A CALL_SITE_RETURN/THROW counts only after its own CALL_SITE_ENTER.
    call_site_enters: dict[tuple[Any, ...], list[int]] = {}
    for event in events:
        if (event.get("event") == "CALL_SITE_ENTER" and
                isinstance(event.get("invocationId"), int) and event["invocationId"] > 0):
            key = (event.get("method"), event.get("siteId"), event["invocationId"],
                   event.get("sourceKey"), event.get("tid"))
            call_site_enters.setdefault(key, []).append(event.get("seq", -1))

    def paired_call_site(event: Event) -> bool:
        invocation = event.get("invocationId")
        if event.get("event") == "CALL_SITE_ENTER":
            return isinstance(invocation, int) and invocation > 0
        key = (event.get("method"), event.get("siteId"), invocation,
               event.get("sourceKey"), event.get("tid"))
        return (isinstance(invocation, int) and invocation > 0 and
                any(seq < event.get("seq", -1) for seq in call_site_enters.get(key, [])))

    applied_seq = max((e.get("seq", -1) for e in applied), default=-1)
    guard_paths = (fatal_guard_paths(target) if
                   ("fatal_guard_paths" in target or "fatal_guards" in target) else [])
    # The final decision on a throw route is the check to retain after the
    # fault; earlier guards may only enter the function or an outer branch.
    check_sites = (set(target.get("check_site_ids") or []) or
                   {path[-1]["siteId"] for path in guard_paths} or
                   ({target["site_id"]} if target.get("site_id") else set()))
    check_events = set(target.get("check_events", ["BRANCH"] if check_sites else []))
    branch_rows = sorted((e for e in events if e.get("event") == "BRANCH"),
                         key=lambda e: e.get("seq", -1))

    def path_last_seq(path: list[dict[str, Any]], call_id: Any, upper_seq: int) -> int | None:
        """The latest final decision of a complete ordered route before a throw."""
        cursors = {-1}
        for guard in path:
            cursors = {e["seq"] for e in branch_rows
                       if e.get("callId") == call_id and
                       e.get("siteId") == guard["siteId"] and
                       e.get("outcome") is guard["outcome"] and
                       isinstance(e.get("seq"), int) and e["seq"] < upper_seq and
                       any(previous < e["seq"] for previous in cursors)}
            if not cursors:
                return None
        return max(cursors)

    # --- did the check execute (again after the last fault)? -----------------
    check_rows = [e for e in events
                  if e.get("event") in check_events and e.get("siteId") in check_sites and
                  calls.contains(e) and
                  (not e["event"].startswith("CALL_SITE_") or paired_call_site(e))]
    site_seen = bool(check_rows)
    guard_seen = any(e.get("event") == "BRANCH" and e.get("siteId") in check_sites and
                     calls.contains(e) for e in events) or site_seen
    # A check that ran only before the injected fault cannot validate the
    # trial; it must execute again after the last applied fault.
    reached_after_fault = (
        any(e.get("seq", -1) > applied_seq >= 0 for e in check_rows)
        if check_events else
        any(e.get("event") in {"METHOD_ENTER", "BRANCH", "METHOD_EXIT_NORMAL",
                               "METHOD_EXIT_THROW", "EXPLICIT_THROW"} and
            calls.contains(e) and e.get("seq", -1) > applied_seq >= 0 for e in events))
    reached = site_seen if check_sites else calls.reached
    site_after_fault = reached_after_fault if check_sites else False

    def check_outcome(event: Event) -> Any:
        return event.get("outcome") if event.get("event") == "BRANCH" else event.get("event")

    outcomes = [check_outcome(e) for e in check_rows]
    outcomes_after_fault = [check_outcome(e) for e in check_rows
                            if e.get("seq", -1) > applied_seq >= 0]

    # --- the typed throw oracle ---------------------------------------------
    required_throw_site = target.get("throw_site_id")
    if not required_throw_site and "CALL_SITE_THROW" in check_events:
        required_throw_site = target.get("site_id")
    site_throws = [e for e in events
                   if e.get("event") == "CALL_SITE_THROW" and
                   e.get("siteId") == required_throw_site and
                   calls.contains(e) and paired_call_site(e)]
    expected = target["exception_type"]

    def expected_type_seen(thrown: Event) -> bool:
        if expected is None:
            return False
        if thrown.get("runtimeType") == expected:
            return True
        if throw_event != "CALL_SITE_THROW":
            return False
        # CALL_SITE_THROW carries no exception class: use the enclosing
        # typed method exit of the same invocation.
        owner = calls.owner(thrown)
        return owner is not None and any(
            e.get("event") == "METHOD_EXIT_THROW" and
            e.get("method") == target.get("throw_method", target["method"]) and
            e.get("runtimeType") == expected and calls.owner(e) == owner and
            e.get("seq", -1) > thrown.get("seq", -1)
            for e in events)

    exception = False
    exception_count = 0
    fatal_count = 0
    fatal_nodes: list[dict[str, Any]] = []
    after_fault = False
    guard_after_fault = False
    for thrown in thrown_candidates:
        if not (expected_type_seen(thrown) and calls.contains(thrown) and
                (throw_event != "CALL_SITE_THROW" or
                 (thrown.get("siteId") == required_throw_site and
                  paired_call_site(thrown)))):
            continue
        exception = True
        exception_count += 1
        completed_paths = [path_last_seq(path, thrown.get("callId"), thrown.get("seq", -1))
                           for path in guard_paths]
        guard_ok = any(last is not None for last in completed_paths) if guard_paths else True
        site_before_throw = [e for e in site_throws
                             if e.get("seq", -1) <= thrown.get("seq", -1) and
                             calls.owner(e) == calls.owner(thrown)]
        fatal_in_call = guard_ok and (bool(site_before_throw) if required_throw_site else True)
        if fatal_in_call:
            fatal_count += 1
            if thrown.get("logicalNodeId"):
                fatal_nodes.append({"seq": thrown.get("seq", -1),
                                    "logicalNodeId": thrown["logicalNodeId"]})
        if thrown.get("seq", -1) > applied_seq >= 0:
            after_fault = True
            guard_after = (any(last is not None and last > applied_seq
                               for last in completed_paths)
                           if guard_paths else reached_after_fault)
            site_after = (any(e.get("seq", -1) > applied_seq for e in site_before_throw)
                          if required_throw_site else True)
            if guard_after and site_after:
                guard_after_fault = True
            # An exact bytecode throw proves the check ran even when a
            # separate CHECK_REACHED hook is absent or names another unit.
            if (throw_event == "EXPLICIT_THROW" and fatal_in_call and
                    (target.get("explicit_throw_site_id") or explicit_lines)):
                reached = reached_after_fault = True
                site_seen = site_after_fault = True
                guard_seen = guard_after_fault = True
    # With an exact target site declared, a method-level throw alone could
    # be an unrelated nested failure propagating.
    oracle = bool(after_fault and reached and guard_after_fault)
    return {
        "points": list(points.values()),
        "point_events": point_events,
        "coverage": sorted(coverage),
        "matched_count": len(matched),
        "applied_count": len(applied),
        "last_applied_seq": max((e.get("seq", -1) for e in applied), default=-1),
        "applied_points": [p for e in applied if (p := point_from_event(e)) is not None],
        "applied_fault_ids": [e.get("faultId") for e in applied],
        "target_reached": reached,
        "target_reached_after_fault": reached_after_fault,
        "target_site_seen": site_seen,
        "target_site_after_fault": site_after_fault,
        "target_outcomes": outcomes,
        "target_outcomes_after_fault": outcomes_after_fault,
        "target_check_seqs": [e.get("seq", -1) for e in check_rows],
        "target_check_nodes": [{"seq": e.get("seq", -1), "logicalNodeId": e["logicalNodeId"]}
                               for e in check_rows if e.get("logicalNodeId")],
        "target_guard_seen": guard_seen,
        "target_guard_after_fault": guard_after_fault,
        "target_exception": exception,
        "target_exception_count": exception_count,
        "target_fatal_exception_count": fatal_count,
        "target_fatal_exception_nodes": fatal_nodes,
        "target_after_fault": after_fault,
        "oracle": oracle,
        "fault_summary": summary,
        "static_selection_digests": selection_digests,
    }


# --- the Soot selection's view of the target ----------------------------------

def selected_target_throw_lines(selection: dict[str, Any], target: dict[str, Any]) -> list[int]:
    """Source lines of the typed throws the selected check controls.

    Soot unit ordinals and ASM bytecode ordinals are different coordinates;
    their common source line is matched only after Soot establishes the
    branch-to-throw relation. The runtime event supplies the actual type.
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
    # The checklist's exact throw line resolves adjacent checks of the same
    # type before the broader control relation applies.
    exact_lines = {site["line"] for site in typed_sites if site["line"] == selected_line}
    if exact_lines:
        return sorted(exact_lines)
    lines: set[int] = set()
    for site in typed_sites:
        controlled = set(site.get("controlled_by", []))
        if (guard_ids & controlled or site.get("soot_site_id") == target.get("site_id") or
                (not guard_ids and site.get("line") == selected_line)):
            lines.add(site.get("line"))
    return sorted(lines)


def selected_target_control_branches(selection: dict[str, Any], target: dict[str, Any],
                                     throw_lines: list[int]) -> list[str]:
    """The branches nearest the check that control its selected typed throw.

    A Soot throw unit is not necessarily an ASM branch or a source-line
    probe; its controlling branches are recorded at runtime independently.
    """
    if not throw_lines:
        return []
    branches = {row.get("site_id"): row.get("line")
                for row in selection.get("branches", [])
                if row.get("method") == target["method"] and isinstance(row.get("line"), int)}
    selected = [site for site in selection.get("target_throw_sites", [])
                if site.get("method") == target["method"] and
                site.get("thrown_type") == target["exception_type"] and
                site.get("line") in throw_lines and
                (site.get("soot_site_id") == target.get("site_id") or
                 site.get("line") == selection.get("target_selected_line"))]
    controlled = {branch for site in selected for branch in site.get("controlled_by", [])
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
