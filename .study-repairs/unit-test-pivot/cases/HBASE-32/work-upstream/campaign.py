#!/usr/bin/env python3
"""Resumable HBASE-32 Master/WAL I/O fuzzing on the unchanged MiniCluster JUnit.

This stage has its own seed, queue, coverage union, and effective denominator.
Only precisely attributed Master OPENED and WAL append/sync calls are mutable.
"""

from collections import Counter
from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
CHECKPOINT = HERE / "supplemental-checkpoint.json"
INFLIGHT = HERE / "supplemental-inflight.json"
RESULT = HERE / "supplemental-result.json"
KINDS = ("DO_NOT_RETRY_IOEXCEPTION", "IOEXCEPTION", "SOCKET_TIMEOUT", "EOF_EXCEPTION")
RNG_SEED = 32032
CHILD_CAP = 24
UNMATCHED_RETRY_LIMIT = 2
INITIAL_EFFECTIVE = 80
EXTENDED_EFFECTIVE = 128
INITIAL_ATTEMPT_CAP = 240
EXTENDED_ATTEMPT_CAP = 384


def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def raw_log_sha256(path):
    h = hashlib.sha256()
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_lines(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", errors="replace") as source:
        yield from enumerate(source, 1)


def active_trial(trial_id):
    marker = ("data-" + trial_id).encode()
    runner = trial_id.encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if marker in b" ".join(args):
            return True
        if any(b"trial_runner.py" in arg for arg in args) and runner in args:
            return True
    return False


def recover_inflight(trial_id, log, receipt):
    """Settle a finished orphan once; preserve a genuinely incomplete attempt."""
    if receipt.exists() or not log.exists() or active_trial(trial_id):
        return
    tail = log.read_text(errors="replace")[-4000:]
    elapsed = re.search(r"ELAPSED_SECONDS=([\d.]+)", tail)
    failed = re.search(r"HBASE32 JUNIT found=\d+ succeeded=\d+ failed=(\d+)", tail)
    nonzero = re.search(r"Command exited with non-zero status (\d+)", tail)
    if elapsed and (nonzero or failed):
        code = int(nonzero[1]) if nonzero else (1 if int(failed[1]) else 0)
        temp = receipt.with_suffix(".exit.tmp")
        with temp.open("w") as output:
            output.write(str(code) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, receipt)
        atomic_json(HERE / "logs" / (trial_id + ".recovered.json"),
                    {"trial": trial_id, "exit_inferred_from_terminal_log": code,
                     "raw_log_sha256": sha256(log)})
        return
    suffix = ".interrupted-" + str(int(time.time()))
    archived = log.with_name(trial_id + suffix + ".log")
    log.rename(archived)
    exec_file = HERE / "logs" / (trial_id + ".exec")
    if exec_file.exists():
        exec_file.rename(HERE / "logs" / (trial_id + suffix + ".exec"))
    atomic_json(HERE / "logs" / (trial_id + suffix + ".json"),
                {"trial": trial_id, "reason": "no terminal receipt or live process",
                 "raw_log_sha256": sha256(archived)})


def parse_log(path):
    trace = {key: [] for key in ("TARGET", "CLIENT_FLUSH_TAG", "SERVER_FLUSH_TAG",
             "MASTER_OPENED_RPC", "WAL_APPEND_START", "WAL_SYNC_START",
             "FAULT_APPLIED", "TARGET_GUARD", "TARGET_B7_RETHROW", "RS_ABORT")}
    trace["junit"] = None
    trace["elapsed_seconds"] = None
    trace["shutdown_hook_line"] = None
    for number, line in read_lines(path):
        if trace["shutdown_hook_line"] is None and "Shutdown hook starting" in line:
            trace["shutdown_hook_line"] = number
        if "HBASE32U " in line:
            tail = line.split("HBASE32U ", 1)[1]
            kind = tail.split(" ", 1)[0]
            if kind in trace:
                trace[kind].append({"line": number,
                                    **dict(re.findall(r"([a-z_]+)=([^\s]+)", tail))})
        if "HBASE32 TARGET_GUARD" in line or "HBASE32 TARGET_B7_RETHROW" in line:
            kind = "TARGET_GUARD" if "TARGET_GUARD" in line else "TARGET_B7_RETHROW"
            trace[kind].append({"line": number,
                                **dict(re.findall(r"([a-z_]+)=([^\s]+)", line))})
        match = re.search(r"\*\*\*\*\* ABORTING region server ([^: ]+):", line)
        if match:
            trace["RS_ABORT"].append({"line": number, "server": match[1]})
        match = re.search(r"HBASE32 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)", line)
        if match:
            trace["junit"] = {"found": int(match[1]), "succeeded": int(match[2]),
                              "failed": int(match[3])}
        match = re.search(r"ELAPSED_SECONDS=([\d.]+)", line)
        if match:
            trace["elapsed_seconds"] = float(match[1])
    return trace


def selector_events(trace):
    """Generate only callsites with exact same-run region and actor evidence."""
    targets = {(e["raw_primary_region"], e["replica"], e["target_ordinal"])
               for e in trace["TARGET"]}
    secondary = {(e["raw_primary_region"], e["raw_secondary_region"], e["replica"])
                 for e in trace["TARGET"]}
    client = {e["actor_tag"] for e in trace["CLIENT_FLUSH_TAG"]}
    server = {e["actor_tag"] for e in trace["SERVER_FLUSH_TAG"]}
    selected = []
    def table2(stable_region):
        raw = base64.urlsafe_b64decode(stable_region + "=" * (-len(stable_region) % 4))
        return raw.startswith(b"testLotsOfRegionRepli2,")
    for event in trace["MASTER_OPENED_RPC"]:
        if not table2(event["stable_region"]):
            continue
        if (event["raw_primary_region"], event["raw_secondary_region"], event["replica"]) \
                not in secondary:
            continue
        selected.append((event["line"], "MASTER_OPENED_RPC~" + event["stable_region"]
                         + "~replica-" + event["replica"]
                         + "~attempt-" + event["attempt"]))
    for family in ("WAL_APPEND_START", "WAL_SYNC_START"):
        for event in trace[family]:
            if not table2(event["stable_region"]):
                continue
            if event.get("from_flush_rpc") != "true" or event.get("action") != "CANNOT_FLUSH":
                continue
            tag = event.get("actor_tag", "")
            parts = tag.split("|")
            if (len(parts) != 4 or tag not in client or tag not in server
                    or parts[0] != event["raw_primary_region"]
                    or tuple(parts[:3]) not in targets):
                continue
            selected.append((event["line"], family + "~" + event["stable_region"]
                             + "~replica-" + parts[1] + "~target-" + parts[2]
                             + "~marker-" + event["marker_ordinal"]))
    return sorted(selected)


def coverage(paths):
    run = subprocess.run(["bash", str(HERE / "run.sh"), "coverage",
                          ",".join(str(path) for path in paths)],
                         capture_output=True, text=True, check=False)
    if run.returncode:
        raise RuntimeError("JaCoCo analysis failed: " + run.stderr[-1500:])
    classes = {}
    target = None
    for line in run.stdout.splitlines():
        match = re.fullmatch(r"COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)",
                             line)
        if match:
            classes[match[1]] = {"methods": int(match[2]), "branches": int(match[3]),
                                  "lines": int(match[4])}
        match = re.fullmatch(r"TARGET line=136 instructions=(\d+) branches=(\d+)", line)
        if match:
            target = {"instructions": int(match[1]), "branches": int(match[2])}
    if len(classes) != 9 or target is None:
        raise RuntimeError("Expected 9 production classes and B7 line: " + run.stdout)
    return {"classes": classes, "target_line_136": target,
            "methods": sum(c["methods"] for c in classes.values()),
            "branches": sum(c["branches"] for c in classes.values()),
            "lines": sum(c["lines"] for c in classes.values())}


def strict(trace, plan):
    events = trace["FAULT_APPLIED"]
    return len(events) == len(plan) and all(
        event.get("selector", "") + "~" + event.get("kind", "") == expected
        and event.get("step") == str(index)
        for index, (event, expected) in enumerate(zip(events, plan), 1))


def target_outcome(trace, plan):
    if not strict(trace, plan):
        return {"method": [], "progress": [], "guard": [], "b7": []}
    last = trace["FAULT_APPLIED"][-1]
    selector = last["selector"]
    family = selector.split("~", 1)[0]
    replica_match = re.search(r"~replica-(\d+)~", selector)
    if replica_match is None:
        return {"method": [], "progress": [], "guard": [], "b7": []}
    replica = replica_match[1]
    primary = last["raw_primary_region"]
    ordinal_match = re.search(r"~target-(\d+)~", selector)
    ordinal = ordinal_match[1] if ordinal_match else None
    method = [event for event in trace["TARGET"]
              if event["line"] > last["line"] and event["raw_primary_region"] == primary
              and event["replica"] == replica
              and (family != "MASTER_OPENED_RPC" or
                   event["raw_secondary_region"] == last.get("raw_secondary_region"))]
    if ordinal is None and method:
        ordinal = method[0]["target_ordinal"]
    progress = [event for event in trace["CLIENT_FLUSH_TAG"]
                if event["line"] > last["line"]
                and event.get("raw_primary_region") == primary
                and event.get("replica") == replica
                and event.get("target_ordinal") == ordinal]
    def related(event):
        return (event["line"] > last["line"]
                and event.get("raw_primary_region") == primary
                and event.get("replica_id") == replica
                and event.get("target_ordinal") == ordinal)
    guard = [event for event in trace["TARGET_GUARD"] if related(event)]
    b7 = [event for event in trace["TARGET_B7_RETHROW"] if related(event)]
    return {"method": method, "progress": progress, "guard": guard, "b7": b7}


def enqueue(state, prefix, selectors, after, novelty, seconds):
    if len(prefix) >= state["max_faults"]:
        return
    pool = list(dict.fromkeys(selector for line, selector in selectors if line > after))
    seed = int.from_bytes(hashlib.sha256((str(RNG_SEED) + ";" + ";".join(prefix)).encode())
                          .digest()[:8], "big")
    random.Random(seed).shuffle(pool)
    if prefix:
        # A continued RPC from the same raw secondary actor is the most
        # direct way to exhaust the target's retry path after one WAL error.
        last = prefix[-1].rsplit("~", 1)[0]
        region = last.split("~")[1]
        replica = re.search(r"~replica-(\d+)~", last)
        actor = re.search(r"~target-(\d+)~", last)
        familiar = set(state["healthy_selectors"])
        if replica:
            common = "~" + region + "~replica-" + replica[1] + "~"
            exact = common + "target-" + actor[1] + "~" if actor else None
            pool.sort(key=lambda item: (0 if exact and exact in item else
                                        1 if common in item else 2,
                                        item in familiar))
        else:
            pool.sort(key=lambda item: item in familiar)
        pool = pool[:CHILD_CAP]
    seen = set(state["seen_plans"])
    for selector in pool:
        for kind in KINDS:
            plan = prefix + [selector + "~" + kind]
            key = ";".join(plan)
            if key not in seen:
                seen.add(key)
                state["queue"].append({"plan": plan, "parent_novelty": novelty,
                                       "parent_seconds": seconds or 60, "wait": 0})
    state["seen_plans"] = sorted(seen)


def priority(entry, tried, family_counts):
    last = entry["plan"][-1]
    selector = last.rsplit("~", 1)[0]
    family = selector.split("~", 1)[0]
    actors = [re.search(r"~([^~]+)~replica-(\d+)~(?:target-(\d+)~)?", step)
              for step in entry["plan"]]
    same_actor = (len(actors) > 1 and all(actor is not None for actor in actors)
                  and len({(actor[1], actor[2], actor[3]) for actor in actors}) == 1)
    return (30 * (not tried[selector]) + min(entry["wait"] // 5, 20)
            + min(entry["parent_novelty"] * 2, 12)
            + (25 if len(entry["plan"]) == 1 else 0)
            + (12 if family.startswith("WAL_") else 8)
            - min(family_counts[family] // 4, 20)
            + (20 if same_actor else 0)
            - 30 * entry.get("unmatched_retries", 0)
            - min(entry["parent_seconds"] / 20, 12))


def prune(state):
    invalid = [trial["plan"] for trial in state["trials"]
               if trial["invalid_cluster"] or (trial["strict"] and not trial["target_retained"])]
    state["queue"] = [entry for entry in state["queue"]
                      if not any(len(entry["plan"]) > len(prefix)
                                 and entry["plan"][:len(prefix)] == prefix
                                 for prefix in invalid)]


def publish(state, status="running"):
    atomic_json(CHECKPOINT, state)
    trials = state["trials"]
    effective = [trial for trial in trials if trial["effective"]]
    result = {"case": "HBASE-32", "phase": "independent_upstream_master_wal",
              "status": status, "workload": "TestRegionReplicaFailover#testLotsOfRegionReplicas",
              "attempted": len(trials), "fully_applied": sum(t["strict"] for t in trials),
              "postfault_target_method": sum(t["target_method_after_fault"] for t in trials),
              "postfault_same_actor_retry": sum(t["same_actor_retry_after_fault"] for t in trials),
              "postfault_same_actor_guard": len(effective),
              "exact_b7": sum(t["exact_b7"] for t in trials),
              "target_lost": sum(t["strict"] and not t["target_retained"] for t in trials),
              "invalid_cluster": sum(t["invalid_cluster"] for t in trials),
              "queue_length": len(state["queue"]),
              "production_coverage": state["coverage_union"],
              "healthy_production_coverage": state["healthy_coverage"],
              "admitted_feedback_trials": sum(t["coverage_admitted"] for t in trials),
              "budget": {"effective": state["effective_budget"],
                         "attempt_cap": state["attempt_cap"], "max_faults": state["max_faults"]},
              "pending_review": [t["id"] for t in trials if t["review_candidate"]],
              "checkpoint": str(CHECKPOINT.relative_to(HERE.parent))}
    atomic_json(RESULT, result)


def main():
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        if INFLIGHT.exists():
            pending = json.loads(INFLIGHT.read_text())
            completed = next((trial for trial in state["trials"]
                              if trial["id"] == pending["id"]), None)
            if completed:
                if completed["plan"] != pending["entry"]["plan"]:
                    raise RuntimeError("Completed trial conflicts with stale inflight marker")
                INFLIGHT.unlink()
        if state.get("version", 1) < 2:
            counts = Counter(tuple(trial["plan"]) for trial in state["trials"])
            queued = {tuple(entry["plan"]) for entry in state["queue"]}
            restored = []
            for trial in state["trials"]:
                key = tuple(trial["plan"])
                if (not trial["strict"] and counts[key] <= UNMATCHED_RETRY_LIMIT
                        and key not in queued):
                    state["queue"].append({"plan": trial["plan"],
                                           "parent_novelty": 0,
                                           "parent_seconds": trial["elapsed_seconds"] or 60,
                                           "wait": 0,
                                           "unmatched_retries": counts[key]})
                    queued.add(key)
                    restored.append(trial["id"])
            state.setdefault("migration_log", []).append({
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "to_version": 2, "restored_unmatched_plans": restored,
                "queue_length": len(state["queue"]),
                "coverage_union_unchanged": state["coverage_union"]})
            state["version"] = 2
            publish(state)
        if state.get("version", 1) < 3:
            # Versions 1/2 pruned any sequence with three DNR faults, even
            # though HBase retries a failed WAL marker up to five times. Bring
            # back only children of admitted two-DNR runs. Their original raw
            # traces determine both the event order and exact actor identity.
            before_queue = len(state["queue"])
            before_seen = len(state["seen_plans"])
            state["seen_plans"] = [key for key in state["seen_plans"]
                                   if sum(step.endswith("~DO_NOT_RETRY_IOEXCEPTION")
                                          for step in key.split(";")) <= 2]
            restored_from = []
            for trial in state["trials"]:
                if (not trial["coverage_admitted"] or
                        sum(step.endswith("~DO_NOT_RETRY_IOEXCEPTION")
                            for step in trial["plan"]) != 2):
                    continue
                path = HERE.parent / trial["log"]
                trace = parse_log(path)
                if not strict(trace, trial["plan"]):
                    raise RuntimeError("Admitted parent lost exact trace: " + trial["id"])
                enqueue(state, trial["plan"], selector_events(trace),
                        trace["FAULT_APPLIED"][-1]["line"],
                        trial["new_branches_methods"], trial["elapsed_seconds"])
                restored_from.append(trial["id"])
            prune(state)
            state.setdefault("migration_log", []).append({
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "to_version": 3,
                "reason": "remove_unsupported_two_DNR_fault_limit",
                "restored_from_admitted_parents": restored_from,
                "queue_before": before_queue,
                "queue_after": len(state["queue"]),
                "seen_before": before_seen,
                "seen_after": len(state["seen_plans"]),
                "coverage_union_unchanged": state["coverage_union"],
                "io_union_unchanged_sha256": hashlib.sha256(
                    json.dumps(state["io_union"], sort_keys=True).encode()).hexdigest()})
            state["version"] = 3
            publish(state)
    else:
        healthy_log = HERE / "logs/healthy4.log"
        healthy_exec = HERE / "logs/healthy4.exec"
        trace = parse_log(healthy_log)
        if (trace["junit"] != {"found": 1, "succeeded": 1, "failed": 0}
                or trace["TARGET_GUARD"] or trace["TARGET_B7_RETHROW"]):
            raise RuntimeError("Unhealthy original-JUnit seed")
        selectors = selector_events(trace)
        family_counts = Counter(item.split("~", 1)[0] for _, item in selectors)
        if (family_counts["MASTER_OPENED_RPC"] < 500
                or family_counts["WAL_APPEND_START"] < 300
                or family_counts["WAL_SYNC_START"] < 300):
            raise RuntimeError("Exact upstream seed identities are missing")
        baseline = coverage([healthy_exec])
        state = {"version": 3, "rng_seed": RNG_SEED,
                 "healthy_log_sha256": sha256(healthy_log),
                 "healthy_exec_sha256": sha256(healthy_exec),
                 "healthy_selector_families": dict(family_counts),
                 "healthy_selectors": sorted(set(item for _, item in selectors)),
                 "io_union": sorted(set(item for _, item in selectors)),
                 "healthy_coverage": baseline, "coverage_union": baseline,
                 "coverage_execs": [str(healthy_exec)], "trials": [],
                 "queue": [], "seen_plans": [], "effective_budget": INITIAL_EFFECTIVE,
                 "attempt_cap": INITIAL_ATTEMPT_CAP, "max_faults": 8,
                 "extended": False, "created_utc": datetime.now(timezone.utc).isoformat()}
        enqueue(state, [], selectors, -1, 0, trace["elapsed_seconds"])
        publish(state)
    if os.environ.get("HBASE32U_INIT_ONLY") == "1":
        print("HBASE32U initialized", state["healthy_selector_families"],
              "queue", len(state["queue"]), flush=True)
        return
    while True:
        effective_count = sum(t["effective"] for t in state["trials"])
        if effective_count >= state["effective_budget"]:
            if not state["extended"] and effective_count >= INITIAL_EFFECTIVE:
                last_eight = [t for t in state["trials"] if t["effective"]][-8:]
                if any(t["new_branches_methods"] or t["new_io_selectors"]
                       for t in last_eight):
                    state["effective_budget"] = EXTENDED_EFFECTIVE
                    state["attempt_cap"] = EXTENDED_ATTEMPT_CAP
                    state["max_faults"] = 10
                    state["extended"] = True
                    state["extension_reason"] = "last_eight_effective_novelty"
                    publish(state)
                    continue
            break
        if len(state["trials"]) >= state["attempt_cap"] or not state["queue"]:
            break
        trial_id = "s%03d" % (len(state["trials"]) + 1)
        for item in state["queue"]:
            item["wait"] += 1
        inflight = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
        if inflight:
            if inflight["id"] != trial_id:
                raise RuntimeError("Inflight trial ID conflicts with checkpoint")
            entry = inflight["entry"]
        else:
            tried = Counter(t["plan"][-1].rsplit("~", 1)[0] for t in state["trials"])
            families = Counter(t["plan"][-1].split("~", 1)[0] for t in state["trials"])
            state["queue"].sort(key=lambda item: (-priority(item, tried, families),
                                                   ";".join(item["plan"])))
            depth_round = (len(state["trials"]) + 1) % 10 == 0
            if depth_round:
                maximum_depth = max(map(lambda item: len(item["plan"]), state["queue"]))
                index = next((i for i, item in enumerate(state["queue"])
                              if len(item["plan"]) == maximum_depth), 0)
            else:
                index = 0
            entry = state["queue"][index]
            atomic_json(INFLIGHT, {"id": trial_id, "entry": entry})
        log = HERE / "logs" / (trial_id + ".log")
        compressed = HERE / "logs" / (trial_id + ".log.gz")
        receipt = HERE / "logs" / (trial_id + ".exit")
        if not receipt.exists():
            recover_inflight(trial_id, log, receipt)
            if not log.exists():
                runner = subprocess.Popen(["python3", str(HERE / "trial_runner.py"),
                                           trial_id, ";".join(entry["plan"])])
            else:
                runner = None
            while not receipt.exists():
                if runner is not None and runner.poll() is not None:
                    raise RuntimeError("Trial runner exited without receipt: " + trial_id)
                if runner is None:
                    recover_inflight(trial_id, log, receipt)
                    if not log.exists() and not receipt.exists():
                        runner = subprocess.Popen(["python3", str(HERE / "trial_runner.py"),
                                                   trial_id, ";".join(entry["plan"])])
                time.sleep(2)
        path = log if log.exists() else compressed
        if not path.exists():
            raise RuntimeError("Trial receipt exists without raw trace: " + trial_id)
        trace = parse_log(path)
        matched = strict(trace, entry["plan"])
        reached = target_outcome(trace, entry["plan"])
        cutoff = trace["shutdown_hook_line"]
        aborts = sorted({e["server"] for e in trace["RS_ABORT"]
                         if cutoff is None or e["line"] < cutoff})
        invalid = matched and len(aborts) >= 3
        retained = bool(reached["method"] or reached["progress"] or reached["guard"])
        guard = bool(reached["guard"])
        exec_file = HERE / "logs" / (trial_id + ".exec")
        exec_ok = exec_file.is_file() and exec_file.stat().st_size > 0
        admitted = matched and retained and not invalid and exec_ok
        effective = admitted and guard
        old = state["coverage_union"]
        new = old
        if admitted:
            state["coverage_execs"].append(str(exec_file))
            new = coverage([Path(item) for item in state["coverage_execs"]])
            state["coverage_union"] = new
        selectors = selector_events(trace)
        novelty = new["methods"] - old["methods"] + new["branches"] - old["branches"]
        observed_selectors = {item for _, item in selectors}
        new_io = len(observed_selectors - set(state["io_union"])) if admitted else 0
        if admitted:
            state["io_union"] = sorted(set(state["io_union"]) | observed_selectors)
        exit_code = int(receipt.read_text().strip())
        unexpected = matched and retained and not invalid and (exit_code == 124 or
            trace["junit"] is not None and trace["junit"]["failed"] > 0)
        trial = {"id": trial_id, "plan": entry["plan"], "strict": matched,
                 "unmatched_retries_before": entry.get("unmatched_retries", 0),
                 "applied_fault_events": len(trace["FAULT_APPLIED"]),
                 "target_method_after_fault": bool(reached["method"]),
                 "same_actor_retry_after_fault": bool(reached["progress"]),
                 "target_retained": retained, "postfault_guard": guard,
                 "exact_b7": bool(reached["b7"]), "invalid_cluster": bool(invalid),
                 "aborted_region_servers": aborts, "coverage_admitted": admitted,
                 "effective": effective, "new_branches_methods": novelty,
                 "new_io_selectors": new_io, "junit": trace["junit"],
                 "exit": exit_code, "elapsed_seconds": trace["elapsed_seconds"],
                 "review_candidate": bool(unexpected),
                 "log": str(compressed.relative_to(HERE.parent)),
                 "raw_log_sha256": raw_log_sha256(path),
                 "exec_sha256": sha256(exec_file) if exec_ok else None,
                 "disposition": ("unmatched" if not matched else
                    "invalid_cluster" if invalid else "target_lost" if not retained else
                    "timeout_requires_review" if exit_code == 124 else
                    "junit_failure_requires_review" if unexpected else
                    "exact_b7" if reached["b7"] else "guard_return" if guard else
                    "target_method_only")}
        if log.exists():
            with log.open("rb") as source, gzip.open(compressed, "wb", compresslevel=6) as out:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    out.write(block)
            if not compressed.is_file() or compressed.stat().st_size == 0:
                raise RuntimeError("Compressed trace missing: " + trial_id)
            trial["compressed_log_sha256"] = sha256(compressed)
            log.unlink()
        elif compressed.exists():
            trial["compressed_log_sha256"] = sha256(compressed)
        state["trials"].append(trial)
        state["queue"] = [item for item in state["queue"]
                          if item["plan"] != entry["plan"]]
        if not matched and entry.get("unmatched_retries", 0) < UNMATCHED_RETRY_LIMIT:
            retry = dict(entry)
            retry["unmatched_retries"] = entry.get("unmatched_retries", 0) + 1
            retry["wait"] = 0
            state["queue"].append(retry)
        if admitted and exit_code != 124:
            enqueue(state, entry["plan"], selectors, trace["FAULT_APPLIED"][-1]["line"],
                    novelty, trace["elapsed_seconds"])
        prune(state)
        publish(state)
        INFLIGHT.unlink(missing_ok=True)
        print("HBASE32U checkpoint", trial_id, trial["disposition"],
              "effective", sum(t["effective"] for t in state["trials"]),
              "queue", len(state["queue"]), flush=True)
    status = ("effective_budget_reached" if
              sum(t["effective"] for t in state["trials"]) >= state["effective_budget"] else
              "attempt_cap_reached" if len(state["trials"]) >= state["attempt_cap"] else
              "queue_exhausted")
    publish(state, status)


if __name__ == "__main__":
    main()
