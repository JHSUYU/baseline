"""Strict per-trial oracle and target-related runtime feedback."""

from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
from typing import Any

from .events import Trace, event_address, event_seq
from .graph import OccurrenceGraph


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:20]


def _target_match(event: dict[str, Any], target: dict[str, Any], *, throwing: bool) -> bool:
    sites = ([target.get("throw_site", target.get("site"))] if throwing else
             target.get("check_sites", [target.get("site")]))
    if event.get("site") not in sites:
        return False
    if "nodes" in target and event.get("node") not in target["nodes"]:
        return False
    for key in ("node", "occurrence", "epoch"):
        if key in target and event.get(key) != target[key]:
            return False
    return True


def _named_node(node: Any) -> bool:
    return isinstance(node, str) and node not in ("", "unknown", "null", "None")


def _fault_ids(plan: list[dict[str, Any]]) -> list[str]:
    return [str(item["fault_id"]) for item in plan]


def _skip_graph_for_missing_target(expected: list[str],
                                   checks: list[dict[str, Any]],
                                   throws: list[dict[str, Any]]) -> bool:
    return not expected and not checks and not throws


def analyze(trace: Trace, target: dict[str, Any], plan: list[dict[str, Any]],
            *, return_code: int | None, timed_out: bool,
            allow_local_timeline_doors: bool = False,
            allow_node_timeline_guidance: bool = False,
            reject_coarse_roots: bool = False,
            require_event_time_paths: bool = False,
            bootstrap_without_target: bool = False) -> dict[str, Any]:
    events = trace.events
    truncated = [e for e in events if e.get("type") == "TRACE_TRUNCATED"]
    expected = _fault_ids(plan)
    matched = [e for e in events if e.get("type") == "FAULT_MATCHED"
               and e.get("fault_id") in expected]
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
               and e.get("fault_id") in expected]
    unexpected = [e for e in events if e.get("type") == "FAULT_APPLIED"
                  and e.get("fault_id") not in expected]
    matched_ids = [str(e["fault_id"]) for e in matched]
    applied_ids = [str(e["fault_id"]) for e in applied]
    all_matched = all(matched_ids.count(fid) == 1 for fid in expected)
    all_applied = all(applied_ids.count(fid) == 1 for fid in expected)
    fault_order_valid = ([applied_ids.index(fid) for fid in expected] ==
                         list(range(len(expected)))) if all_applied else False
    pairing_order_valid = (all(event_seq(next(e for e in matched if e["fault_id"] == fid)) <
                               event_seq(next(e for e in applied if e["fault_id"] == fid))
                               for fid in expected) if all_matched and all_applied else False)
    def identity_matches(event: dict[str, Any], fault: dict[str, Any]) -> bool:
        point = fault["point"]
        if "door_ordinal" in point:
            # The ordinal agent emits the replay identity on both receipts.
            # A fault ID alone cannot attest that it matched the intended I/O.
            return all(event.get(key) == point[key]
                       for key in ("site", "node", "epoch", "door_ordinal"))
        return all(event[key] == value for key, value in point.items() if key in event)

    fault_identity_valid = (all(identity_matches(event, fault)
                                for fault in plan
                                for event in matched + applied
                                if event.get("fault_id") == fault["fault_id"])
                            if all_matched and all_applied else False)
    relative_identity_valid = all_matched and all_applied
    if relative_identity_valid:
        applied_by_id = {e["fault_id"]: e for e in applied}
        matched_by_id = {e["fault_id"]: e for e in matched}
        for index, fault in enumerate(plan):
            point = fault["point"]
            receipt = matched_by_id[fault["fault_id"]]
            same = point.get("same_node_as")
            after = point.get("after_fault")
            if same is not None:
                if not isinstance(same, int) or same < 0 or same >= index:
                    relative_identity_valid = False
                    break
                prior = applied_by_id[plan[same]["fault_id"]]
                if (receipt.get("node"), receipt.get("epoch")) != (
                        prior.get("node"), prior.get("epoch")):
                    relative_identity_valid = False
                    break
            if after is not None:
                if not isinstance(after, int) or after < 0 or after >= index:
                    relative_identity_valid = False
                    break
                anchor = applied_by_id[plan[after]["fault_id"]]
                if event_seq(anchor) >= event_seq(receipt):
                    relative_identity_valid = False
                    break
                relative_hit = point.get("relative_hit")
                if relative_hit is not None:
                    eligible = [e for e in events
                                if e.get("type") == "DOOR_OBSERVED"
                                and e.get("site") == point["site"]
                                and (e.get("node"), e.get("epoch")) == (
                                    receipt.get("node"), receipt.get("epoch"))
                                and all(e.get(key) == point[key] for key in (
                                    "occurrence", "hit", "door_ordinal") if key in point)
                                and event_seq(anchor) < event_seq(e) < event_seq(receipt)]
                    if (not isinstance(relative_hit, int) or relative_hit <= 0 or
                            len(eligible) != relative_hit):
                        relative_identity_valid = False
                        break
            elif point.get("relative_hit") is not None:
                relative_identity_valid = False
                break
    effective = (bool(expected) and all_matched and all_applied and
                 fault_order_valid and pairing_order_valid and
                 fault_identity_valid and relative_identity_valid and not unexpected)
    last_fault_seq = max((event_seq(e) for e in applied), default=-1)

    all_checks = [e for e in events if e.get("type") == "TARGET_CHECK"
                  and _target_match(e, {k: v for k, v in target.items() if k != "nodes"},
                                    throwing=False)]
    throw_site_events = [e for e in events if e.get("type") == "TARGET_THROW"
                         and _target_match(e, {k: v for k, v in target.items()
                                               if k != "nodes"}, throwing=True)]
    all_throws = [e for e in throw_site_events
                  if e.get("exception_class") == target.get("exception_class")]
    identity_gaps = [e for e in all_checks + all_throws if not _named_node(e.get("node"))]
    checks = [e for e in all_checks if _target_match(e, target, throwing=False)]
    throws = [e for e in all_throws if _target_match(e, target, throwing=True)]
    post_checks = [e for e in checks if event_seq(e) > last_fault_seq]
    post_throws = [e for e in throws if event_seq(e) > last_fault_seq]
    # Unnamed startup actors are recorded as identity gaps. A later named
    # occurrence can still anchor the campaign; unnamed throws never qualify.
    named_events = [e for e in checks + throws if _named_node(e.get("node"))]
    target_identity_complete = all(event_address(e) is not None for e in named_events)
    target_region_present = all(isinstance(e.get("region"), str) and e["region"]
                                for e in named_events)
    target_instances = sorted({(str(e.get("node")), e.get("epoch"),
                                str(e.get("occurrence"))) for e in checks + throws})
    target_ambiguous = False
    target_reached = bool(post_checks or post_throws) if expected else bool(checks or throws)
    target_check_reached = bool(post_checks) if expected else bool(checks)
    target_check_actors = sorted({str(e["node"]) for e in (post_checks if expected else checks)
                                  if _named_node(e.get("node")) and
                                  event_address(e) is not None and
                                  isinstance(e.get("region"), str) and e["region"]})
    target_threw = bool(post_throws) if expected else bool(throws)
    qualifying_throws = [e for e in post_throws
                         if _named_node(e.get("node")) and any(
                             (check.get("node"), check.get("epoch"), check.get("occurrence")) ==
                             (e.get("node"), e.get("epoch"), e.get("occurrence"))
                             and event_seq(check) < event_seq(e) for check in post_checks)]
    target_exception_candidate = (not truncated and effective and target_reached and target_threw and
                                  target_identity_complete and target_region_present and
                                  bool(qualifying_throws))

    # Multiple visits on one logical actor are legitimate (including restart
    # epochs). Keep each anchor's closure separate and also expose their union
    # for scheduling. No target occurrence means no dynamic closure.
    anchor_events = ([e for e in post_checks + post_throws if _named_node(e.get("node"))]
                     if expected else [e for e in checks + throws if _named_node(e.get("node"))])
    # A fault-free run with no exact target event cannot seed a causal closure.
    # Preserve its oracle, global coverage, and observed doors, but avoid the
    # expensive whole-trace graph build. The raw trace remains available for
    # diagnosis; the summary explicitly says that edges were not computed.
    graph_skipped = (_skip_graph_for_missing_target(expected, all_checks,
                                                   throw_site_events) or
                     bootstrap_without_target and not all_checks and
                     not throw_site_events)
    graph = (None if graph_skipped else OccurrenceGraph(events, reject_coarse_roots=(
        reject_coarse_roots or require_event_time_paths)))
    graph_gaps: dict[str, int] = {} if graph_skipped else graph.gaps
    anchors: dict[tuple[Any, ...], dict[str, Any]] = {}
    time_reachability = []
    time_edges = set()
    for event in anchor_events:
        identity = (event.get("node"), event.get("epoch"), event.get("occurrence"))
        if require_event_time_paths:
            identity += (event.get("id"),)
        if identity not in anchors:
            address = event_address(event)
            if require_event_time_paths:
                reach = graph.backward_event_reachability(event, include_candidates=True)
                time_reachability.append(reach)
                time_edges.update(edge for path in reach.paths.values() for edge in path)
                occurrences = sorted({key[0] for key in reach.cutoffs})
            else:
                occurrences = sorted(graph.backward_closure(address)) if address else []
            anchors[identity] = {"node": identity[0], "epoch": identity[1],
                                 "occurrence": identity[2], "anchor": address,
                                 "closure_occurrences": occurrences}
            if require_event_time_paths:
                anchors[identity]["anchor_event_id"] = event.get("id")
                anchors[identity]["anchor_seq"] = event_seq(event)
    target_closures = list(anchors.values())
    anchor = target_closures[0]["anchor"] if target_closures else None
    closure = {occurrence for row in target_closures
               for occurrence in row["closure_occurrences"]}
    edge_rows = [{"source": e.source, "target": e.target, "kind": e.kind,
                  "evidence": e.evidence, "certainty": e.certainty,
                  "producer_event": e.producer_event,
                  "consumer_event": e.consumer_event}
                 for e in sorted(time_edges if require_event_time_paths else
                                 (graph.edges | graph.candidate_edges if graph else set()),
                                 key=lambda e: (e.source, e.target, e.kind))
                 if e.target in closure and e.source in closure]

    coverage: set[str] = set()
    closure_coverage_set: set[str] = set()
    coverage_definitions: dict[int, str] = {}
    coverage_ids_to_refs: dict[str, int] = {}
    coverage_ref_errors: list[str] = []
    for e in events:
        kind = e.get("type")
        if kind == "COVERAGE_DEF":
            ref, coverage_id = e.get("coverage_ref"), e.get("coverage_id")
            if (isinstance(ref, bool) or not isinstance(ref, int) or ref <= 0 or
                    not isinstance(coverage_id, str) or not coverage_id):
                coverage_ref_errors.append(f"invalid_definition:{e.get('id')}")
            elif ref in coverage_definitions and coverage_definitions[ref] != coverage_id:
                coverage_ref_errors.append(f"conflicting_ref:{ref}")
            elif coverage_id in coverage_ids_to_refs and coverage_ids_to_refs[coverage_id] != ref:
                coverage_ref_errors.append(f"conflicting_id:{coverage_id}")
            else:
                coverage_definitions[ref] = coverage_id
                coverage_ids_to_refs[coverage_id] = ref
            continue
        if kind == "COVERAGE_SUMMARY":
            ids: set[str] = set()
            legacy_ids = e.get("coverage_ids")
            if legacy_ids is not None:
                if not isinstance(legacy_ids, list):
                    coverage_ref_errors.append(f"invalid_coverage_ids:{e.get('id')}")
                else:
                    ids.update(item for item in legacy_ids if isinstance(item, str) and item)
            refs = e.get("coverage_refs")
            if refs is not None:
                if not isinstance(refs, list):
                    coverage_ref_errors.append(f"invalid_coverage_refs:{e.get('id')}")
                else:
                    seen_refs: set[int] = set()
                    for ref in refs:
                        if isinstance(ref, bool) or not isinstance(ref, int) or ref <= 0:
                            coverage_ref_errors.append(f"invalid_ref:{e.get('id')}:{ref}")
                        elif ref in seen_refs:
                            coverage_ref_errors.append(f"duplicate_ref:{e.get('id')}:{ref}")
                        elif ref not in coverage_definitions:
                            coverage_ref_errors.append(f"undefined_ref:{e.get('id')}:{ref}")
                        else:
                            ids.add(coverage_definitions[ref])
                            seen_refs.add(ref)
            coverage.update(ids)
            if (any(reach.witness(e) is not None for reach in time_reachability)
                    if require_event_time_paths else event_address(e) in closure):
                closure_coverage_set.update(ids)
            continue
        if e.get("coverage_id") is not None:
            coverage_id = str(e["coverage_id"])
        elif kind == "BRANCH" and e.get("site") is not None and "outcome" in e:
            coverage_id = "branch:" + str(e["site"]) + ":" + str(e["outcome"])
        elif kind == "METHOD" and e.get("site") is not None:
            coverage_id = "method:" + str(e["site"])
        else:
            continue
        coverage.add(coverage_id)
        if (kind in {"BRANCH", "METHOD"} and
                (any(reach.witness(e) is not None for reach in time_reachability)
                 if require_event_time_paths else event_address(e) in closure)):
            closure_coverage_set.add(str(e.get("coverage_id") or
                                         f"{kind}:{e.get('site')}:{e.get('outcome', '')}"))
    closure_coverage = sorted(closure_coverage_set)
    if coverage_ref_errors:
        target_exception_candidate = False

    doors: list[dict[str, Any]] = []
    last_target_seq = max((event_seq(e) for e in anchor_events), default=-1)
    local_checks: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    local_check_seqs: dict[tuple[Any, Any, Any], list[int]] = {}
    node_checks: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    node_check_seqs: dict[tuple[Any, Any], list[int]] = {}
    if allow_local_timeline_doors:
        for check in (post_checks if expected else checks):
            if _named_node(check.get("node")) and event_address(check) is not None:
                identity = (check.get("node"), check.get("epoch"), check.get("occurrence"))
                local_checks.setdefault(identity, []).append(check)
        for identity, rows in local_checks.items():
            rows.sort(key=event_seq)
            local_check_seqs[identity] = [event_seq(check) for check in rows]
    if allow_node_timeline_guidance:
        for check in (post_checks if expected else checks):
            if _named_node(check.get("node")) and event_address(check) is not None:
                identity = (check.get("node"), check.get("epoch"))
                node_checks.setdefault(identity, []).append(check)
        for identity, rows in node_checks.items():
            rows.sort(key=event_seq)
            node_check_seqs[identity] = [event_seq(check) for check in rows]
    seen_doors: set[str] = set()
    for e in events:
        if e.get("type") != "DOOR_OBSERVED" or not e.get("site"):
            continue
        if not _named_node(e.get("node")):
            graph_gaps["door_unknown_actor"] = graph_gaps.get("door_unknown_actor", 0) + 1
            continue
        if last_target_seq >= 0 and event_seq(e) >= last_target_seq:
            continue
        # A transport's occurrence can contain random client/call IDs and is
        # useful only inside this trace. The agent's per-node/epoch/site door
        # ordinal is the stable cross-run replay identity. Never mix it with
        # the volatile occurrence or the older per-occurrence hit counter.
        ordinal = e.get("door_ordinal")
        if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
            point = {key: e[key] for key in ("site", "node", "epoch")
                     if key in e and e[key] is not None}
            point["door_ordinal"] = ordinal
            required = {"site", "node", "epoch", "door_ordinal"}
        else:
            point = {key: e[key] for key in ("site", "occurrence", "node", "epoch", "hit")
                     if key in e and e[key] is not None}
            required = {"site", "occurrence", "node", "epoch", "hit"}
        if set(point) != required:
            continue
        key = digest(point)
        if key in seen_doors:
            continue
        seen_doors.add(key)
        door = {"point": point, "fault_type": e.get("fault_type"),
                "fault_types": e.get("fault_types"),
                "exception_class": e.get("exception_class"),
                "in_closure": (any(reach.witness(e) is not None
                                   for reach in time_reachability)
                               if require_event_time_paths else event_address(e) in closure),
                "site": e["site"], "event_id": e.get("id"),
                "event_seq": event_seq(e)}
        if allow_node_timeline_guidance and not door["in_closure"]:
            identity = (e.get("node"), e.get("epoch"))
            rows = node_checks.get(identity, [])
            index = bisect_right(node_check_seqs.get(identity, []), event_seq(e))
            if index < len(rows) and event_seq(e) >= 0:
                check = rows[index]
                # This is an observed ordering on one logical JVM, not a
                # happens-before edge between its unrelated threads.
                door["node_timeline_candidate"] = {
                    "kind": "same_node_temporal_candidate",
                    "door_event_id": e.get("id"), "door_seq": event_seq(e),
                    "target_check_event_id": check.get("id"),
                    "target_check_seq": event_seq(check),
                    "node": identity[0], "epoch": identity[1],
                    "door_thread_id": e.get("thread_id"),
                    "target_thread_id": check.get("thread_id")}
        if allow_local_timeline_doors:
            identity = (e.get("node"), e.get("epoch"), e.get("occurrence"))
            rows = local_checks.get(identity, [])
            index = bisect_right(local_check_seqs.get(identity, []), event_seq(e))
            if index < len(rows) and event_seq(e) >= 0 and door["in_closure"]:
                check = rows[index]
                if require_event_time_paths and (
                        not isinstance(e.get("thread_id"), int) or
                        isinstance(e.get("thread_id"), bool) or
                        e.get("thread_id") != check.get("thread_id")):
                    doors.append(door)
                    continue
                door["local_timeline_evidence"] = {
                    "kind": "observed_local_timeline", "door_event_id": e.get("id"),
                    "door_seq": event_seq(e), "target_check_event_id": check.get("id"),
                    "target_check_seq": event_seq(check), "node": identity[0],
                    "epoch": identity[1], "occurrence": identity[2]}
        doors.append(door)

    if truncated:
        status = "trace_truncated"
    elif trace.incomplete_last_line:
        status = "trace_incomplete"
    elif coverage_ref_errors:
        status = "coverage_ref_invalid"
    elif timed_out:
        status = "timeout"
    elif not target_identity_complete:
        status = "target_identity_missing"
    elif not target_region_present:
        status = "target_region_missing"
    elif target_ambiguous:
        status = "target_identity_ambiguous"
    elif unexpected:
        status = "unexpected_fault_applied"
    elif expected and all_matched and all_applied and not (
            fault_identity_valid and relative_identity_valid):
        status = "fault_identity_mismatch"
    elif expected and not effective:
        status = "fault_unmatched"
    elif not target_reached:
        status = "target_lost" if expected else "healthy_target_missing"
    elif target_exception_candidate:
        status = "target_exception_candidate"
    elif not expected and target_threw:
        status = "healthy_target_exception"
    elif return_code not in (0, None):
        status = "workload_failed_other"
    else:
        status = "observed"
    if graph is None:
        graph_summary = {
            "occurrences": len({event_address(e) for e in events} - {None}),
            "edges": 0, "candidate_edges": 0,
            "edges_by_kind": {}, "candidate_edges_by_kind": {},
            "gaps": dict(sorted(graph_gaps.items())),
            "analysis_skipped": ("bootstrap_target_absent" if expected else
                                 "healthy_target_absent"),
        }
    else:
        graph_summary = graph.summary()
    feedback = {"status": status, "matched_fault_ids": matched_ids,
            "applied_fault_ids": applied_ids, "all_faults_matched": all_matched,
            "all_faults_applied": all_applied, "fault_order_valid": fault_order_valid,
            "all_faults_effective": effective,
            "pairing_order_valid": pairing_order_valid,
            "fault_identity_valid": fault_identity_valid,
            "relative_identity_valid": relative_identity_valid,
            "unexpected_applied_fault_ids": [e.get("fault_id") for e in unexpected],
            "target_reached": target_reached, "target_threw": target_threw,
            "target_check_reached": target_check_reached,
            "target_check_actors": target_check_actors,
            "target_throw_evidence": [
                {key: e.get(key) for key in ("id", "seq", "node", "epoch",
                                           "occurrence", "site", "exception_class")}
                for e in post_throws],
            "qualified_target_throw_evidence": [
                {key: e.get(key) for key in ("id", "seq", "node", "epoch",
                                           "occurrence", "site", "exception_class")}
                for e in qualifying_throws],
            "target_instances": [{"node": n, "epoch": epoch, "occurrence": occurrence}
                                 for n, epoch, occurrence in target_instances],
            "target_identity_complete": target_identity_complete,
            "target_region_present": target_region_present,
            "target_identity_ambiguous": target_ambiguous,
            "target_identity_gaps": [
                {key: e.get(key) for key in ("id", "seq", "node", "epoch", "occurrence", "site")}
                for e in identity_gaps],
            "target_exception_candidate": target_exception_candidate,
            "target_anchor": anchor, "closure_occurrences": sorted(closure),
            "target_closures": target_closures,
            "require_event_time_paths": require_event_time_paths,
            "reject_coarse_roots": bool(reject_coarse_roots or require_event_time_paths),
            "last_fault_seq": last_fault_seq,
            "closure_edges": edge_rows, "graph": graph_summary,
            "coverage_ids": sorted(coverage), "closure_coverage_ids": closure_coverage,
            "coverage_ref_errors": coverage_ref_errors,
            "doors": doors,
            "trace_truncated": bool(truncated),
            "trace_truncation_events": [
                {key: event.get(key) for key in ("id", "seq", "reason", "dropped_type",
                                                  "max_events", "max_bytes")}
                for event in truncated],
            "observed_door_events": sum(e.get("type") == "DOOR_OBSERVED" for e in events),
            "eligible_doors_before_target": len(doors),
            "event_count": len(events)}
    if allow_local_timeline_doors:
        feedback["local_timeline_doors"] = sum(
            "local_timeline_evidence" in door for door in doors)
        feedback["allow_local_timeline_doors"] = True
    if allow_node_timeline_guidance:
        feedback["node_timeline_candidate_doors"] = sum(
            "node_timeline_candidate" in door for door in doors)
        feedback["allow_node_timeline_guidance"] = True
    return feedback
