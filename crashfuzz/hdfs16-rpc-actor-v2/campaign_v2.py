#!/usr/bin/env python3
"""Fresh HDFS-16 role-aware, coverage/I/O-guided original-JUnit campaign."""
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
from calibrate_v2 import SITE, context, family, read_events
from run_v2 import TEST
from strict_receipt import audit

FIELDS = ("marker", "api", "senderRole", "ordinal", "exception")
KINDS = ("PROBE", "METHOD", "BRANCH_UNIT")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atom(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temp.open("w") as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def coverage(run: Path) -> dict[str, set[str]]:
    path = run / "coverage.tsv"
    lines = path.read_text().splitlines() if path.is_file() else []
    return {kind: {line for line in lines if line.startswith(kind + "\t")}
            for kind in KINDS}


def relevant(row: dict) -> bool:
    return (row.get("event") == "IO_OBSERVED" and
            ((row.get("marker") == "RPC_RESPONSE" and
              row.get("senderRole") in ("dn0", "dn1") and
              row.get("senderActor", "").startswith("dn:") and
              row.get("peerPort", -1) > 0) or
             (row.get("marker") == "FILE_FLUSH" and
              row.get("senderRole") == "nn-editlog" and
              row.get("senderActor") == "nn-editlog" and
              row.get("api", "").endswith(":durable"))))


def next_context(trace: list[dict], after: int) -> dict | None:
    guards = [row for row in trace if row.get("event") == "TARGET_GUARD"
              and row.get("site") == SITE and row.get("seq", -1) > after
              and row.get("caller") in ("BlockManager.updateLastBlock",
                                        "BlockInfo.commitBlock")]
    return context(min(guards, key=lambda row: row["seq"])) if guards else None


def options(row: dict) -> tuple[str, ...]:
    return (("IOException", "EOFException", "SocketTimeoutException")
            if row["marker"] == "RPC_RESPONSE" else ("IOException",))


def point(row: dict, exception: str) -> dict:
    return {key: row[key] for key in FIELDS[:-1]} | {"exception": exception}


def identity(sequence: list[dict], target: dict) -> str:
    raw = json.dumps({"sequence": sequence, "target": target}, sort_keys=True,
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def enqueue(state: dict, sequence: list[dict], target: dict,
            reason: str, priority: int) -> None:
    token = identity(sequence, target)
    if token not in state["seen"]:
        state["seen"].append(token)
        state["queue"].append({"id": token, "sequence": sequence,
                               "target_context": target, "reason": reason,
                               "priority": priority,
                               "queued_after": len(state["completed"])})


def initialize(root: Path, checkpoint: Path) -> dict:
    if checkpoint.is_file():
        state = json.loads(checkpoint.read_text())
        if state.get("case") != "HDFS-16" or state.get("version") != 2:
            raise RuntimeError("wrong actor-V2 checkpoint")
        return state
    calibration = json.loads((root / "healthy-calibration.json").read_text())
    if (not calibration.get("pass") or calibration.get("case") != "HDFS-16" or
            calibration.get("original_junit_seeds") != 2 or
            calibration.get("legacy_trials_imported") != 0):
        raise RuntimeError("two fresh V2 original-JUnit healthy seeds required")
    if not calibration.get("shared_target_contexts") or not calibration.get("shared_io_families"):
        raise RuntimeError("healthy seeds lack a common original-test phase/I/O family")
    state = {"case": "HDFS-16", "version": 2, "status": "running",
             "started_at_utc": datetime.now(timezone.utc).isoformat(),
             "legacy_trials_imported": 0,
             "budget": {"effective": 80, "max_faults": 8, "attempt_cap": 320,
                        "extension_effective": 128, "extension_max_faults": 10},
             "queue": [], "current": None, "completed": [], "seen": [],
             "coverage_union": {key: [] for key in KINDS}, "io_union": []}
    for seed in ("healthy-a", "healthy-b"):
        run = root / seed
        trace = read_events(run / "runtime_trace.jsonl")
        for key, values in coverage(run).items():
            state["coverage_union"][key] = sorted(set(state["coverage_union"][key]) | values)
        for row in trace:
            if not relevant(row):
                continue
            target = next_context(trace, row["seq"])
            if target is None:
                continue
            state["io_union"] = sorted(set(state["io_union"]) | {family(row)})
            for exception in options(row):
                enqueue(state, [point(row, exception)], target,
                        f"observed {seed} seq {row['seq']}",
                        300 if row["marker"] == "RPC_RESPONSE" else 220)
    if not state["queue"]:
        raise RuntimeError("no role-bound I/O preceding exact target")
    atom(checkpoint, state)
    return state


def choose(state: dict) -> dict:
    tested = {}
    for row in state["completed"]:
        key = "\t".join(str(row["sequence"][-1][field]) for field in FIELDS[:3])
        tested[key] = tested.get(key, 0) + 1
    now = len(state["completed"])
    index = max(range(len(state["queue"])), key=lambda i: (
        state["queue"][i]["priority"] +
        18 * min(len(state["queue"][i]["sequence"]), 6) +
        min(now - state["queue"][i]["queued_after"], 64) -
        20 * tested.get("\t".join(str(state["queue"][i]["sequence"][-1][field])
                                   for field in FIELDS[:3]), 0), -i))
    return state["queue"].pop(index)


def evidence_errors(run: Path, manifest: dict, calibration: dict) -> list[str]:
    errors = []
    if manifest.get("case_id") != "HDFS-16" or manifest.get("test") != TEST:
        errors.append("wrong original JUnit/case")
    for label, path in (("plan", run.parent / "campaign-v2/plans" / (run.name + ".tsv")),
                        ("trace", run / "runtime_trace.jsonl"),
                        ("jacoco", run / "jacoco.exec"),
                        ("coverage", run / "coverage.tsv")):
        if (not path.is_file() or not path.stat().st_size or
                manifest.get(label + "_sha256") != sha(path)):
            errors.append(f"missing/changed {label} raw artifact")
    if manifest.get("overlay_sha256") != calibration["seeds"][0]["overlay_sha256"]:
        errors.append("actor-V2 overlay changed since healthy calibration")
    if any(not coverage(run)[kind] for kind in KINDS):
        errors.append("production JaCoCo feedback incomplete")
    return errors


def analyze(state: dict, item: dict, run: Path, root: Path) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    trace = read_events(run / "runtime_trace.jsonl")
    plan = [[str(step[field]) for field in FIELDS] for step in item["sequence"]]
    receipt = audit(trace, plan, item["target_context"])
    calibration = json.loads((root / "healthy-calibration.json").read_text())
    evidence = evidence_errors(run, manifest, calibration)
    if evidence:
        receipt["pass"] = False
        receipt["errors"].extend(evidence)
    now = coverage(run)
    gains = {kind: sorted(values - set(state["coverage_union"][kind]))
             if receipt["pass"] else [] for kind, values in now.items()}
    new_io = (sorted({family(row) for row in trace if relevant(row) and
                      next_context(trace, row["seq"]) is not None} -
                     set(state["io_union"])) if receipt["pass"] else [])
    candidate = (receipt["pass"] and
                 receipt["same_context_postfault_exceptions"] > 0 and
                 manifest["returncode"] != 0)
    return {"run": run.name, "id": item["id"], "sequence": item["sequence"],
            "target_context": item["target_context"], "reason": item["reason"],
            "receipt": receipt, "effective": receipt["pass"],
            "junit_returncode": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "new_coverage_ids": gains,
            "new_coverage_method_branch": len(gains["METHOD"]) + len(gains["BRANCH_UNIT"]),
            "new_io_family_ids": new_io, "new_io_families": len(new_io),
            "candidate": candidate, "bug_mark": "candidate" if candidate else "none",
            "completed_at_utc": datetime.now(timezone.utc).isoformat()}


def mutate(state: dict, row: dict, trace: list[dict]) -> None:
    if not row["effective"] or len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    last = row["receipt"]["last_fault_seq"]
    candidates = [event for event in trace if relevant(event) and
                  event["seq"] > last and next_context(trace, event["seq"]) is not None]
    candidates.sort(key=lambda event: (family(event) not in row["new_io_family_ids"],
                                       -event["seq"]))
    chosen = set()
    gain = row["new_coverage_method_branch"] + row["new_io_families"]
    for event in candidates:
        key = (family(event), event["ordinal"])
        if key in chosen:
            continue
        chosen.add(key)
        target = next_context(trace, event["seq"])
        for exception in options(event):
            enqueue(state, row["sequence"] + [point(event, exception)], target,
                    f"mutated {row['run']} seq {event['seq']}",
                    180 + 4 * min(gain, 20) + 18 * (len(row["sequence"]) + 1))
        if len(chosen) >= 8:
            break


def finish(state: dict, item: dict, root: Path, checkpoint: Path,
           run_id: str) -> dict:
    run = root / run_id
    saved = run / "trial-result.json"
    if saved.is_file():
        row = json.loads(saved.read_text())
        if row["id"] != item["id"] or row["run"] != run_id:
            raise RuntimeError("immutable trial result/selected plan differ")
    else:
        row = analyze(state, item, run, root)
        atom(saved, row)
    if row["effective"]:
        now = coverage(run)
        for kind in KINDS:
            state["coverage_union"][kind] = sorted(set(state["coverage_union"][kind]) | now[kind])
        state["io_union"] = sorted(set(state["io_union"]) | set(row["new_io_family_ids"]))
    state["completed"].append(row)
    mutate(state, row, read_events(run / "runtime_trace.jsonl"))
    state["current"] = None
    accepted = [entry for entry in state["completed"] if entry["effective"]]
    if len(accepted) >= 80 and state["budget"]["effective"] == 80:
        if any(entry["new_coverage_method_branch"] or entry["new_io_families"]
               for entry in accepted[-8:]):
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


def step(state: dict, root: Path, checkpoint: Path) -> dict | None:
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
            return finish(state, item, root, checkpoint, run_id)
        pid_file = root / run_id / "jvm.pid"
        if pid_file.is_file():
            try:
                pid = int(pid_file.read_text().strip())
                command = Path(f"/proc/{pid}/cmdline").read_bytes()
            except (ValueError, OSError):
                command = b""
            if str(root / run_id / "runtime_trace.jsonl").encode() in command:
                raise RuntimeError(f"previous JUnit still live: PID {pid}")
        item.pop("run_id")
    item["attempt"] += 1
    run_id = f"trial-{len(state['completed']) + 1:04d}-attempt-{item['attempt']:02d}"
    plan_path = root / "campaign-v2/plans" / (run_id + ".tsv")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    if plan_path.exists() or (root / run_id).exists():
        raise RuntimeError("immutable run ID collision")
    plan_path.write_text("".join("\t".join(str(step[field]) for field in FIELDS) + "\n"
                                 for step in item["sequence"]))
    item["run_id"] = run_id
    atom(checkpoint, state)
    subprocess.run([sys.executable, str(HERE / "run_v2.py"), "--name", run_id,
                    "--plan", str(plan_path)], check=True)
    return finish(state, item, root, checkpoint, run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--once", type=int, default=0)
    parser.add_argument("--max-existing-jvms", type=int, default=4)
    parser.add_argument("--min-disk-gib", type=int, default=8)
    parser.add_argument("--wait-for-resources", action="store_true")
    args = parser.parse_args()
    if min(args.once, args.max_existing_jvms, args.min_disk_gib) < 0:
        parser.error("negative run/resource limit")
    root = HERE / "evidence"
    checkpoint = root / "campaign-v2/checkpoint.json"
    lock_path = root / "campaign-v2/lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = initialize(root, checkpoint)
        if args.init or args.once == 0:
            print(json.dumps({"status": state["status"],
                "completed": len(state["completed"]),
                "effective": sum(row["effective"] for row in state["completed"]),
                "queued": len(state["queue"])}))
            return
        selected = 0
        while selected < args.once:
            if (root / "campaign-v2/PAUSE").exists():
                break
            active = len(subprocess.run(["pgrep", "-x", "java"], capture_output=True,
                                        text=True).stdout.splitlines())
            free = shutil.disk_usage(root).free / 1024 ** 3
            if active > args.max_existing_jvms or free < args.min_disk_gib:
                print(json.dumps({"status": "resource_guard_wait", "jvms": active,
                    "free_gib": round(free, 2)}), flush=True)
                if not args.wait_for_resources:
                    break
                time.sleep(15)
                continue
            row = step(state, root, checkpoint)
            if row is None:
                break
            selected += 1
            print(json.dumps({"run": row["run"], "effective": row["effective"],
                              "seconds": row["elapsed_seconds"],
                              "candidate": row["candidate"],
                              "status": state["status"]}), flush=True)


if __name__ == "__main__":
    main()
