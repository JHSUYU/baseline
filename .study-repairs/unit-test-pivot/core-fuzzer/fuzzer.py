#!/usr/bin/env python3
"""Resumable, target-guided exception trials over one original JUnit test.

GraphChecker owns static slicing, the runtime region plan, weaving, and the
JUnit invocation.  This driver consumes those artifacts and reruns the same
test with exact GraphChecker fault selectors.  It never edits the test or the
system under test.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

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
                    raise ValueError(f"{path}:{number}: {exc}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{number}: expected JSON object")
                yield row


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def fingerprint(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def read_closure(path: Path, target_method: str,
                 target_occurrence: str | None = None,
                 target_region_id: str | None = None,
                 allowed_target_request_apis: set[str] | None = None,
                 allowed_target_occurrences: set[str] | None = None) -> dict[str, Any]:
    """Read only target-rooted GraphChecker demand-walk membership evidence."""
    plans = list(rows(path))
    catalog = [r for r in plans if r.get("kind") == "CONCOLIC_RUNTIME_MODEL_CATALOG"]
    selected = [r for r in plans if r.get("kind") == "CONCOLIC_REGION_PLAN"]
    targets = [r for r in selected if r.get("targetMethod") == target_method
               and (target_occurrence is None or
                    r.get("occurrenceId") == target_occurrence)
               and (allowed_target_request_apis is None or
                    r.get("requestApi") in allowed_target_request_apis)
               and (allowed_target_occurrences is None or
                    r.get("occurrenceId") in allowed_target_occurrences)
               and any(g.get("kind") == "TARGET_REACH_CLOSURE"
                       for g in r.get("closureGoals", []))]
    gaps = [g for r in catalog for g in r.get("gaps", [])]
    if not targets:
        raise ValueError(f"no target region for {target_method} "
                         f"occurrence={target_occurrence} "
                         f"requestApi={allowed_target_request_apis} "
                         f"allowedOccurrences={allowed_target_occurrences} in {path}")
    target_addresses = {str(r["occurrenceId"]) for r in targets}
    addresses = set(target_addresses)
    evidence_tiers: dict[str, str] = {}
    evidence_missing: list[str] = []
    if len(catalog) != 1:
        gaps.append({"kind": "RUNTIME_MODEL_CATALOG_COUNT",
                     "cls": "BLOCKING", "subject": path.as_posix(),
                     "actual": len(catalog)})
    if target_region_id and not any(
            row.get("regionId") == target_region_id for row in targets):
        folded = any(target_region_id in row.get("foldedRegionIds", [])
                     for row in targets)
        gaps.append({"kind": ("TARGET_REGION_FOLDED_ONLY" if folded else
                              "TARGET_REGION_RUNTIME_OCCURRENCE_MISSING"),
                     "cls": "BLOCKING", "subject": target_region_id,
                     "detail": "the target region needs its own runtime plan row"})
    for row in selected:
        address = str(row.get("occurrenceId", ""))
        evidence = row.get("targetClosureEvidence")
        if (isinstance(evidence, dict) and
                evidence.get("kind") == "TARGET_CLOSURE_MEMBERSHIP" and
                evidence.get("targetOccurrence") not in target_addresses):
            # A multi-target plan may contain another root's valid closure.
            # Its members say nothing about this target's backward walk.
            continue
        if not isinstance(evidence, dict) or (
                evidence.get("kind") != "TARGET_CLOSURE_MEMBERSHIP" or
                evidence.get("schemaVersion") != 1 or
                evidence.get("occurrence") != address or
                evidence.get("targetOccurrence") not in target_addresses or
                evidence.get("evidenceTier") not in {"EXACT", "CANDIDATE"}):
            evidence_missing.append(address)
            continue
        addresses.add(address)
        evidence_tiers[address] = evidence["evidenceTier"]
    if "" in addresses:
        raise ValueError(f"PLAN has a region without occurrenceId: {path}")
    if evidence_missing:
        gaps.append({"kind": "CLOSURE_MEMBER_EVIDENCE_MISSING",
                     "cls": "BLOCKING", "subject": path.as_posix(),
                     "occurrences": evidence_missing})
    return {
        "addresses": sorted(addresses),
        "target_addresses": sorted(target_addresses),
        "target_request_apis": sorted({r["requestApi"] for r in targets
                                       if isinstance(r.get("requestApi"), str) and
                                       r["requestApi"]}),
        "evidence_tiers": evidence_tiers,
        "evidence_missing": evidence_missing,
        "edges_unavailable": any(
            isinstance(r.get("targetClosureEvidence"), dict) and
            r["targetClosureEvidence"].get("edgeEvidence") == "UNAVAILABLE"
            for r in selected),
        "region_count": len(selected),
        "target_region_id": target_region_id,
        "target_region_explicit": bool(target_region_id and any(
            row.get("regionId") == target_region_id for row in targets)),
        "gaps": gaps,
        "blocking_gaps": [g for g in gaps if g.get("cls") == "BLOCKING"],
    }


def load_target_policy(target: dict[str, Any]) -> None:
    """Use GraphChecker TARGET_SITE's declared fatal arms, never guess them."""
    if target.get("throw_site_id"):
        declared_throw_method = target["throw_site_id"].split("#u", 1)[0]
        if target.get("throw_method") and \
                target["throw_method"] != declared_throw_method:
            raise ValueError("throw_method differs from throw_site_id's method")
        target["throw_method"] = declared_throw_method
    explicit_paths = "fatal_guard_paths" in target or "fatal_guards" in target
    if explicit_paths and target.get("region_id"):
        return
    scope = target.get("scope_map")
    throw_site = target.get("throw_site_id")
    if not scope or not throw_site:
        if explicit_paths:
            return
        raise ValueError("target needs fatal guards or scope_map + throw_site_id")
    matches = [row for row in rows(Path(scope))
               if row.get("role") == "TARGET_SITE" and
               row.get("siteId") == throw_site]
    if len(matches) != 1:
        raise ValueError(f"expected one TARGET_SITE for {throw_site}: {scope}")
    row = matches[0]
    if target.get("region_id") and row.get("regionId") != target["region_id"]:
        raise ValueError("target region_id differs from TARGET_SITE regionId")
    if not target.get("region_id"):
        target["region_id"] = row.get("regionId")
    if explicit_paths:
        return
    guards = row.get("guards", [])
    outcomes = row.get("guardOutcomes", [])
    if len(guards) != len(outcomes) or not guards:
        raise ValueError(f"TARGET_SITE has no complete guard policy: {throw_site}")
    target["fatal_guards"] = [
        {"siteId": site, "outcome": outcome}
        for site, outcome in zip(guards, outcomes)
        if isinstance(outcome, bool)]
    if len(target["fatal_guards"]) != len(guards):
        raise ValueError(f"TARGET_SITE has an undecidable fatal arm: {throw_site}")


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
    marker = event.get("marker", "")
    site = event.get("siteId", "")
    address = event.get("occurrenceAddress", "")
    ordinal = event.get("hitOrdinal", 0)
    if (event.get("event") not in FAULT_EVENTS or
            event.get("schemaVersion") != TRACE_SCHEMA or
            not isinstance(marker, str) or not marker.startswith("FAULT:") or
            not isinstance(site, str) or "#u" not in site or
            not isinstance(address, str) or "/region/" not in address or
            not isinstance(ordinal, int) or ordinal < 1):
        return None
    point = {"marker": marker, "siteId": site,
             "occurrence": address, "hitOrdinal": ordinal}
    if event.get("sourceKey"):
        point["sourceKey"] = event["sourceKey"]
    return point


