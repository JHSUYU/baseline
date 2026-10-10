"""Deterministic, bounded mutation of observed fault sequences."""

from __future__ import annotations

import re
from typing import Any

from .feedback import digest


def fault_signature(fault: dict[str, Any]) -> str:
    return digest({"point": fault["point"], "fault_type": fault["fault_type"],
                   "exception_class": fault.get("exception_class")})


def sequence_signature(sequence: list[dict[str, Any]]) -> str:
    return digest([fault_signature(f) for f in sequence])


def _allowed_types(door: dict[str, Any], config: dict[str, Any]) -> list[str]:
    types = door.get("fault_types") or door.get("fault_type") or config.get("fault_types", [])
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, list):
        return []
    allowed = set(config.get("fault_types", types))
    return [kind for kind in types if isinstance(kind, str) and kind in allowed]


def _static_match(site: str, config: dict[str, Any]) -> bool:
    if site in config.get("static_fault_sites", []):
        return True
    match = re.match(r"^(.+)#([^(@]+)\([^)]*\)[^@]*@([0-9]+):door:[0-9]+$", site)
    if not match:
        return False
    class_name, method, line_text = match.groups()
    line = int(line_text)
    for row in config.get("static_fault_locations", []):
        if row.get("class") != class_name or row.get("line") != line:
            continue
        static_method = str(row.get("method", ""))
        if static_method == method or re.search(r"\b" + re.escape(method) + r"\(", static_method):
            return True
    return False


def _replay_point(door: dict[str, Any]) -> dict[str, Any] | None:
    """Use a stable cross-run identity without weakening within-run graph IDs."""
    source = door.get("point")
    if not isinstance(source, dict):
        return None
    ordinal = source.get("door_ordinal")
    if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
        keys = ("site", "node", "epoch", "door_ordinal")
    else:
        keys = ("site", "node", "epoch", "occurrence", "hit")
    if any(key not in source or source[key] is None for key in keys):
        return None
    return {key: source[key] for key in keys}


def mutate(parent: list[dict[str, Any]], feedback: dict[str, Any],
           config: dict[str, Any], *, bootstrap: bool = False) -> list[dict[str, Any]]:
    budget = config["budget"]
    bootstrap_config = config.get("target_absent_bootstrap", {}) if bootstrap else {}
    max_faults = min(int(budget["max_faults_per_trial"]),
                     int(bootstrap_config.get("max_faults_per_trial",
                                              budget["max_faults_per_trial"])))
    if len(parent) >= max_faults:
        return []
    if parent and not feedback["all_faults_effective"]:
        return []
    if parent and not bootstrap and not feedback["target_reached"]:
        return []
    if bootstrap:
        # An absent target has no observed backward closure. Exact site names
        # are an explicit exploration policy, not a causal claim.
        allowed = set(bootstrap_config["door_sites"])
        last_fault_seq = int(feedback.get("last_fault_seq", -1))
        doors = [door for door in feedback["doors"]
                 if door.get("site") in allowed and
                 int(door.get("event_seq", -1)) > last_fault_seq]
        doors.sort(key=lambda door: (bootstrap_config["door_sites"].index(door["site"]),
                                     int(door.get("event_seq", -1)),
                                     digest(door.get("point"))))
        doors = doors[:int(bootstrap_config["max_doors_per_trial"])]
        return _make_candidates(parent, doors, config, "bootstrap_io", feedback)
    validated_sites = {row["site"] for row in config.get("validated_recovery_sites", [])}
    validated = [d for d in feedback["doors"] if d.get("site") in validated_sites]
    dynamic = [d for d in feedback["doors"] if d.get("in_closure")
               and d not in validated]
    # Static may-influence sites can be tested even when the current exact
    # dynamic closure has no writer or producer on that path.
    static = [d for d in feedback["doors"] if _static_match(str(d.get("site")), config)
              and d not in validated and d not in dynamic]
    include_outside = bool(config.get("explore_outside_closure", True))
    outside = ([d for d in feedback["doors"]
                if d not in validated and d not in dynamic and d not in static]
               if include_outside else [])
    return _make_candidates(parent, validated + dynamic + static + outside,
                            config, None, feedback,
                            validated=validated, dynamic=dynamic, static=static)


