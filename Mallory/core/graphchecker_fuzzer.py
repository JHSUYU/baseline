"""Resumable, target-guided fuzz loop over native GraphChecker JUnit trials.

The queue contains only fault plans formed from attributed FAULT_DOOR rows in
completed trials. Exact causal closure and static MAY scope have distinct
priorities. Neither an old Mallory event graph nor a static relation can prove
that a fault applied or that the exact target exception ran.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graphchecker_campaign import (_configured_check_sites, _json, _write_json,
                                    _prior_trace_metadata, _prior_trace_profiles,
                                    _sha256, load_config, prepare,
                                    run_trial, verify_trial_artifacts)

SCHEMA = 1
PLAN_FIELDS = ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")
REPLAY_FIELD = "replayOccurrenceId"
TIER_WEIGHT = {"observed_closure": 100, "static_may_observed": 55,
               "selected_scope_observed": 35, "outside_closure": 15,
               "after_target": -100}
SCHEDULER_VERSION = 5
BOOTSTRAP_POLICY_VERSION = 1
CLOSURE_NOVELTY_POLICY_VERSION = 1
BOOTSTRAP_MAX_FAULTS = 3
BOOTSTRAP_MAX_TRIALS = 128
MAX_QUEUE = 5000
MAX_UNMATCHED_RETRIES = 2
MAX_PRODUCER_FRONTIER_CONTINUATIONS = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _budget(config_path: Path) -> dict[str, int]:
    raw = _json(config_path).get("budget")
    if not isinstance(raw, dict):
        raise ValueError("campaign needs budget: fault_trials, seconds, max_faults_per_trial")
    values = {key: raw.get(key) for key in
              ("fault_trials", "seconds", "max_faults_per_trial")}
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
           for value in values.values()):
        raise ValueError("campaign budget values must be positive integers")
    if values["max_faults_per_trial"] > 10:
        raise ValueError("max_faults_per_trial exceeds 10")
    return values


def _plan_key(faults: list[dict[str, Any]]) -> str:
    # The exact seed occurrence is kept in each plan for provenance, but a
    # replay lineage selects the same operation even when that occurrence's
    # per-run RPC correlation changes. Deduplicate by the selector actually
    # used by the controller.
    canonical = []
    for fault in faults:
        item = dict(fault)
        if item.get(REPLAY_FIELD):
            item.pop("occurrenceId", None)
        canonical.append(item)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _actor_site_key(fault: dict[str, Any]) -> str:
    """Group retries by logical node and site, independent of reboot epoch."""
    node = fault["node"]
    base, marker, epoch = node.rpartition("#epoch")
    logical_node = base if marker and epoch.isdigit() else node
    return json.dumps([logical_node, fault["siteId"]], separators=(",", ":"))


def _live_process(trial: Path) -> bool:
    receipt = trial / "process.json"
    if not receipt.is_file():
        return False
    data = _json(receipt)
    pid = data.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat.rsplit(") ", 1)[1].split()
        return fields[19] == data.get("start_ticks") and fields[0] != "Z"
    except (OSError, IndexError):
        return False


def _score(item: dict[str, Any], completed: int) -> float:
    return (TIER_WEIGHT[item["tier"]] + item["novelty"] +
            4 * len(item["faults"]) + min(30, completed - item["enqueued_at"]))


def _retention_score(item: dict[str, Any], completed: int,
                     state: dict[str, Any]) -> float:
    """Bounded feedback; repeated target loss lowers priority, never eligibility."""
    actor_site = _actor_site_key(item["faults"][-1])
    history = state.get("site_target_retention", {}).get(actor_site, {})
    preserved = int(history.get("preserved", 0))
    lost = int(history.get("lost", 0))
    productive = int(history.get("productive", 0))
    attempts = int(state.get("last_fault_actor_site_attempts", {}).get(
        actor_site, 0))
    parent_delta = int(item.get("parent_graph_delta", 0))
    parent_bonus = (24 if parent_delta > 0 else 8) if item.get(
        "parent_target_retained") else 0
    return (_score(item, completed) + parent_bonus + min(20, 5 * preserved)
            + min(15, 5 * productive)
            - min(40, 10 * max(0, lost - preserved))
            - min(18, 3 * attempts))


def _pick(queue: list[dict[str, Any]], completed: int,
          state: dict[str, Any] | None = None) -> dict[str, Any]:
    if state is not None and state.get("scheduler_version", 1) >= 3:
        # Spend a bounded, periodic slot on a second fault after a strict
        # static-producer fault retained the target. This is exploration,
        # never evidence that the producer belongs to the observed closure.
        if completed % 8 == 7:
            continuation = [item for item in queue if item.get(
                "producer_frontier_continuation")]
            if continuation:
                selected = max(continuation, key=lambda item: (
                    _retention_score(item, completed, state),
                    -item["enqueued_at"], item["key"]))
                queue.remove(selected)
                return selected
        # Static MAY and selected scope have periodic slots; one of eighteen
        # is reserved for outside closure when that queue is nonempty.
        outside = [item for item in queue if item["tier"] == "outside_closure"]
        requested = ("outside_closure" if completed % 18 == 17 and outside else
                     {2: "static_may_observed", 5: "selected_scope_observed"}.get(
                         completed % 6))
        candidates = ([item for item in queue if item["tier"] == requested]
                      if requested else [])
        if not candidates:
            candidates = queue
        selected = max(candidates, key=lambda item: (
            _retention_score(item, completed, state),
            -item["enqueued_at"], item["key"]))
        queue.remove(selected)
        return selected
    if state is not None and state.get("scheduler_version", 1) >= 2:
        # Two periodic slots reach observed static candidates even while
        # exact-closure plans are abundant. Neither tier implies causality.
        requested = {2: "static_may_observed", 5: "selected_scope_observed"}.get(
            completed % 6)
        candidates = [item for item in queue if item["tier"] == requested]
        if not candidates:
            candidates = queue
        # Preserve the existing tier score, then prefer a last fault site
        # selected fewer times within that tier (CrashFuzz fault-ID novelty).
        tier = max(candidates, key=lambda item: _score(item, completed))["tier"]
        same_tier = [item for item in candidates if item["tier"] == tier]
        attempts = state.get("last_fault_site_attempts", {})
        selected = max(same_tier, key=lambda item: (
            -int(attempts.get(item["faults"][-1]["siteId"], 0)),
            _score(item, completed), -item["enqueued_at"], item["key"]))
        queue.remove(selected)
        return selected
    # A periodic exploration slot prevents exact-closure sites from starving
    # static MAY and outside-closure sites under a finite trial budget.
    candidates = queue
    if completed % 5 == 4:
        exploratory = [item for item in queue if item["tier"] != "observed_closure"]
        if exploratory:
            candidates = exploratory
    selected = max(candidates, key=lambda item: (_score(item, completed),
                                                -item["enqueued_at"], item["key"]))
    queue.remove(selected)
    return selected


def _novelty(result: dict[str, Any]) -> int:
    """Legacy v1-v4 score: each trial compared only with the healthy run."""
    graph = result.get("graphchecker_feedback", {})
    return min(60, 4 * int(graph.get("newClosureEdges", 0)) +
               2 * int(graph.get("newClosureNodes", 0)) +
               int(graph.get("newClosureCoverageSites", 0)))


_CLOSURE_FAMILY_FIELDS = (
    ("closureNodeFamilies", "seen_target_closure_node_families", 2),
    ("closureEdgeFamilies", "seen_target_closure_edge_families", 4),
    ("closureCoverageSiteIds", "seen_target_closure_coverage_sites", 1),
)
_CLOSURE_FEEDBACK_NAMES = {
    "closureNodeFamilies": "new_node_families",
    "closureEdgeFamilies": "new_edge_families",
    "closureCoverageSiteIds": "new_coverage_sites",
}


def _target_closure_novelty(state: dict[str, Any], result: dict[str, Any]
                            ) -> tuple[int, dict[str, int]]:
    """Credit exact target-closure families only on first campaign observation.

    The graph analyzer emits stable families/coverage IDs as well as counts
    relative to the healthy run. Counts cannot distinguish a new family from
    one that already appeared in an earlier fault trial. Missing family arrays
    never inherit the healthy-relative count as a proxy for identity.
    """
    evidence = result.get("evidence", {})
    if (not evidence.get("target_reached") or result.get(
            "status") == "invalid_graphchecker_trace" or
            (result.get("fault_plan") and not (
                evidence.get("strict_injection") and
                evidence.get("injection_specific_target_reached")))):
        return 0, {}
    graph = result.get("graphchecker_feedback", {})
    if not isinstance(graph, dict):
        raise ValueError("target closure graph feedback missing")
    observed: list[tuple[str, str, int, set[str]]] = []
    for graph_field, state_field, weight in _CLOSURE_FAMILY_FIELDS:
        values = graph.get(graph_field)
        if values is None:
            # A v5 campaign cannot rank a target-reaching trial by a count
            # that cannot establish identity across trials.
            raise ValueError(f"target closure family field missing: {graph_field}")
        if not isinstance(values, list) or any(
                not isinstance(value, str) or not value for value in values):
            raise ValueError(f"invalid target closure family field: {graph_field}")
        observed.append((graph_field, state_field, weight, set(values)))
    feedback: dict[str, int] = {}
    score = 0
    for graph_field, state_field, weight, values in observed:
        seen = set(state[state_field])
        new = values - seen
        state[state_field] = sorted(seen | values)
        feedback[_CLOSURE_FEEDBACK_NAMES[graph_field]] = len(new)
        score += weight * len(new)
    return min(60, score), feedback


def _result_novelty(state: dict[str, Any], result: dict[str, Any]
                    ) -> tuple[int, dict[str, int]]:
    if state.get("scheduler_version", 1) >= 5:
        return _target_closure_novelty(state, result)
    return _novelty(result), {}


def _healthy_target_attribution_missing(evidence: dict[str, Any]) -> bool:
    """Distinguish a reached but unscoped target from a truly absent target."""
    totals = []
    for kind in ("check", "throw"):
        names = (f"raw_target_{kind}_rows",
                 f"unattributed_target_{kind}_rows",
                 f"attributed_target_{kind}_rows")
        values = [evidence.get(name) for name in names]
        if (any(not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in values) or values[0] != values[1] + values[2]):
            raise ValueError(f"invalid healthy target attribution counts: {kind}")
        totals.append((values[0], values[2]))
    return sum(raw for raw, _ in totals) > 0 and sum(
        attributed for _, attributed in totals) == 0


def _bootstrap_sites(result: dict[str, Any]) -> set[str]:
    """Typed, observed I/O in the static selection, never inferred closure."""
    return {door["siteId"] for door in result.get("evidence", {}).get(
        "eligible_doors", []) if door.get("tier") in (
            "static_may_observed", "selected_scope_observed") and
            all(door.get(key) for key in PLAN_FIELDS)}


def _bootstrap_feedback(state: dict[str, Any], result: dict[str, Any]
                        ) -> tuple[int, set[str], dict[str, int]]:
    """Score available global feedback without scanning a large trace again.

    The current graph receipt provides total graph edge/node counts, not
    global coverage IDs. A future compact coverage summary can contribute
    exact site novelty; an absent summary contributes zero rather than
    mislabeling target-closure coverage as global coverage.
    """
    sites = _bootstrap_sites(result)
    seen_sites = set(state.get("bootstrap_seen_door_sites", []))
    new_sites = sites - seen_sites
    state["bootstrap_seen_door_sites"] = sorted(seen_sites | sites)
    graph = result.get("graphchecker_feedback", {})
    coverage = graph.get("globalCoverageSiteIds", [])
    if not isinstance(coverage, list) or any(not isinstance(site, str)
                                             for site in coverage):
        coverage = []
    seen_coverage = set(state.get("bootstrap_seen_coverage_sites", []))
    new_coverage = set(coverage) - seen_coverage
    state["bootstrap_seen_coverage_sites"] = sorted(seen_coverage | set(coverage))
    counts = {}
    for name in ("edges", "nodes"):
        value = graph.get(name, 0)
        value = value if isinstance(value, int) and not isinstance(value, bool) else 0
        previous = int(state.get("bootstrap_max_graph_" + name, 0))
        counts[name] = max(0, value - previous)
        state["bootstrap_max_graph_" + name] = max(previous, value)
    novelty = min(60, 8 * len(new_sites) + 2 * len(new_coverage) +
                  2 * counts["edges"] + counts["nodes"])
    return novelty, new_sites, {"new_io_sites": len(new_sites),
                                "new_coverage_sites": len(new_coverage),
                                "graph_edge_count_gain": counts["edges"],
                                "graph_node_count_gain": counts["nodes"]}


def _enqueue(state: dict[str, Any], result: dict[str, Any],
             prefix: list[dict[str, Any]], *, bootstrap: bool = False,
             bootstrap_novelty: int = 0,
             bootstrap_new_sites: set[str] | None = None,
             target_novelty: int | None = None,
             producer_frontier_continuation: bool = False,
             max_added: int | None = None) -> int:
    evidence = result.get("evidence", {})
    if bootstrap and (state.get("scheduler_version", 1) < 4 or
                      evidence.get("target_reached") or
                      (prefix and not evidence.get("strict_injection"))):
        raise ValueError("target-absent bootstrap requires a strict target-absent v4 seed")
    last_seq = evidence.get("last_fault_seq") or 0
    if len(prefix) >= state["budget"]["max_faults_per_trial"]:
        return 0
    if bootstrap and len(prefix) >= state["bootstrap_limits"]["max_faults_per_trial"]:
        return 0
    seen = set(state["seen_plan_keys"])
    added = 0
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for door in evidence.get("eligible_doors", []):
        tier = door.get("tier")
        if producer_frontier_continuation and tier != "observed_closure":
            continue
        if bootstrap and tier not in ("static_may_observed",
                                      "selected_scope_observed"):
            # A target-absent run has no observed target closure. Static MAY
            # is a selection bound, never a runtime causal edge.
            continue
        if state.get("scheduler_version", 1) < 2 and tier == "selected_scope_observed":
            tier = "outside_closure"
            door = {**door, "tier": tier}
        if (tier not in TIER_WEIGHT or tier == "after_target" or
                door.get("seq", 0) <= last_seq or
                not all(door.get(key) for key in PLAN_FIELDS)):
            continue
        groups.setdefault((door["siteId"], door["node"], tier), []).append(door)
    sampled: list[dict[str, Any]] = []
    for group in groups.values():
        group.sort(key=lambda door: door["seq"])
        # Five quantile points cover early and late repeated I/O calls without
        # filling the queue with every heartbeat or polling occurrence.
        n = len(group)
        sampled.extend(group[(n - 1) * bucket // 4] for bucket in range(5))
    by_tier = {tier: deque(sorted((door for door in sampled if door["tier"] == tier),
                                  key=lambda door: door["seq"]))
               for tier in ("observed_closure", "static_may_observed",
                            "selected_scope_observed", "outside_closure")}
    # Reserve queue capacity for conservative static and exploratory sites.
    # Their priority during execution remains lower than exact closure sites.
    ordered = []
    schedule = ("observed_closure", "observed_closure", "observed_closure",
                "static_may_observed", "selected_scope_observed",
                "outside_closure")
    while any(by_tier.values()) and len(ordered) < MAX_QUEUE:
        for tier in schedule:
            if by_tier[tier]:
                ordered.append(by_tier[tier].popleft())
    parent_novelty = (target_novelty if target_novelty is not None else
                      _novelty(result) if state.get("scheduler_version", 1) < 5
                      else 0)
    for door in ordered:
        if max_added is not None and added >= max_added:
            break
        if len(state["queue"]) >= MAX_QUEUE:
            break
        tier = door["tier"]
        fault = {key: door[key] for key in PLAN_FIELDS}
        if door.get(REPLAY_FIELD):
            fault[REPLAY_FIELD] = door[REPLAY_FIELD]
        faults = [*prefix, fault]
        key = _plan_key(faults)
        if key in seen:
            continue
        seen.add(key)
        item = {"key": key, "faults": faults, "tier": tier,
                "static_producer_frontier": bool(door.get(
                    "static_producer_frontier", False)),
                "producer_frontier_continuation": producer_frontier_continuation,
                "novelty": (min(60, bootstrap_novelty +
                                (15 if door["siteId"] in (
                                    bootstrap_new_sites or set()) else 0))
                            if bootstrap else parent_novelty),
                "enqueued_at": state["completed_fault_trials"]}
        if bootstrap:
            item["bootstrap_seed"] = True
        if state.get("scheduler_version", 1) >= 3:
            item["parent_target_retained"] = bool(
                not bootstrap and prefix and
                evidence.get("injection_specific_target_reached"))
            item["parent_graph_delta"] = (
                parent_novelty if prefix and not bootstrap else 0)
        state["queue"].append(item)
        added += 1
    state["seen_plan_keys"] = sorted(seen)
    return added


def _new_state(config: dict[str, Any], budget: dict[str, int]) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "case_id": config["case_id"],
            "config_sha256": config["config_sha256"], "budget": budget,
            "configured_check_sites": _configured_check_sites(config["target"])
            if isinstance(config.get("target"), dict) else [],
            "scheduler_version": SCHEDULER_VERSION,
            "bootstrap_policy_version": BOOTSTRAP_POLICY_VERSION,
            "bootstrap_limits": {
                "fault_trials": min(BOOTSTRAP_MAX_TRIALS, budget["fault_trials"]),
                "max_faults_per_trial": min(BOOTSTRAP_MAX_FAULTS,
                                            budget["max_faults_per_trial"])},
            "healthy_target_reached": None,
            "bootstrap_seed_doors": 0,
            "bootstrap_fault_trials": 0,
            "bootstrap_seen_door_sites": [],
            "bootstrap_seen_coverage_sites": [],
            "bootstrap_max_graph_edges": 0,
            "bootstrap_max_graph_nodes": 0,
            "closure_novelty_policy_version": CLOSURE_NOVELTY_POLICY_VERSION,
            "seen_target_closure_node_families": [],
            "seen_target_closure_edge_families": [],
            "seen_target_closure_coverage_sites": [],
            "target_discovered_trial": None,
            "last_fault_site_attempts": {}, "last_fault_site_strict": {},
            "last_fault_actor_site_attempts": {},
            "site_target_retention": {},
            "producer_frontier_continuations_enqueued": 0,
            "target_site_rows": config.get("target_site_rows", []),
            "status": "running", "terminal": False,
            "started_at": _now(), "updated_at": _now(),
            "completed_fault_trials": 0, "trial_elapsed_seconds": 0.0,
            "healthy": None, "trials": [], "queue": [], "seen_plan_keys": [],
            "unmatched_retries": {},
            "active": None, "next_trial_index": 1}


def _trial_record(name: str, result: dict[str, Any]) -> dict[str, Any]:
    evidence = result.get("evidence", {})
    return {"name": name, "status": result["status"],
            "result": f"trials/{name}/result.json",
            "elapsed_seconds": result["elapsed_seconds"],
            "faults": result["fault_plan"],
            "strict_injection": evidence.get("strict_injection", False),
            "post_fault_target_reached": evidence.get("post_fault_target_reached", False),
            "injection_specific_target_reached": evidence.get(
                "injection_specific_target_reached", False),
            "target_exception_triggered": result["target_exception_triggered"],
            "target_exception_candidate": result["target_exception_candidate"],
            "observed_check_sites": evidence.get("observed_check_sites", []),
            "junit_passed": result["junit_passed"]}


def _accept_result(state: dict[str, Any], name: str,
                   result: dict[str, Any]) -> None:
    active = state["active"]
    if active is None or active["name"] != name:
        raise ValueError("checkpoint active trial disagrees with result")
    record = _trial_record(name, result)
    target_novelty, closure_feedback = _result_novelty(state, result)
    if active["index"] == 0 and state.get("scheduler_version", 1) >= 5:
        # The healthy graph seeds the campaign's seen sets, not a reward.
        target_novelty = 0
    if state.get("scheduler_version", 1) >= 5:
        record["target_closure_novelty"] = target_novelty
        record["target_closure_feedback"] = closure_feedback
        for field in ("raw_target_check_rows", "raw_target_throw_rows",
                      "unattributed_target_check_rows", "unattributed_target_throw_rows",
                      "attributed_target_check_rows", "attributed_target_throw_rows"):
            if field in result.get("evidence", {}):
                record[field] = result["evidence"][field]
    record["unmatched_retry"] = active.get("unmatched_retry", 0)
    if active["index"] > 0:
        record["selection_tier"] = active.get("selection_tier")
        record["selection_score"] = active.get("selection_score")
        record["producer_frontier_continuation"] = active.get(
            "producer_frontier_continuation", False)
        record["parent_target_retained"] = active.get("parent_target_retained", False)
        record["parent_graph_delta"] = active.get("parent_graph_delta", 0)
        if state.get("scheduler_version", 1) >= 4:
            record["bootstrap_seed"] = active.get("bootstrap_seed", False)
    state["trial_elapsed_seconds"] = round(
        state["trial_elapsed_seconds"] + result["elapsed_seconds"], 3)
    if active["index"] == 0:
        state["healthy"] = record
        if state.get("scheduler_version", 1) >= 4:
            state["healthy_target_reached"] = bool(result.get(
                "evidence", {}).get("target_reached"))
        if result["status"] == "invalid_graphchecker_trace":
            state["status"] = "blocked_healthy_trace"
        elif not result["junit_passed"]:
            state["status"] = "blocked_healthy_junit"
        elif not result.get("evidence", {}).get("target_reached"):
            if (state.get("scheduler_version", 1) >= 5 and
                    _healthy_target_attribution_missing(result["evidence"])):
                state["status"] = "blocked_healthy_target_attribution"
            elif state.get("scheduler_version", 1) >= 4:
                _bootstrap_feedback(state, result)
                state["bootstrap_seed_doors"] = _enqueue(
                    state, result, [], bootstrap=True)
                if not state["queue"]:
                    state["status"] = "no_observed_fault_door"
            else:
                state["status"] = "no_healthy_target"
        else:
            _enqueue(state, result, [], target_novelty=target_novelty)
            if not state["queue"]:
                state["status"] = "no_observed_fault_door"
    else:
        state["trials"].append(record)
        state["completed_fault_trials"] += 1
        evidence = result.get("evidence", {})
        if state.get("scheduler_version", 1) >= 4:
            if active.get("bootstrap_seed"):
                state["bootstrap_fault_trials"] += 1
            if (state.get("healthy_target_reached") is False and
                    state.get("target_discovered_trial") is None and
                    evidence.get("strict_injection") and
                    evidence.get("injection_specific_target_reached") and
                    evidence.get("target_reached")):
                state["target_discovered_trial"] = name
            if (active.get("bootstrap_seed") and
                    evidence.get("strict_injection") and
                    not evidence.get("target_reached") and
                    state["bootstrap_fault_trials"] < state[
                        "bootstrap_limits"]["fault_trials"]):
                novelty, new_sites, feedback = _bootstrap_feedback(state, result)
                record["bootstrap_feedback"] = feedback
                _enqueue(state, result, active["faults"], bootstrap=True,
                         bootstrap_novelty=novelty,
                         bootstrap_new_sites=new_sites)
            if (state.get("healthy_target_reached") is False and
                    state.get("target_discovered_trial") is None and
                    state["bootstrap_fault_trials"] >= state[
                        "bootstrap_limits"]["fault_trials"]):
                state["status"] = "complete_bootstrap_budget"
                state["queue"].clear()
        if (state.get("scheduler_version", 1) >= 2 and
                evidence.get("strict_injection") and active["faults"]):
            site = active["faults"][-1]["siteId"]
            counts = state.setdefault("last_fault_site_strict", {})
            counts[site] = int(counts.get(site, 0)) + 1
            if state.get("scheduler_version", 1) >= 3:
                actor_site = _actor_site_key(active["faults"][-1])
                history = state.setdefault("site_target_retention", {}).setdefault(
                    actor_site, {"preserved": 0, "lost": 0, "productive": 0})
                if evidence.get("injection_specific_target_reached"):
                    history["preserved"] += 1
                    if target_novelty > 0:
                        history["productive"] += 1
                else:
                    history["lost"] += 1
        if (state["status"] == "running" and result["status"] == "unmatched"
                and active["faults"]):
            # The planned I/O may disappear under scheduling nondeterminism.
            # Give this exact plan at most two more chances; each attempt still
            # consumes the trial/time budget and is recorded independently.
            key = _plan_key(active["faults"])
            retries = state.setdefault("unmatched_retries", {})
            count = int(retries.get(key, 0))
            if count < MAX_UNMATCHED_RETRIES and len(state["queue"]) < MAX_QUEUE:
                retries[key] = count + 1
                state["queue"].append({
                    "key": key, "faults": active["faults"],
                    "tier": active.get("selection_tier", "outside_closure"),
                    "static_producer_frontier": active.get(
                        "static_producer_frontier", False),
                    "producer_frontier_continuation": active.get(
                        "producer_frontier_continuation", False),
                    "novelty": -10 * (count + 1),
                    "enqueued_at": state["completed_fault_trials"],
                    "bootstrap_seed": active.get("bootstrap_seed", False),
                    "unmatched_retry": count + 1})
        if evidence.get("strict_injection") and evidence.get(
                "injection_specific_target_reached"):
            _enqueue(state, result, active["faults"],
                     target_novelty=target_novelty)
        elif (len(active["faults"]) == 1 and
              active.get("static_producer_frontier") and
              evidence.get("strict_injection") and
              evidence.get("post_fault_target_reached") and
              evidence.get("target_reached")):
            remaining = MAX_PRODUCER_FRONTIER_CONTINUATIONS - int(state.get(
                "producer_frontier_continuations_enqueued", 0))
            if remaining > 0:
                added = _enqueue(state, result, active["faults"],
                                 target_novelty=0,
                                 producer_frontier_continuation=True,
                                 max_added=remaining)
                state["producer_frontier_continuations_enqueued"] = (
                    MAX_PRODUCER_FRONTIER_CONTINUATIONS - remaining + added)
    state["active"] = None
    state["updated_at"] = _now()
    state["terminal"] = state["status"] != "running"


def _resume_active(state: dict[str, Any], root: Path,
                   config: dict[str, Any], prepared: Path,
                   additional_healthy_seeds: list[Path] | None = None) -> None:
    active = state.get("active")
    if active is None:
        return
    name = active["name"]
    trial = root / "trials" / name
    result_file = trial / "result.json"
    if result_file.is_file():
        result = _json(result_file)
        if result.get("case_id") != state["case_id"] or result.get("fault_plan") != active["faults"]:
            raise ValueError("completed active trial does not match checkpoint")
        verify_trial_artifacts(trial, result)
        _accept_result(state, name, result)
        _write_json(root / "checkpoint.json", state)
        return
    if _live_process(trial):
        raise RuntimeError(f"trial JVM is still running; refusing duplicate: {trial}")
    if trial.exists():
        archive = root / "interrupted"
        archive.mkdir(exist_ok=True)
        suffix = 1
        while (archive / f"{name}-attempt{suffix}").exists():
            suffix += 1
        trial.rename(archive / f"{name}-attempt{suffix}")
        active["interrupted_attempts"] = suffix
    prior = root / "trials" / "r0000" / "graphchecker-trace.jsonl.gz"
    if active["index"] > 0 and not prior.is_file():
        # Allow trials from the initial uncompressed pilot to resume without
        # replaying their completed healthy seed.
        legacy = prior.with_suffix("")
        if not legacy.is_file():
            raise FileNotFoundError(f"healthy GraphChecker trace missing: {prior}")
        prior = legacy
    result = run_trial(config, prepared, trial, {"faults": active["faults"]},
                       prior if active["index"] > 0 else None,
                       additional_healthy_seeds if active["index"] > 0 else None)
    _accept_result(state, name, result)
    _write_json(root / "checkpoint.json", state)


def _verify_recorded_evidence(state: dict[str, Any], root: Path) -> None:
    """Resume only when every recorded terminal trial still has its evidence."""
    for record in ([state["healthy"]] if state.get("healthy") else []) + state.get("trials", []):
        path = root / record["result"]
        result = _json(path)
        if result.get("case_id") != state["case_id"] or result.get("fault_plan") != record["faults"]:
            raise ValueError(f"checkpoint trial receipt changed: {path}")
        verify_trial_artifacts(path.parent, result)


def _finish(state: dict[str, Any], root: Path) -> dict[str, Any]:
    if state["status"] == "running":
        if state["completed_fault_trials"] >= state["budget"]["fault_trials"]:
            state["status"] = "complete_trial_budget"
        elif state["trial_elapsed_seconds"] >= state["budget"]["seconds"]:
            state["status"] = "complete_time_budget"
        elif not state["queue"]:
            state["status"] = "complete_queue"
    state["updated_at"] = _now()
    state["terminal"] = state["status"] != "running"
    _write_json(root / "checkpoint.json", state)
    if state["status"] != "running":
        trials = state["trials"]
        records = ([state["healthy"]] if state.get("healthy") else []) + trials
        observed_checks = sorted({site for row in records
                                  for site in row.get("observed_check_sites", [])})
        configured_checks = state.get("configured_check_sites", [])
        summary = {"schema_version": SCHEMA, "case_id": state["case_id"],
                   "status": state["status"], "terminal": True,
                   "config_sha256": state["config_sha256"],
                   "target_site_rows": state.get("target_site_rows", []),
                   "configured_check_sites": configured_checks,
                   "observed_check_sites": observed_checks,
                   "missing_check_sites": sorted(set(configured_checks) - set(observed_checks)),
                   "budget": state["budget"],
                   "scheduler_version": state.get("scheduler_version", 1),
                   "bootstrap_policy_version": state.get("bootstrap_policy_version"),
                   "bootstrap_limits": state.get("bootstrap_limits"),
                   "healthy_target_reached": state.get("healthy_target_reached"),
                   "bootstrap_seed_doors": state.get("bootstrap_seed_doors", 0),
                   "bootstrap_fault_trials": state.get("bootstrap_fault_trials", 0),
                   "target_discovered_trial": state.get("target_discovered_trial"),
                   "last_fault_site_attempts": state.get("last_fault_site_attempts", {}),
                   "last_fault_site_strict": state.get("last_fault_site_strict", {}),
                   "last_fault_actor_site_attempts": state.get(
                       "last_fault_actor_site_attempts", {}),
                   "site_target_retention": state.get("site_target_retention", {}),
            "producer_frontier_continuations_enqueued": state.get(
                "producer_frontier_continuations_enqueued", 0),
                   "completed_fault_trials": state["completed_fault_trials"],
                   "trial_elapsed_seconds": state["trial_elapsed_seconds"],
                   "healthy": state["healthy"],
                   "strict_trials": sum(row["strict_injection"] for row in trials),
                   "unmatched_trials": sum(row["status"] == "unmatched"
                                           for row in trials),
                   "post_fault_target_trials": sum(row["post_fault_target_reached"]
                                                   for row in trials),
                   "injection_specific_target_trials": sum(
                       row.get("injection_specific_target_reached", False)
                       for row in trials),
                   "target_exception_triggered_trials": sum(
                       row["target_exception_triggered"] for row in trials),
                   "differential_candidates": sum(
                       row["target_exception_candidate"] for row in trials),
                   "first_target_exception_trial": next(
                       (row["name"] for row in trials
                        if row["target_exception_triggered"]), None),
                   "updated_at": state["updated_at"]}
        if state.get("scheduler_version", 1) >= 5:
            summary["closure_novelty_policy_version"] = state[
                "closure_novelty_policy_version"]
            summary["target_closure_unique_counts"] = {
                "node_families": len(state["seen_target_closure_node_families"]),
                "edge_families": len(state["seen_target_closure_edge_families"]),
                "coverage_sites": len(state["seen_target_closure_coverage_sites"])}
        _write_json(root / "summary.json", summary)
    return state


def run_campaign(config_path: Path, root: Path,
                 stop_after_fault_trials: int | None = None,
                 additional_healthy_seeds: list[Path] | None = None
                 ) -> dict[str, Any]:
    config = load_config(config_path)
    budget = _budget(config_path)
    if (stop_after_fault_trials is not None and
            (not isinstance(stop_after_fault_trials, int) or
             isinstance(stop_after_fault_trials, bool) or
             stop_after_fault_trials <= 0 or
             stop_after_fault_trials > budget["fault_trials"])):
        raise ValueError("stop_after_fault_trials must be within the immutable budget")
    root = root.resolve()
    healthy_seed_paths = [path.resolve() for path in additional_healthy_seeds or []]
    if len(set(healthy_seed_paths)) != len(healthy_seed_paths):
        raise ValueError("duplicate additional healthy seed trace")
    for path in healthy_seed_paths:
        _prior_trace_metadata(path, config["target"], config["case_id"])
        if _prior_trace_profiles(path, config["target"]) is None:
            raise ValueError("additional healthy seed lacks structural target profiles")
    healthy_seed_pins = [{"path": str(path), "archive_sha256": _sha256(path)}
                         for path in healthy_seed_paths]
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".campaign.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as failure:
            raise RuntimeError(f"campaign already owned by another worker: {root}") from failure
        checkpoint = root / "checkpoint.json"
        if checkpoint.is_file():
            state = _json(checkpoint)
            if (state.get("schema_version") != SCHEMA or
                    state.get("case_id") != config["case_id"] or
                    state.get("config_sha256") != config["config_sha256"] or
                    state.get("budget") != budget):
                raise ValueError("campaign checkpoint does not match immutable config")
            if state.get("additional_healthy_seed_pins", []) != healthy_seed_pins:
                raise ValueError("campaign additional healthy seeds changed")
            if state.get("scheduler_version", 1) >= 4 and (
                    state.get("bootstrap_policy_version") != BOOTSTRAP_POLICY_VERSION or
                    state.get("bootstrap_limits") != {
                        "fault_trials": min(BOOTSTRAP_MAX_TRIALS,
                                            budget["fault_trials"]),
                        "max_faults_per_trial": min(BOOTSTRAP_MAX_FAULTS,
                                                    budget["max_faults_per_trial"])}):
                raise ValueError("campaign bootstrap checkpoint policy changed")
            if state.get("scheduler_version", 1) >= 5:
                if state.get("closure_novelty_policy_version") != (
                        CLOSURE_NOVELTY_POLICY_VERSION):
                    raise ValueError("campaign target closure novelty policy changed")
                for _, field, _ in _CLOSURE_FAMILY_FIELDS:
                    values = state.get(field)
                    if (not isinstance(values, list) or
                            any(not isinstance(value, str) or not value
                                for value in values) or
                            values != sorted(set(values))):
                        raise ValueError(f"invalid target closure novelty checkpoint: {field}")
            _verify_recorded_evidence(state, root)
        else:
            state = _new_state(config, budget)
            state["additional_healthy_seed_pins"] = healthy_seed_pins
            _write_json(checkpoint, state)
        if state["status"] != "running":
            return _finish(state, root)
        prepared = root / "prepared"
        if not (prepared / "weave-receipt.json").is_file():
            if prepared.exists():
                raise ValueError("incomplete weave preparation; preserve it and use a new case root")
            prepare(config, prepared)
        (root / "trials").mkdir(exist_ok=True)
        if state["healthy"] is None and state["active"] is None:
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            _write_json(checkpoint, state)
        _resume_active(state, root, config, prepared, healthy_seed_paths)
        while state["status"] == "running":
            if (state["completed_fault_trials"] >= budget["fault_trials"] or
                    state["trial_elapsed_seconds"] >= budget["seconds"] or
                    not state["queue"]):
                break
            if (stop_after_fault_trials is not None and
                    state["completed_fault_trials"] >= stop_after_fault_trials):
                # A bounded wave pauses only between trials. The queue,
                # budget, config hash, and nonterminal checkpoint remain the
                # exact successor state for a later invocation.
                state["updated_at"] = _now()
                state["terminal"] = False
                _write_json(checkpoint, state)
                return state
            selected = _pick(state["queue"], state["completed_fault_trials"], state)
            selected_score = (
                _retention_score(selected, state["completed_fault_trials"], state)
                if state.get("scheduler_version", 1) >= 3 else
                _score(selected, state["completed_fault_trials"]))
            index = state["next_trial_index"]
            state["next_trial_index"] += 1
            if state.get("scheduler_version", 1) >= 2:
                site = selected["faults"][-1]["siteId"]
                counts = state.setdefault("last_fault_site_attempts", {})
                counts[site] = int(counts.get(site, 0)) + 1
                if state.get("scheduler_version", 1) >= 3:
                    actor_site = _actor_site_key(selected["faults"][-1])
                    actor_counts = state.setdefault("last_fault_actor_site_attempts", {})
                    actor_counts[actor_site] = int(actor_counts.get(actor_site, 0)) + 1
            state["active"] = {"index": index, "name": f"r{index:04d}",
                               "faults": selected["faults"],
                               "selection_tier": selected["tier"],
                               "selection_score": selected_score,
                               "static_producer_frontier": selected.get(
                                   "static_producer_frontier", False),
                               "producer_frontier_continuation": selected.get(
                                   "producer_frontier_continuation", False),
                               "parent_target_retained": selected.get(
                                   "parent_target_retained", False),
                               "parent_graph_delta": selected.get("parent_graph_delta", 0),
                               "bootstrap_seed": selected.get("bootstrap_seed", False),
                               "unmatched_retry": selected.get("unmatched_retry", 0)}
            _write_json(checkpoint, state)
            _resume_active(state, root, config, prepared, healthy_seed_paths)
        return _finish(state, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stop-after-fault-trials", type=int,
                        help="pause after this cumulative fault-trial count; "
                             "preserve the nonterminal checkpoint for resume")
    parser.add_argument("--additional-healthy-seed-trace", action="append",
                        type=Path, default=[],
                        help="independent unchanged no-fault trace; its archive "
                             "digest is pinned in the campaign checkpoint")
    args = parser.parse_args(argv)
    state = run_campaign(args.config, args.out, args.stop_after_fault_trials,
                         args.additional_healthy_seed_trace)
    paused = (state["status"] == "running" and args.stop_after_fault_trials is not None
              and state["completed_fault_trials"] >= args.stop_after_fault_trials)
    print(json.dumps({"case_id": state["case_id"],
                      "status": "paused_wave" if paused else state["status"],
                      "completed_fault_trials": state["completed_fault_trials"],
                      "summary": (str((args.out / "summary.json").resolve())
                                  if (args.out / "summary.json").is_file() else None)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