def trace_feedback(path: Path, closure: dict[str, Any],
                   target: dict[str, Any]) -> dict[str, Any]:
    addresses = set(closure["addresses"])
    target_addresses = set(closure["target_addresses"])
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
    target_site_seen = False
    target_site_after_fault = False
    target_guard_seen = False
    target_guard_after_fault = False
    exceptions: list[dict[str, Any]] = []
    target_calls: set[int] = set()
    call_parents: dict[int, int] = {}
    summary: dict[str, Any] = {}
    throw_event = target.get("throw_event", "METHOD_EXIT_THROW")
    coverage_exclude_sites = set(target.get("coverage_exclude_sites", []))
    events = list(rows(path))
    for event in events:
        kind = event.get("event")
        if kind in FAULT_EVENTS:
            point = point_from_event(event)
            if point and point["occurrence"] in addresses:
                points[fingerprint(point)] = point
                if kind == "FAULT_POINT_OBSERVED":
                    point_events.append({"point": point, "seq": event.get("seq", -1)})
            if kind == "FAULT_MATCHED":
                matched.append(event)
            if kind == "FAULT_APPLIED":
                applied.append(event)
        elif kind == "FAULT_TRIAL_SUMMARY":
            summary = event
        elif kind == "METHOD_ENTER":
            call_id = event.get("callId")
            if isinstance(call_id, int):
                call_parents[call_id] = event.get("parentCallId", 0)
            method = event.get("method")
            if method:
                coverage.add("METHOD:" + method)
            if (method == target["method"] and
                    event.get("occurrenceAddress") in target_addresses and
                    isinstance(call_id, int)):
                target_reached = True
                target_calls.add(call_id)
        elif kind == "BRANCH":
            site = event.get("siteId")
            if site and site not in coverage_exclude_sites:
                coverage.add("BRANCH:" + site + ":" + str(event.get("outcome")))
        elif kind == throw_event:
            if (event.get("method") == target.get("throw_method", target["method"])
                    and (throw_event != "EXPLICIT_THROW" or
                         event.get("siteId") == target.get("explicit_throw_site_id"))):
                exceptions.append(event)
    def in_target_call(call_id: Any) -> bool:
        seen: set[int] = set()
        while isinstance(call_id, int) and call_id > 0 and call_id not in seen:
            if call_id in target_calls:
                return True
            seen.add(call_id)
            call_id = call_parents.get(call_id)
        return False

    applied_seq = max((e.get("seq", -1) for e in applied), default=-1)
    guard_paths = fatal_guard_paths(target)
    # Earlier guards can merely enter the function or an outer branch. The
    # final decision on a throw route is the selected check to retain after
    # the fault; Solr's alternative routes end at different branch sites.
    check_sites = {path[-1]["siteId"] for path in guard_paths}
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

    target_site_seen = any(
        e.get("event") == "BRANCH" and
        e.get("siteId") == target.get("site_id") and
        in_target_call(e.get("callId")) for e in events)
    target_guard_seen = any(
        e.get("event") == "BRANCH" and
        e.get("siteId") in check_sites and
        in_target_call(e.get("callId")) for e in events)
    # A target invocation that happened only before the injected fault cannot
    # validate this trial. The check itself must execute again after the last
    # applied fault, including when its method was entered before that fault.
    target_reached_after_fault = any(
        e.get("event") == "BRANCH" and
        e.get("siteId") in check_sites and
        in_target_call(e.get("callId")) and
        e.get("seq", -1) > applied_seq >= 0 for e in events)
    if target.get("site_id"):
        target_site_after_fault = any(
            e.get("event") == "BRANCH" and
            e.get("siteId") == target["site_id"] and
            in_target_call(e.get("callId")) and
            e.get("seq", -1) > applied_seq >= 0 for e in events)
    expected = target["exception_type"]
    for thrown in exceptions:
        if thrown.get("runtimeType") == expected and \
                in_target_call(thrown.get("callId")):
            target_exception = True
            target_exception_count += 1
            completed_paths = [path_last_seq(path, thrown.get("callId"),
                                             thrown.get("seq", -1))
                               for path in guard_paths]
            fatal_in_call = any(last is not None for last in completed_paths)
            if fatal_in_call:
                target_fatal_exception_count += 1
            if thrown.get("seq", -1) > applied_seq >= 0:
                target_after_fault = True
                if any(last is not None and last > applied_seq
                       for last in completed_paths):
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
        "target_guard_seen": target_guard_seen,
        "target_guard_after_fault": target_guard_after_fault,
        "target_exception": target_exception,
        "target_exception_count": target_exception_count,
        "target_fatal_exception_count": target_fatal_exception_count,
        "target_after_fault": target_after_fault,
        "oracle": oracle,
        "fault_summary": summary,
    }