def _make_candidates(parent: list[dict[str, Any]], doors: list[dict[str, Any]],
                     config: dict[str, Any], reason: str | None,
                     feedback: dict[str, Any], *,
                     validated: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
                     dynamic: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
                     static: tuple[dict[str, Any], ...] | list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    seen = {sequence_signature(parent)}
    result = []
    last_fault_seq = int(feedback.get("last_fault_seq", -1))
    for door in doors:
        if int(door.get("event_seq", -1)) <= last_fault_seq:
            continue
        point = _replay_point(door)
        if point is None:
            continue
        for kind in _allowed_types(door, config):
            exception_class = door.get("exception_class") or config.get("exception_class")
            if kind == "EXCEPTION" and not exception_class:
                continue
            fault = {"fault_id": "f" + digest([len(parent), point, kind]),
                     "point": point, "fault_type": kind}
            if exception_class:
                fault["exception_class"] = exception_class
            sequence = parent + [fault]
            sig = sequence_signature(sequence)
            if sig not in seen:
                selection_reason = reason or ("validated_recovery" if door in validated else
                                              "dynamic_closure" if door in dynamic else
                                              "static_candidate" if door in static else
                                              "bounded_exploration")
                result.append({"faults": sequence,
                               "selection_reason": selection_reason,
                               "signature": sig})
                seen.add(sig)
    return result


def score(candidate: dict[str, Any], parent_feedback: dict[str, Any],
          tried_sites: set[str], waiting_rounds: int) -> float:
    reason = candidate.get("selection_reason")
    last = candidate["faults"][-1]
    site = str(last["point"]["site"])
    novelty = parent_feedback.get("novelty", {})
    location = (96.0 if reason == "validated_recovery" else
                12.0 if reason == "dynamic_closure" else
                6.0 if reason == "static_candidate" else 1.0)
    coverage = (2.0 * novelty.get("closure_coverage", 0) +
                0.25 * novelty.get("coverage", 0) +
                3.0 * novelty.get("closure_edges", 0))
    return (location + (4.0 if site not in tried_sites else 0.0) +
            min(coverage, 30.0) + min(waiting_rounds, 30) * 0.1 +
            min(len(candidate["faults"]), 6) * 0.3)


def pick_next(queue: list[dict[str, Any]], next_trial: int,
              fault_trials_completed: int, config: dict[str, Any]) -> dict[str, Any]:
    """Prioritize validated doors and reserve periodic deeper exploration."""
    queue.sort(key=lambda item: (-(item["priority"] +
                                  0.05 * (next_trial - item["queued_at"])),
                                 item["queued_at"], item["signature"]))
    if queue[0].get("selection_reason") == "candidate_replay":
        return queue.pop(0)
    if (config.get("validated_recovery_sites") and
            (fault_trials_completed + 1) %
            config.get("validated_recovery_exploration_interval", 5) == 0):
        for index, item in enumerate(queue):
            if item.get("selection_reason") != "validated_recovery":
                return queue.pop(index)
    breadth_interval = config.get("single_fault_breadth_interval")
    # Healthy-run coverage can give every initial single-fault candidate a
    # higher inherited score than any later mutation. Without a depth slot,
    # a bounded campaign may never exercise the multi-fault plans it generated.
    depth_interval = config.get("multi_fault_exploration_interval",
                                4 if breadth_interval is None else None)
    if (depth_interval and fault_trials_completed > 0 and
            (fault_trials_completed + 1) % depth_interval == 0):
        for index, item in enumerate(queue):
            if len(item["faults"]) > 1:
                return queue.pop(index)
    if (breadth_interval and
            (fault_trials_completed + 1) % breadth_interval != 0):
        for index, item in enumerate(queue):
            if len(item["faults"]) == 1:
                return queue.pop(index)
    return queue.pop(0)
