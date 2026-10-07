#!/usr/bin/env python3
"""Resumable QJM actor-V2 coverage/I/O fault campaign for one original JUnit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from build_offline import HERE
from strict_receipt import RPC, SITES, actor, audit

FIELDS = ("marker", "siteId", "sourceKey", "hitOrdinal", "faultType")
METHOD = {"07": "testRecoverAfterIncompleteRecovery",
          "09": "testSingleWriter", "10": "testSingleWriter"}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atom(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def events(path: Path) -> list[dict]:
    return ([json.loads(line) for line in path.read_text().splitlines() if line]
            if path.is_file() else [])


def coverage(run: Path) -> dict[str, set[str]]:
    return {key: set((run / f"covered_{key}.txt").read_text().splitlines())
            if (run / f"covered_{key}.txt").is_file() else set()
            for key in ("probes", "methods", "branch_counts", "lines")}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_errors(run: Path, case: str, manifest: dict,
                    calibration: dict) -> list[str]:
    errors = []
    trace = run / "runtime_trace.jsonl"
    jacoco = run / "jacoco.exec"
    plan = run.parent / "campaign-v2/plans" / (run.name + ".tsv")
    if (manifest.get("case_id") != f"HDFS-{case}" or
            manifest.get("test") !=
            "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" + METHOD[case]):
        errors.append("wrong original JUnit or case")
    for label, path in (("plan", plan), ("trace", trace), ("jacoco", jacoco)):
        if not path.is_file() or not path.stat().st_size or \
                manifest.get(label + "_sha256") != sha(path):
            errors.append(f"missing or changed {label} raw artifact")
    for field in ("overlay_probe_sha256", "overlay_client_sha256"):
        if manifest.get(field) != calibration["seeds"][0][field]:
            errors.append(f"V2 build identity changed: {field}")
    feedback = manifest.get("coverage_sha256") or {}
    for kind in ("probes", "methods", "branch_counts", "lines"):
        path = run / f"covered_{kind}.txt"
        if (not path.is_file() or not path.stat().st_size or
                feedback.get(kind) != sha(path)):
            errors.append(f"missing or changed production {kind} feedback")
    return errors


def family(row: dict) -> str:
    return "\t".join(str(row[key]) for key in FIELDS[:3])


def identity(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:20]


def point(row: dict, fault: str) -> dict:
    return {key: row[key] for key in FIELDS[:-1]} | {"faultType": fault}


def observed(row: dict) -> bool:
    return (row.get("event") == "FAULT_POINT_OBSERVED" and
            row.get("marker", "").startswith("FAULT:HDFS_QJM_") and
            actor(row.get("sourceKey")) is not None)


def options(row: dict) -> tuple[str, ...]:
    return (("IOException", "EOFException", "SocketTimeoutException")
            if row["marker"] == RPC else ("IOException", "FileNotFoundException"))


def target_after(trace: list[dict], case: str, key: str, after: int) -> bool:
    return any(event.get("event") == "TARGET_CHECK" and
               event.get("siteId") == SITES[case] and
               event.get("journalNode") == key and
               event.get("journalId") == "test-journal" and
               event.get("seq", -1) > after for event in trace)


def enqueue(state: dict, sequence: list[dict], reason: str, priority: int) -> None:
    token = identity(sequence)
    if token not in state["seen"]:
        state["seen"].append(token)
        state["queue"].append({"id": token, "sequence": sequence,
                               "target_actor": actor(sequence[-1]["sourceKey"]),
                               "reason": reason, "priority": priority,
                               "queued_after": len(state["completed"])})


def initialize(case: str, root: Path, checkpoint: Path) -> dict:
    if checkpoint.is_file():
        state = json.loads(checkpoint.read_text())
        if state.get("case") != f"HDFS-{case}" or state.get("version") != 2:
            raise RuntimeError("checkpoint case/version mismatch")
        return state
    calibration = json.loads((root / "healthy-calibration.json").read_text())
    if (not calibration.get("pass") or calibration.get("case") != f"HDFS-{case}" or
            calibration.get("original_junit_seeds") != 2):
        raise RuntimeError("two V2 original JUnit healthy seeds not calibrated")
    state = {"case": f"HDFS-{case}", "version": 2, "status": "running",
             "started_at_utc": utc(), "legacy_trials_imported": 0,
             "budget": {"effective": 80, "max_faults": 8, "attempt_cap": 320,
                        "extension_effective": 128, "extension_max_faults": 10},
             "queue": [], "current": None, "completed": [], "seen": [],
             "coverage_union": {key: [] for key in
                                ("probes", "methods", "branch_counts", "lines")},
             "io_union": []}
    for name in ("healthy-a", "healthy-b"):
        run = root / name
        trace = events(run / "runtime_trace.jsonl")
        if not trace:
            raise RuntimeError(f"missing V2 healthy trace: {name}")
        for key, values in coverage(run).items():
            state["coverage_union"][key] = sorted(set(state["coverage_union"][key]) |
                                                   values)
        for event in trace:
            if not observed(event):
                continue
            key = actor(event["sourceKey"])
            if not target_after(trace, case, key, event["seq"]):
                continue
            state["io_union"] = sorted(set(state["io_union"]) | {family(event)})
            for fault in options(event):
                enqueue(state, [point(event, fault)],
                        f"observed {name} seq {event['seq']}",
                        300 if event["marker"] == RPC else 240)
    if not state["queue"]:
        raise RuntimeError("no actor-bound I/O preceding the exact target")
    atom(checkpoint, state)
    return state


def choose(state: dict) -> dict:
    if not state["queue"]:
        raise RuntimeError("empty fault queue")
    tested = {}
    for row in state["completed"]:
        key = family(row["sequence"][-1])
        tested[key] = tested.get(key, 0) + 1
    now = len(state["completed"])
    index = max(range(len(state["queue"])), key=lambda i: (
        state["queue"][i]["priority"] +
        16 * min(len(state["queue"][i]["sequence"]), 6) +
        min(now - state["queue"][i]["queued_after"], 64) -
        18 * tested.get(family(state["queue"][i]["sequence"][-1]), 0),
        -state["queue"][i]["queued_after"], -i))
    return state["queue"].pop(index)


def mutate(state: dict, row: dict, trace: list[dict], case: str) -> None:
    if not row["effective"] or len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    lower = row["receipt"]["last_fault_seq"]
    candidates = [event for event in trace if observed(event) and
                  event["seq"] > lower and
                  target_after(trace, case, actor(event["sourceKey"]), event["seq"])]
    used = {family(p) for p in row["sequence"]}
    candidates.sort(key=lambda e: (family(e) in used, -e["seq"]))
    chosen, counts = [], {}
    for event in candidates:
        key = family(event)
        if counts.get(key, 0) >= 2:
            continue
        chosen.append(event)
        counts[key] = counts.get(key, 0) + 1
        if len(chosen) >= 8:
            break
    gain = row["new_coverage_method_branch"] + row["new_io_families"]
    for event in chosen:
        for fault in options(event):
            sequence = row["sequence"] + [point(event, fault)]
            enqueue(state, sequence, f"mutated {row['run']} seq {event['seq']}",
                    180 + min(gain, 20) * 4 + 18 * len(sequence))


def analyze_run(state: dict, item: dict, run: Path, case: str) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    trace = events(run / "runtime_trace.jsonl")
    plan = [[str(p[key]) for key in FIELDS[:-1]] + ["pending", p["faultType"]]
            for p in item["sequence"]]
    receipt = audit(trace, plan, case, item["target_actor"])
    calibration = json.loads((run.parent / "healthy-calibration.json").read_text())
    evidence = evidence_errors(run, case, manifest, calibration)
    if evidence:
        receipt["pass"] = False
        receipt["errors"].extend(evidence)
    current = coverage(run)
    gains = {key: sorted(values - set(state["coverage_union"][key]))
             if receipt["pass"] else [] for key, values in current.items()}
    new_io = sorted({family(e) for e in trace if observed(e)} -
                    set(state["io_union"])) if receipt["pass"] else []
    # The original JUnit may tolerate a failed JournalNode and still pass.
    # A post-fault target exception remains a candidate observation either way.
    candidate = receipt["pass"] and receipt["post_fault_target_throws"] > 0
    return {"run": run.name, "id": item["id"], "sequence": item["sequence"],
            "target_actor": item["target_actor"], "reason": item["reason"],
            "receipt": receipt, "effective": receipt["pass"],
            "junit_returncode": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "new_coverage_ids": gains,
            "new_coverage_method_branch": len(gains["methods"]) +
                                          len(gains["branch_counts"]),
            "new_io_family_ids": new_io, "new_io_families": len(new_io),
            "candidate": candidate,
            "bug_mark": "candidate" if candidate else "none",
            "completed_at_utc": utc()}


def finish(state: dict, item: dict, root: Path, checkpoint: Path,
           case: str, run_id: str) -> dict:
    run = root / run_id
    saved = run / "trial-result.json"
    if saved.is_file():
        row = json.loads(saved.read_text())
        if row["id"] != item["id"] or row["run"] != run_id:
            raise RuntimeError("immutable trial-result differs from current plan")
    else:
        row = analyze_run(state, item, run, case)
        atom(saved, row)
    if row["effective"]:
        for key in state["coverage_union"]:
            state["coverage_union"][key] = sorted(set(state["coverage_union"][key]) |
                                                   coverage(run)[key])
        state["io_union"] = sorted(set(state["io_union"]) |
                                   set(row["new_io_family_ids"]))
    state["completed"].append(row)
    mutate(state, row, events(run / "runtime_trace.jsonl"), case)
    state["current"] = None
    accepted = [r for r in state["completed"] if r["effective"]]
    if len(accepted) >= 80 and state["budget"]["effective"] == 80:
        if any(r["new_coverage_method_branch"] or r["new_io_families"]
               for r in accepted[-8:]):
            state["budget"].update(effective=128, max_faults=10, attempt_cap=512)
        else:
            state["status"] = "budget_complete_80"
    if len(accepted) >= state["budget"]["effective"]:
        state["status"] = "budget_complete_" + str(state["budget"]["effective"])
    elif len(state["completed"]) >= state["budget"]["attempt_cap"]:
        state["status"] = "attempt_cap"
    elif not state["queue"]:
        state["status"] = "queue_exhausted"
    atom(checkpoint, state)
    return row


def step(state: dict, root: Path, checkpoint: Path, case: str) -> dict | None:
    if state["status"] != "running":
        return None
    if state["current"] is None:
        state["current"] = choose(state)
        state["current"]["attempt"] = 0
        atom(checkpoint, state)
    item = state["current"]
    if "run_id" in item:
        run_id = item["run_id"]
        if (root / run_id / "manifest.json").is_file():
            return finish(state, item, root, checkpoint, case, run_id)
        pid_file = root / run_id / "jvm.pid"
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text().strip())
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
            except (ValueError, OSError):
                command = b""
            if str(root / run_id / "runtime_trace.jsonl").encode() in command:
                raise RuntimeError(f"previous JUnit is still live: PID {pid}")
        item.pop("run_id")  # preserve interrupted raw folder; assign fresh ID
    item["attempt"] += 1
    run_id = f"trial-{len(state['completed']) + 1:04d}-attempt-{item['attempt']:02d}"
    plan_path = root / "campaign-v2/plans" / (run_id + ".tsv")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    if plan_path.exists() or (root / run_id).exists():
        raise RuntimeError(f"immutable run ID collision: {run_id}")
    plan_path.write_text("".join("\t".join(str(p[key]) for key in FIELDS[:-1]) +
                                 "\tpending\t" + p["faultType"] + "\n"
                                 for p in item["sequence"]))
    item["run_id"] = run_id
    atom(checkpoint, state)
    subprocess.run([sys.executable, str(HERE / "run_v2.py"), "--case", case,
                    "--name", run_id, "--plan", str(plan_path)], check=True)
    return finish(state, item, root, checkpoint, case, run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=METHOD, required=True)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--once", type=int, default=0,
                        help="at most N selected plans; N=0 starts no JUnit")
    parser.add_argument("--max-existing-jvms", type=int, default=4)
    parser.add_argument("--min-disk-gib", type=int, default=8)
    parser.add_argument("--wait-for-resources", action="store_true",
                        help="stay in tmux and retry resource gate at a JUnit boundary")
    args = parser.parse_args()
    if args.once < 0 or args.max_existing_jvms < 0 or args.min_disk_gib < 0:
        parser.error("run and resource limits must be nonnegative")
    root = HERE / "evidence" / f"HDFS-{args.case}"
    checkpoint = root / "campaign-v2/checkpoint.json"
    lock_path = root / "campaign-v2/lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = initialize(args.case, root, checkpoint)
        if args.init or args.once == 0:
            print(json.dumps({"case": state["case"], "status": state["status"],
                "completed": len(state["completed"]),
                "effective": sum(r["effective"] for r in state["completed"]),
                "queued": len(state["queue"])}))
            return
        selected = 0
        while selected < args.once:
            if (root / "campaign-v2/PAUSE").exists():
                break
            java = subprocess.run(["pgrep", "-x", "java"], capture_output=True,
                                  text=True, check=False)
            active_jvms = len(java.stdout.splitlines())
            free_gib = shutil.disk_usage(root).free / (1024 ** 3)
            if (active_jvms > args.max_existing_jvms or
                    free_gib < args.min_disk_gib):
                print(json.dumps({"status": "resource_guard_wait",
                    "active_jvms": active_jvms, "free_gib": round(free_gib, 2)}),
                    flush=True)
                if not args.wait_for_resources:
                    break
                time.sleep(15)
                continue
            row = step(state, root, checkpoint, args.case)
            if row is None:
                break
            selected += 1
            print(json.dumps({"run": row["run"], "effective": row["effective"],
                              "seconds": row["elapsed_seconds"],
                              "candidate": row["candidate"],
                              "status": state["status"]}), flush=True)


if __name__ == "__main__":
    main()