def sequence_id(sequence: list[dict[str, Any]]) -> str:
    return fingerprint(sequence)


def strict_injection(result: dict[str, Any],
                     sequence: list[dict[str, Any]]) -> bool:
    """Every requested selector must be proved applied, in requested order."""
    expected = [fingerprint(point) for point in sequence]
    observed = [fingerprint(point) for point in result.get("applied_points", [])]
    return (len(expected) == result.get("applied_count") and
            result.get("matched_count", 0) >= len(expected) and
            observed == expected and
            result.get("applied_fault_ids") == expected)


def enqueue(state: dict[str, Any], sequence: list[dict[str, Any]],
            priority: int = 0) -> None:
    name = sequence_id(sequence)
    if name in state["seen_sequences"]:
        return
    state["seen_sequences"].append(name)
    state["queue"].append({"id": name, "sequence": sequence,
                           "priority": priority, "created": time.time()})


def fault_family(point: dict[str, Any]) -> str:
    """Stable I/O identity for scheduling; an occurrence can vary on retry."""
    return fingerprint({key: point.get(key) for key in
                        ("marker", "siteId", "sourceKey")})


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


def choose_next_sequence(state: dict[str, Any]) -> int:
    """Balance new I/O sites with deeper sequences and diversify roots.

    Coverage remains a priority within each diversity tier. This prevents
    one coverage-rich seed from filling a bounded campaign with descendants
    before other observed fault sites have been tested.
    """
    previous = list(completed_sequences(state))
    single_done = sum(len(sequence) == 1 for sequence in previous)
    multi_done = len(previous) - single_done
    preferred_length = 1 if single_done <= multi_done else 2
    eligible = [(index, item) for index, item in enumerate(state["queue"])
                if (len(item["sequence"]) == 1) == (preferred_length == 1)]
    if not eligible:
        eligible = list(enumerate(state["queue"]))
    family_counts: dict[str, int] = {}
    root_counts: dict[str, int] = {}
    for sequence in previous:
        last = fault_family(sequence[-1])
        root = fault_family(sequence[0])
        family_counts[last] = family_counts.get(last, 0) + 1
        root_counts[root] = root_counts.get(root, 0) + 1

    def rank(entry: tuple[int, dict[str, Any]]) -> tuple[Any, ...]:
        index, item = entry
        sequence = item["sequence"]
        root_penalty = (root_counts.get(fault_family(sequence[0]), 0)
                        if len(sequence) > 1 else 0)
        return (root_penalty,
                family_counts.get(fault_family(sequence[-1]), 0),
                -item["priority"], item["created"], index)

    return min(eligible, key=rank)[0]


