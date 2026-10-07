#!/usr/bin/env python3
"""Resumable coverage and I/O guided SOLR-05 receiver-read fault campaign."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from audit_v4 import (CASE, EVIDENCE, PATH, CALLER, CONTEXT, healthy, observed_pairs,
                      semantic, trace_events, trial)
from deps import asm_jars

ROOT = EVIDENCE / "campaign-v4"
STATE = ROOT / "checkpoint.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
BASE_GOAL, EXT_GOAL = 80, 128
BASE_ATTEMPTS, EXT_ATTEMPTS = 320, 512


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
    tmp.replace(path)


def coverage(directory: Path) -> tuple[set[str], set[str], dict[str, int]]:
    execution = directory / "jacoco.exec"
    if not execution.is_file():
        return set(), set(), {}
    cp = ":".join([str(CASE / "classes"), str(CASE.parent / "lib/jacoco-core.jar"),
                   *map(str, asm_jars()), (CASE / "classpath.txt").read_text().strip()])
    blocks = subprocess.check_output([JAVA, "-cp", cp,
        "baseline.solr05v4.CoverageProbes", str(execution), DIST], text=True)
    methods_out = subprocess.check_output([JAVA, "-cp", cp,
        "baseline.solr05v4.CoverageFeedback", DIST, str(CASE / "classes"),
        str(execution)], text=True)
    branches = {}
    for line in methods_out.splitlines():
        method, count = line.rsplit("\t", 1)
        branches[method] = int(count)
    return set(blocks.splitlines()), set(branches), branches


def family(e: dict) -> str | None:
    if e["kind"] not in ("IO_OBSERVED", "RECEIVER_IO_OBSERVED", "UPSTREAM_IO_OBSERVED"):
        return None
    p = e["parts"]
    if len(p) < 3:
        return None
    operation, path, caller = p[:3]
    if not (path.startswith("/collections/testAddMultipleReplicas") or
            path.startswith("/live_nodes") or path.startswith("/overseer")):
        return None
    if "/leader_elect/" in path:
        resource = "leader-election"
    elif "/leaders/" in path:
        resource = "leader-state"
    elif path.endswith("/state.json"):
        resource = "collection-state"
    elif path.startswith("/overseer"):
        resource = "overseer"
    elif path.startswith("/live_nodes"):
        resource = "live-nodes"
    else:
        resource = "collection-other"
    return "|".join((operation, resource, caller.split(":", 1)[0]))


def key(e: dict) -> tuple[str, ...]:
    f = e["fields"]
    return tuple([e["parts"][0], e["parts"][1], e["parts"][2],
                  *(f[k] for k in CONTEXT)])


def selector(e: dict, ordinal: int, after: str | None = None,
             global_hit: int = 0) -> str:
    f = e["fields"]
    parts = [e["parts"][0], e["parts"][1],
             ("@" if after else "") + str(ordinal), e["parts"][2],
             "actor=receiver_state_read_for_replica",
             *(k + "=" + f[k] for k in CONTEXT)]
    if after:
        parts.extend(["after=" + after, "seed_global=" + str(global_hit)])
    return "|".join(parts)


def plan_id(plan: list[str]) -> str:
    return hashlib.sha256(";".join(plan).encode()).hexdigest()[:20]


def eligible_pairs(events: list[dict]) -> list[dict]:
    pairs = observed_pairs(events)
    targets = [e for e in events if e["kind"] == "TARGET_CHECK" and
               e["parts"][1] == "SOLR-05"]
    return [p for p in pairs if any(t["seq"] > p["read"]["seq"] and
                                   semantic(t) == semantic(p["read"]) and
                                   t["fields"].get("client_id") ==
                                   p["read"]["fields"].get("client_id") and
                                   t["fields"].get("reader_id") ==
                                   p["read"]["fields"].get("reader_id")
                                   for t in targets)]


def seeds() -> list[dict]:
    entries = {}
    for name in ("healthy-001", "healthy-002"):
        events = trace_events(EVIDENCE / name / "events.tsv")
        counts = Counter()
        for e in events:
            if e["kind"] != "RECEIVER_IO_OBSERVED":
                continue
            identity = key(e)
            counts[identity] += 1
            if not any(p["read"]["seq"] == e["seq"] for p in eligible_pairs(events)):
                continue
            plan = [selector(e, counts[identity])]
            entries[plan_id(plan)] = {"plan": plan, "priority": 100 + e["seq"],
                                       "reason": "healthy version-linked receiver read"}
    return sorted(entries.values(), key=lambda e: -e["priority"])


def initial() -> dict:
    calibration = [healthy(EVIDENCE / n) for n in
                   ("original-001", "original-002", "healthy-001", "healthy-002")]
    base_blocks, base_methods, base_branches, base_io = set(), set(), {}, set()
    for name in ("healthy-001", "healthy-002"):
        directory = EVIDENCE / name
        blocks, methods, branches = coverage(directory)
        base_blocks |= blocks
        base_methods |= methods
        for k, v in branches.items():
            base_branches[k] = max(v, base_branches.get(k, 0))
        base_io |= {v for e in trace_events(directory / "events.tsv")
                    if (v := family(e)) is not None}
    queue = seeds()
    if not queue:
        raise ValueError("no version-linked receiver read before target guard")
    state = {"case": "SOLR-05", "identity_version": "receiver-state-read-v4",
             "test": "AddReplicaTest.testAddMultipleReplicas",
             "started_at_utc": utc(), "updated_at_utc": utc(),
             "calibration": calibration, "legacy_attempts_imported": 0,
             "legacy_effective_imported": 0,
             "budget": {"effective_goal": BASE_GOAL, "max_faults": 8,
                        "attempt_cap": BASE_ATTEMPTS},
             "extension": "pending", "recent_eight_effective": [],
             "coverage_union": sorted(base_blocks), "method_union": sorted(base_methods),
             "branch_union": base_branches, "io_union": sorted(base_io),
             "queue": queue, "seen_plans": [], "inflight": None, "trials": [],
             "effective": 0, "status": "running"}
    atomic(STATE, state)
    return state


def enqueue(state: dict, plan: list[str], priority: int, reason: str) -> None:
    token = plan_id(plan)
    if token in state["seen_plans"] or any(
            plan_id(item["plan"]) == token for item in state["queue"]):
        return
    state["queue"].append({"plan": plan, "priority": priority, "reason": reason})


def mutate(state: dict, plan: list[str], events: list[dict], report: dict,
           novelty: dict) -> None:
    if not report["effective"] or len(plan) >= state["budget"]["max_faults"]:
        return
    faults = [e for e in events if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    final = faults[-1]["seq"]
    counts, relative = Counter(), Counter()
    candidates = []
    for e in events:
        if e["kind"] != "RECEIVER_IO_OBSERVED":
            continue
        identity = key(e)
        counts[identity] += 1
        if e["seq"] > final:
            relative[identity] += 1
        if e["seq"] <= final or relative[identity] == 0:
            continue
        if not any(p["read"]["seq"] == e["seq"] for p in eligible_pairs(events)):
            continue
        child = plan + [selector(e, relative[identity],
                                 after="F" + str(len(plan) - 1),
                                 global_hit=counts[identity])]
        candidates.append((e["seq"], child))
    if not candidates:
        return
    novel = novelty["methods"] or novelty["branches"] or novelty["io"]
    # Keep both close and distant successors to vary the recovery window.
    candidates.sort(reverse=True)
    selected = candidates[:3] + candidates[-2:]
    for seq, child in selected[:5 if novel else 3]:
        enqueue(state, child, 100 + len(child) * 30 + (seq % 17) + 30 * bool(novel),
                "runtime post-fault receiver read and later same-replica guard")
    state["queue"].sort(key=lambda item: (-item["priority"], plan_id(item["plan"])))


def consume(state: dict, directory: Path, plan: list[str], reason: str) -> dict:
    audit = trial(directory, plan)
    events = trace_events(directory / "events.tsv")
    eligible = audit["strict"] and audit["effective"]
    blocks, methods, branches = coverage(directory) if eligible else (set(), set(), {})
    ios = {v for e in events if (v := family(e)) is not None} if eligible else set()
    old_blocks = set(state["coverage_union"])
    old_methods = set(state["method_union"])
    old_branches = state["branch_union"]
    old_ios = set(state["io_union"])
    novelty = {"blocks": len(blocks - old_blocks),
               "methods": len(methods - old_methods),
               "branches": sum(max(0, count - old_branches.get(k, 0))
                               for k, count in branches.items()),
               "io": len(ios - old_ios)}
    if eligible:
        state["coverage_union"] = sorted(old_blocks | blocks)
        state["method_union"] = sorted(old_methods | methods)
        state["io_union"] = sorted(old_ios | ios)
        for k, count in branches.items():
            old_branches[k] = max(old_branches.get(k, 0), count)
        state["effective"] += 1
        state["recent_eight_effective"] = (
            state["recent_eight_effective"] + [{"number": len(state["trials"]) + 1,
                **novelty}])[-8:]
    row = {"number": len(state["trials"]) + 1, "plan": plan,
           "reason": reason, "evidence": str(directory.relative_to(CASE)),
           "audit": audit, "new": novelty,
           "elapsed_seconds": audit["elapsed_seconds"], "completed_at_utc": utc()}
    state["trials"].append(row)
    state["seen_plans"].append(plan_id(plan))
    if eligible:
        mutate(state, plan, events, audit, novelty)
    if state["effective"] == BASE_GOAL and state["extension"] == "pending":
        continuing = any(x["methods"] or x["branches"] or x["io"] for x in
                         state["recent_eight_effective"])
        state["extension"] = "extended" if continuing else "not_extended"
        if continuing:
            state["budget"] = {"effective_goal": EXT_GOAL,
                               "max_faults": 10, "attempt_cap": EXT_ATTEMPTS}
    if state["effective"] >= state["budget"]["effective_goal"]:
        state["status"] = "budget_reached"
    elif len(state["trials"]) >= state["budget"]["attempt_cap"]:
        state["status"] = "attempt_cap_before_goal"
    elif not state["queue"]:
        state["status"] = "queue_exhausted_before_goal"
    state["updated_at_utc"] = utc()
    atomic(directory / "v4-trial.json", row)
    state["inflight"] = None
    atomic(STATE, state)
    if not audit["target_exception"]:
        scratch = directory / "scratch"
        if scratch.exists():
            shutil.rmtree(scratch)
    return row


def import_pilot(state: dict) -> None:
    directory = EVIDENCE / "pilot-001"
    if state["trials"] or not (directory / "manifest.json").is_file():
        return
    manifest = json.loads((directory / "manifest.json").read_text())
    plan = manifest["faults"].split(";")
    state["queue"] = [q for q in state["queue"] if q["plan"] != plan]
    row = consume(state, directory, plan, "independently audited V4 pilot")
    if not row["audit"]["effective"]:
        raise ValueError("V4 pilot did not retain the exact target")


def pick(state: dict) -> dict:
    if (len(state["trials"]) + 1) % 4 == 0:
        for i, row in enumerate(state["queue"]):
            if len(row["plan"]) == 1:
                return state["queue"].pop(i)
    return state["queue"].pop(0)


def once(state: dict) -> dict:
    if state["inflight"] is None:
        state["inflight"] = pick(state)
        state["inflight"]["number"] = len(state["trials"]) + 1
        atomic(STATE, state)
    inflight = state["inflight"]
    number, plan = inflight["number"], inflight["plan"]
    directory = ROOT / f"trial-{number:03d}"
    subprocess.run([sys.executable, str(CASE / "probe/run.py"), str(directory),
                    "--coverage", "--faults", ";".join(plan), "--timeout", "240"],
                   check=False)
    row = consume(state, directory, plan, inflight["reason"])
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--wall-seconds", type=int, default=43200)
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else initial()
    if not state["trials"]:
        import_pilot(state)
    if not args.run and not args.once:
        print(json.dumps({"status": state["status"], "trials": len(state["trials"]),
                          "effective": state["effective"], "queued": len(state["queue"]),
                          "inflight": state["inflight"], "budget": state["budget"]}))
        return
    deadline = time.monotonic() + args.wall_seconds
    while state["status"] == "running" and time.monotonic() < deadline:
        row = once(state)
        print(json.dumps({"number": row["number"],
                          "strict": row["audit"]["strict"],
                          "effective": state["effective"],
                          "target_exception": row["audit"]["target_exception"],
                          "queued": len(state["queue"]), "status": state["status"]}),
              flush=True)
        if args.once:
            break


if __name__ == "__main__":
    main()