def write_trial(path: Path, sequence: list[dict[str, Any]],
                target: dict[str, Any], closure: dict[str, Any]) -> None:
    region_ids = {address.split("/region/", 1)[1].split("/ctx:", 1)[0]
                  for address in closure["target_addresses"]}
    trial = {"schemaVersion": 1, "faults": [
        {"faultId": fingerprint(point), **point, "value": True}
        for point in sequence]}
    if target.get("site_id"):
        trial["targetSiteId"] = target["site_id"]
    if len(region_ids) == 1:
        trial["targetRegionId"] = next(iter(region_ids))
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
    plan = Path(seed["closure_plan"])
    seed_command_seconds = None
    if not (trace.is_file() and plan.is_file()):
        command = seed.get("command")
        if not command:
            raise FileNotFoundError(f"seed artifacts missing: {trace}, {plan}")
        context = {"case_dir": str(case_dir), "trace_dir": str(trace.parent)}
        environment = {**os.environ, **config.get("env", {}),
                       "TMPDIR": config["workspaces"]["temp"],
                       "CAUSYNTH_LOCAL_SCRATCH": config["workspaces"]["temp"]}
        result = run_command(command, context, Path(config["cwd"]),
                             environment,
                             case_dir / "seed-command", config["timeout_seconds"])
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
                                       for stage in ("compile", "weave", "runtime",
                                                     "aggregate", "static"))
        else:
            seed_command_seconds = float(seed["elapsed_seconds"])
        if not state.get("seed_timing_recorded"):
            state["active_runtime_seconds"] += seed_command_seconds
            state["seed_runtime_seconds"] += seed_command_seconds
            state["seed_timing_recorded"] = True
            atomic_json(case_dir / "state.json", state)
    closure = read_closure(plan, config["target"]["method"],
                           config["target"].get("occurrence"),
                           config["target"].get("region_id"),
                           allowed_target_request_apis=(
                               {config["target"]["request_api"]}
                               if config["target"].get("request_api") else None))
    feedback = trace_feedback(trace, closure, config["target"])
    state["seed"] = {
        "trace": str(trace), "closure_plan": str(plan),
        "closure": closure, "feedback": feedback,
        "target_reached": feedback["target_reached"], "recorded_at": time.time(),
        "elapsed_seconds": seed_command_seconds,
    }
    state["coverage"] = feedback["coverage"]
    state["closure_members"] = closure["evidence_tiers"]
    if closure["blocking_gaps"]:
        state["status"] = "graph_gap"
        return
    if not feedback["target_reached"] or not feedback["target_guard_seen"]:
        state["status"] = "healthy_target_unreached"
        return
    if not feedback["points"]:
        state["status"] = "no_closure_fault_points"
        return
    for point in feedback["points"]:
        tier = closure["evidence_tiers"].get(point["occurrence"], "CANDIDATE")
        enqueue(state, [point], priority=50 if tier == "EXACT" else 20)


def process_trial(config: dict[str, Any], state: dict[str, Any],
                  case_dir: Path, active: dict[str, Any]) -> None:
    trial_dir = case_dir / "trials" / f"{active['number']:04d}-{active['id']}"
    result_file = trial_dir / "result.json"
    if result_file.is_file():
        result = json.loads(result_file.read_text())
    else:
        trial_dir.mkdir(parents=True, exist_ok=True)
        selector_file = trial_dir / "fault-trial.json"
        write_trial(selector_file, active["sequence"], config["target"],
                    state["seed"]["closure"])
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
        env.update({key: value.format_map(context)
                    for key, value in config["trial"].get("env", {}).items()})
        # GraphChecker experiments/lib/execute.sh passes this option to the
        # stock JUnit JVM; a custom trial command can also use {fault_trial}.
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
            Path(config["workspaces"][name]).resolve()
            for name in ("graphchecker", "system_test", "temp")]
        resolved_trace = trace.resolve()
        if not trace.is_absolute() or not any(
                resolved_trace == root or root in resolved_trace.parents
                for root in allowed_trace_roots):
            raise ValueError(f"trial trace must stay in a per-case workspace: {trace}")
        dynamic_closure = None
        aggregate = config["trial"].get("aggregate_command")
        if trace.is_file() and aggregate:
            aggregate_dir = trial_dir / "aggregate"
            aggregate_dir.mkdir(exist_ok=True)
            context["aggregate_dir"] = str(aggregate_dir)
            aggregate_result = run_command(aggregate, context,
                                           Path(config["cwd"]), env,
                                           aggregate_dir,
                                           config["timeout_seconds"])
            result["aggregate"] = aggregate_result
            state["active_runtime_seconds"] += aggregate_result["elapsed_seconds"]
            state["aggregate_runtime_seconds"] += aggregate_result["elapsed_seconds"]
            atomic_json(case_dir / "state.json", state)
            plan = Path(config["trial"]["closure_plan"].format_map(context))
            if aggregate_result["exit"] == 0 and plan.is_file():
                try:
                    dynamic_closure = read_closure(
                        plan, config["target"]["method"],
                        config["target"].get("occurrence"),
                        config["target"].get("region_id"),
                        allowed_target_request_apis=(
                            set(state["seed"]["closure"]["target_request_apis"])
                            if not config["target"].get("occurrence") and
                            state["seed"]["closure"]["target_request_apis"]
                            else None),
                        allowed_target_occurrences=(
                            set(state["seed"]["closure"]["target_addresses"])
                            if not config["target"].get("occurrence") and not
                            state["seed"]["closure"]["target_request_apis"]
                            else None))
                    result["dynamic_closure_plan"] = str(plan)
                except ValueError as error:
                    result["dynamic_graph_error"] = str(error)
        if trace.is_file():
            feedback = trace_feedback(trace, dynamic_closure or state["seed"]["closure"],
                                      config["target"])
            result.update(feedback)
            result["trace"] = str(trace)
            result["dynamic_graph"] = dynamic_closure is not None
            result["blocking_graph_gaps"] = (
                dynamic_closure or state["seed"]["closure"])["blocking_gaps"]
            result["closure_members"] = (
                dynamic_closure or state["seed"]["closure"])["evidence_tiers"]
        else:
            result.update({"trace": None, "matched_count": 0,
                           "applied_count": 0, "target_reached": False,
                           "oracle": False, "coverage": [], "points": []})
        result["sequence_id"] = active["id"]
        result["fault_count"] = len(active["sequence"])
        result["attempt"] = active["attempt"]
        result["completed_at"] = time.time()
        atomic_json(result_file, result)
    graph_blocked = bool(state["seed"]["closure"]["blocking_gaps"] or
                         result.get("blocking_graph_gaps"))
    selector_matched = strict_injection(result, active["sequence"])
    # Selector identity is proved by the runtime controller. A fault can
    # legitimately erase a versioned state edge in the faulted graph; keep
    # that graph gap separate from whether the selected fault was applied.
    strict = selector_matched and not state["seed"]["closure"]["blocking_gaps"]
    graph_feedback_valid = not graph_blocked and bool(result.get("dynamic_graph"))
    result["selector_matched"] = selector_matched
    result["strict_injection"] = strict
    result["graph_feedback_valid"] = graph_feedback_valid
    baseline_fatal_count = state["seed"]["feedback"].get(
        "target_fatal_exception_count", 0)
    result["baseline_target_fatal_exception_count"] = baseline_fatal_count
    result["differential_target_exception"] = bool(
        result.get("target_fatal_exception_count", 0) > baseline_fatal_count)
    if not selector_matched:
        status = "unmatched"
    elif not result.get("target_reached_after_fault"):
        status = "lost_target"
    elif result["oracle"] and result["differential_target_exception"]:
        status = "target_exception_candidate"
    elif not graph_feedback_valid:
        status = "graph_gap"
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
    old_members = state.get("closure_members", {})
    observed_members = {key: tier for key, tier in
                        result.get("closure_members", {}).items()
                        if key not in old_members}
    admitted = graph_feedback_valid and status in {
        "checked", "target_exception_candidate", "baseline_exception_recurrence"}
    new_coverage = observed_coverage if admitted else set()
    new_members = observed_members if admitted else {}
    if admitted:
        state["closure_members"] = {**old_members,
                                    **result.get("closure_members", {})}
    result["observed_new_coverage_count"] = len(observed_coverage)
    result["observed_new_closure_member_count"] = len(observed_members)
    result["new_coverage_count"] = len(new_coverage)
    result["new_closure_member_count"] = len(new_members)
    result["new_exact_closure_members"] = sum(
        tier == "EXACT" for tier in new_members.values())
    result["status"] = status
    atomic_json(result_file, result)
    if status == "graph_gap":
        state["status"] = "graph_gap"
        state["queue"] = []
    if admitted:
        state["coverage"] = sorted(old_coverage | set(result.get("coverage", [])))
    state["completed"].append({"id": active["id"], "number": active["number"],
                               "status": status, "result": str(result_file),
                               "elapsed_seconds": result["elapsed_seconds"],
                               "sequence": active["sequence"]})
    if admitted and \
            len(active["sequence"]) < config["budget"]["max_faults"]:
        for observed in result.get("point_events", []):
            point = observed["point"]
            if (observed.get("seq", -1) > result.get("last_applied_seq", -1)
                    and point not in active["sequence"]):
                tier = result.get("closure_members", {}).get(
                    point["occurrence"], "CANDIDATE")
                member_novelty = 50 if tier == "EXACT" else 20
                if point["occurrence"] not in new_members:
                    member_novelty = 0
                enqueue(state, active["sequence"] + [point],
                        priority=10 * len(new_coverage) +
                        member_novelty +
                        (3 if status == "target_exception_candidate" else 0))
    state["active"] = None


def validate(config: dict[str, Any]) -> None:
    needed = {"case_id", "system", "test_class", "test_method", "target",
              "cwd", "seed", "trial", "budget", "timeout_seconds",
              "workspaces"}
    missing = needed - config.keys()
    if missing:
        raise ValueError(f"missing config keys: {sorted(missing)}")
    if not config["target"].get("method") or not config["target"].get("exception_type"):
        raise ValueError("target requires exact method and exception_type")
    if "request_api" in config["target"] and (
            not isinstance(config["target"]["request_api"], str) or
            not config["target"]["request_api"]):
        raise ValueError("target.request_api must be a nonempty semantic operation")
    throw_event = config["target"].get("throw_event", "METHOD_EXIT_THROW")
    if throw_event not in {"METHOD_EXIT_THROW", "EXPLICIT_THROW"}:
        raise ValueError("target.throw_event must name a supported throw event")
    if throw_event == "EXPLICIT_THROW" and (
            not isinstance(config["target"].get("explicit_throw_site_id"), str)
            or "#u" not in config["target"]["explicit_throw_site_id"]):
        raise ValueError("EXPLICIT_THROW requires exact explicit_throw_site_id")
    load_target_policy(config["target"])
    if throw_event == "EXPLICIT_THROW":
        explicit_site = config["target"]["explicit_throw_site_id"]
        throw_method = config["target"].get("throw_method",
                                            config["target"]["method"])
        if explicit_site.split("#u", 1)[0] != throw_method:
            raise ValueError("explicit_throw_site_id differs from throw_method")
        if (config["target"].get("throw_site_id") and
                explicit_site != config["target"]["throw_site_id"]):
            raise ValueError("explicit_throw_site_id differs from throw_site_id")
    if not config["target"].get("region_id"):
        raise ValueError("target requires static region_id or scope_map + throw_site_id")
    fatal_guard_paths(config["target"])
    coverage_exclude_sites = config["target"].get("coverage_exclude_sites", [])
    if (not isinstance(coverage_exclude_sites, list) or
            any(not isinstance(site, str) or "#u" not in site
                for site in coverage_exclude_sites)):
        raise ValueError("target.coverage_exclude_sites needs exact site IDs")
    if any(guard["siteId"] in coverage_exclude_sites
           for path in fatal_guard_paths(config["target"])
           for guard in path):
        raise ValueError("cannot exclude a fatal target guard from coverage")
    if not isinstance(config["trial"].get("command"), list):
        raise ValueError("trial.command must be an argv list, never a shell string")
    if (not config["seed"].get("command") and
            "elapsed_seconds" not in config["seed"] and
            "timing_manifest" not in config["seed"]):
        raise ValueError("precomputed seed requires elapsed_seconds or timing_manifest")
    if (not isinstance(config["trial"].get("aggregate_command"), list) or
            not config["trial"].get("closure_plan")):
        raise ValueError("trial requires GraphChecker aggregate_command and closure_plan")
    if config["budget"]["max_trials"] < 1 or config["budget"]["max_faults"] < 1:
        raise ValueError("budgets must be positive")
    workspaces = config["workspaces"]
    for name in ("graphchecker", "system_test", "temp"):
        if name not in workspaces or not Path(workspaces[name]).is_absolute():
            raise ValueError(f"workspaces.{name} must be an absolute per-case path")
    paths = [Path(workspaces[name]).resolve() for name in
             ("graphchecker", "system_test", "temp")]
    if len(set(paths)) != len(paths):
        raise ValueError("GraphChecker, system test, and temp workspaces must differ")
    shared = [Path(value).resolve() for value in config.get("shared_readonly_roots", [])]
    for path in paths:
        if any(path == root or root in path.parents for root in shared):
            raise ValueError(f"workspace must be outside shared source: {path}")
    cwd = Path(config["cwd"]).resolve()
    if cwd not in paths[:2]:
        raise ValueError("cwd must be the case's GraphChecker or system test workspace")


def write_case_result(case_dir: Path, state: dict[str, Any]) -> None:
    completed = state["completed"]
    sequences = list(completed_sequences(state))
    results = [json.loads(Path(item["result"]).read_text())
               for item in completed]
    candidates = [item for item, result in zip(completed, results)
                  if result.get("status") == "target_exception_candidate"]
    status = state.get("status", "recorded_seed")
    if candidates and status not in TERMINAL:
        status = "candidate_review"
    elif any(result.get("status") == "graph_gap" for result in results):
        status = "graph_gap"
    elif completed and not state.get("finished"):
        status = "fuzzing"
    seed = state.get("seed") or {}
    initial_coverage = len(seed.get("feedback", {}).get("coverage", []))
    setup_seconds = float(state.get("setup_seconds", 0))
    build_seconds = float(state.get("build_seconds", 0))
    seed_seconds = float(state.get("seed_runtime_seconds", 0))
    fault_seconds = float(state.get("fault_runtime_seconds", 0))
    aggregate_seconds = float(state.get("aggregate_runtime_seconds", 0))
    total_seconds = round(setup_seconds + build_seconds + seed_seconds + fault_seconds +
                          aggregate_seconds, 3)
    record = {
        "schema_version": SCHEMA,
        "case_id": state["case_id"], "system": state["system"],
        "cluster_test": state["test_class"] + "#" + state["test_method"],
        "target_method": state.get("target_method"),
        "target_throw_method": state.get("target_throw_method"),
        "target_throw_site_id": state.get("target_throw_site_id"),
        "target_region_id": state.get("target_region_id"),
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
        "post_fault_target_reach_trials": sum(
            bool(result.get("target_reached_after_fault")) for result in results),
        "lost_target_trials": sum(result.get("status") == "lost_target"
                                  for result in results),
        "target_after_fault": sum(bool(result.get("target_after_fault"))
                                  for result in results),
        "target_exception_after_fault_trials": sum(
            bool(result.get("target_after_fault")) for result in results),
        "oracle_candidates": len(candidates),
        "coverage_gain": max(0, len(state.get("coverage", [])) - initial_coverage),
        "setup_seconds": round(setup_seconds, 3),
        "build_seconds": round(build_seconds, 3),
        "seed_seconds": round(seed_seconds, 3),
        "fault_seconds": round(fault_seconds, 3),
        "aggregate_seconds": round(aggregate_seconds, 3),
        "total_elapsed_seconds": total_seconds,
        "elapsed_seconds": total_seconds,
        "bug_mark": "candidate" if candidates else "none",
        "evidence": candidates[0]["result"] if candidates else
                    (completed[-1]["result"] if completed else None),
        "graph_blocking_gaps": (
            len(seed.get("closure", {}).get("blocking_gaps", [])) +
            sum(len(result.get("blocking_graph_gaps", [])) for result in results)),
        "graph_edges_unavailable": seed.get("closure", {}).get("edges_unavailable"),
        "started_at": state.get("started"),
        "updated_at": time.time(),
    }
    atomic_json(case_dir / "result.json", record)


class CaseLease:
    """One cross-host owner; stale takeover requires both TTL and free flock."""

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


def campaign(config: dict[str, Any], root: Path) -> dict[str, Any]:
    validate(config)
    case_dir = root / config["case_id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    Path(config["workspaces"]["temp"]).mkdir(parents=True, exist_ok=True)
    with CaseLease(case_dir):
        path = case_dir / "state.json"
        # Budgets can grow without changing the JUnit/test/target identity of
        # already completed trials.  A changed workload or fault selector
        # contract still requires a new case directory.
        config_digest = fingerprint({key: value for key, value in config.items()
                                     if key not in {"budget", "timeout_seconds"}})
        if path.exists():
            state = json.loads(path.read_text())
            if state["config_digest"] != config_digest:
                raise ValueError("case config changed; use a new case directory")
            state.setdefault("active_runtime_seconds", 0.0)
            state.setdefault("seed_runtime_seconds", 0.0)
            state.setdefault("fault_runtime_seconds", 0.0)
            state.setdefault("aggregate_runtime_seconds", 0.0)
            state.setdefault("closure_members", {})
            state.setdefault("setup_seconds", float(config.get("setup_seconds", 0)))
            state.setdefault("build_seconds", float(config.get("build_seconds", 0)))
            state.setdefault("target_method", config["target"]["method"])
            state.setdefault("target_throw_method", config["target"].get(
                "throw_method", config["target"]["method"]))
            state.setdefault("target_throw_site_id", config["target"].get(
                "throw_site_id"))
            state.setdefault("target_region_id", config["target"].get("region_id"))
            state.setdefault("target_source_file", config["target"].get("source_file"))
            state.setdefault("target_source_line", config["target"].get("source_line"))
            state.setdefault("target_code", config["target"].get("code"))
            state.setdefault("coverage_exclude_sites",
                             config["target"].get("coverage_exclude_sites", []))
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
                     "target_region_id": config["target"]["region_id"],
                     "target_source_file": config["target"].get("source_file"),
                     "target_source_line": config["target"].get("source_line"),
                     "target_code": config["target"].get("code"),
                     "coverage_exclude_sites": config["target"].get(
                         "coverage_exclude_sites", []),
                     "config_digest": config_digest, "seed": None,
                     "coverage": [], "queue": [], "seen_sequences": [],
                     "closure_members": {}, "active_runtime_seconds": 0.0,
                     "seed_runtime_seconds": 0.0,
                     "fault_runtime_seconds": 0.0,
                     "aggregate_runtime_seconds": 0.0,
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
        if state.get("status") in {"graph_gap", "no_closure_fault_points",
                                   "healthy_target_unreached"}:
            state["finished"] = False
            atomic_json(path, state)
            write_case_result(case_dir, state)
            return state
        max_runtime = config["budget"].get("max_seconds", 1e18)
        while (state.get("status") != "graph_gap" and
               len(state["completed"]) < config["budget"]["max_trials"] and
               (state["active"] or state["active_runtime_seconds"] < max_runtime) and
               (state["queue"] or state["active"])):
            if state["active"] is None:
                item = state["queue"].pop(choose_next_sequence(state))
                state["active"] = {**item, "number": len(state["completed"]) + 1}
                atomic_json(path, state)
            process_trial(config, state, case_dir, state["active"])
            atomic_json(path, state)
            write_case_result(case_dir, state)
        state["last_updated"] = time.time()
        state["finished"] = bool(state.get("status") != "graph_gap" and
                                 not state["active"] and
                                 (not state["queue"] or
                                  len(state["completed"]) >= config["budget"]["max_trials"] or
                                  state["active_runtime_seconds"] >= max_runtime))
        if state["finished"] and state.get("status") not in TERMINAL:
            valid_trial_statuses = {"checked", "target_exception_candidate",
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
