#!/usr/bin/env python3
"""Checkpointed, graph-free HDFS-39 V2 fault queue. Never imports old counts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from build_offline import HERE
from strict_receipt import audit

ROOT = HERE / "evidence"
STATE = ROOT / "campaign-v2/checkpoint.json"
LOCK = ROOT / "campaign-v2/lock"
KEYS = ("marker", "api", "endpoint", "ordinal", "exception")
TARGET = "FSDirAppendOp.appendFile:131"
FILE = "/testMultipleAppend/foo"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_events(path: Path) -> list[dict]:
    return ([json.loads(line) for line in path.read_text().splitlines() if line]
            if path.is_file() else [])


def coverage(path: Path) -> set[str]:
    return set(path.read_text().splitlines()) if path.is_file() else set()


def selector(event: dict, exception: str) -> dict:
    return {key: event[key] for key in KEYS[:-1]} | {"exception": exception}


def identity(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:20]


def family(event: dict) -> str:
    return "\t".join(str(event[key]) for key in ("marker", "api", "endpoint"))


def relevant(event: dict, block: int) -> bool:
    if event.get("event") != "IO_OBSERVED":
        return False
    api, marker = event.get("api", ""), event.get("marker", "")
    if marker in {"RPC_SEND", "RPC_RESPONSE_WAIT"}:
        if api.startswith("DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"):
            text = api.split("blocks=[", 1)[-1].split("]", 1)[0]
            return (str(block) in text.split(", ") and
                    event.get("endpoint", "").startswith("nn0<-dn") and
                    bool(event.get("sourceUuid")) and bool(event.get("blockPoolId")) and
                    event.get("peerPort", -1) > 0)
        return (api == "ClientNamenodeProtocolTranslatorPB.append[append:" + FILE + "]"
                and event.get("endpoint") == "nn0<-client"
                and event.get("peerPort", -1) > 0)
    return (marker == "FILE_FLUSH" and api == "editLog:durable"
            and event.get("endpoint") == "nnlocal")


def enqueue(state: dict, sequence: list[dict], reason: str, priority: int) -> None:
    token = identity(sequence)
    if token not in state["seen"]:
        state["seen"].append(token)
        state["queue"].append({"id": token, "sequence": sequence,
                               "reason": reason, "priority": priority,
                               "queued_after": len(state["completed"])})


def initialize() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text())
    calibration = json.loads((ROOT / "healthy-calibration.json").read_text())
    if not calibration.get("pass") or calibration.get("cluster_junit_seeds") != 2:
        raise RuntimeError("two unchanged original healthy seeds not calibrated")
    block = calibration["healthy"][0]["target_block_id"]
    state = {"case": "HDFS-39", "version": 2, "status": "running",
             "started_at_utc": utc(), "target": {"path": FILE, "block_id": block},
             "budget": {"effective": 80, "max_faults": 8, "attempt_cap": 160,
                        "extension_effective": 128, "extension_max_faults": 10},
             "legacy_effective_imported": 0, "queue": [], "current": None,
             "completed": [], "seen": [], "coverage_union": [], "io_union": []}
    for healthy_name in ("healthy-a", "healthy-b"):
        run = ROOT / healthy_name
        state["coverage_union"] = sorted(set(state["coverage_union"]) |
                                         coverage(run / "coverage.tsv"))
        events = read_events(run / "trace/runtime_trace.jsonl")
        last_guard = max(e["seq"] for e in events if e.get("event") == "TARGET_GUARD"
                         and e.get("site") == TARGET and e.get("path") == FILE
                         and e.get("blockId") == block)
        for event in events:
            if event.get("seq", 0) >= last_guard or not relevant(event, block):
                continue
            state["io_union"] = sorted(set(state["io_union"]) | {family(event)})
            for kind in (("IOException",) if event["marker"] == "FILE_FLUSH"
                         else ("IOException", "EOFException", "SocketTimeoutException")):
                rank = 300 if "blockReceivedAndDeleted" in event["api"] else 200
                enqueue(state, [selector(event, kind)],
                        f"observed {healthy_name} seq {event['seq']}", rank)
    if not state["queue"]:
        raise RuntimeError("healthy pair supplied no target-related actor-aware I/O")
    write_json(STATE, state)
    return state


def choose(state: dict) -> dict:
    round_number = len(state["completed"])
    families = {}
    for row in state["completed"]:
        key = family(row["sequence"][-1])
        families[key] = families.get(key, 0) + 1
    index = max(range(len(state["queue"])), key=lambda i: (
        state["queue"][i]["priority"] +
        min(round_number - state["queue"][i]["queued_after"], 64) +
        12 * min(len(state["queue"][i]["sequence"]), 6) -
        18 * families.get(family(state["queue"][i]["sequence"][-1]), 0),
        -state["queue"][i]["queued_after"], -i))
    return state["queue"].pop(index)


def mutate(state: dict, row: dict, events: list[dict]) -> None:
    if not row["effective"] or len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    last = row["receipt"]["last_fault_seq"]
    target = state["target"]
    guards = [e["seq"] for e in events if e.get("event") == "TARGET_GUARD"
              and e.get("site") == TARGET and e.get("path") == target["path"]
              and e.get("blockId") == target["block_id"] and e["seq"] > last]
    if not guards:
        return
    used = {family(point) for point in row["sequence"]}
    candidates = [e for e in events if last < e.get("seq", -1) < max(guards)
                  and relevant(e, target["block_id"])]
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
    for event in chosen:
        for kind in (("IOException",) if event["marker"] == "FILE_FLUSH"
                     else ("IOException", "EOFException", "SocketTimeoutException")):
            sequence = row["sequence"] + [selector(event, kind)]
            gain = row["new_coverage_method_branch"] + row["new_io_families"]
            enqueue(state, sequence, f"mutated {row['run']} seq {event['seq']}",
                    180 + min(gain, 20) * 4 + 16 * len(sequence))


def finalize(state: dict, item: dict, run_id: str) -> dict:
    run = ROOT / run_id
    manifest = json.loads((run / "manifest.json").read_text())
    if ((run / "jacoco.exec").is_file() and
            not (run / "coverage.tsv").is_file()):
        subprocess.run([sys.executable, str(HERE / "coverage_v2.py"),
                        "--name", run_id], check=True)
    events = read_events(run / "trace/runtime_trace.jsonl")
    saved = run / "trial-result.json"
    if saved.is_file():
        row = json.loads(saved.read_text())
        if row["id"] != item["id"] or row["run"] != run_id:
            raise RuntimeError("immutable trial-result mismatch on resume")
        state["coverage_union"] = sorted(set(state["coverage_union"]) |
                                         coverage(run / "coverage.tsv"))
        state["io_union"] = sorted(set(state["io_union"]) |
                                   set(row["new_io_family_ids"]))
    else:
        row = analyze_run(state, item, run_id, manifest, events)
        write_json(saved, row)
    state["completed"].append(row)
    mutate(state, row, events)
    state["current"] = None
    effective = [r for r in state["completed"] if r["effective"]]
    if len(effective) >= 80 and state["budget"]["effective"] == 80:
        last_eight = effective[-8:]
        if any(r["new_coverage_method_branch"] or r["new_io_families"]
               for r in last_eight):
            state["budget"].update(effective=128, max_faults=10, attempt_cap=256)
        else:
            state["status"] = "budget_complete_80"
    if len(effective) >= state["budget"]["effective"]:
        state["status"] = "budget_complete_" + str(state["budget"]["effective"])
    elif len(state["completed"]) >= state["budget"]["attempt_cap"]:
        state["status"] = "attempt_cap"
    elif not state["queue"]:
        state["status"] = "queue_exhausted"
    write_json(STATE, state)
    return row


def analyze_run(state: dict, item: dict, run_id: str,
                manifest: dict, events: list[dict]) -> dict:
    run = ROOT / run_id
    plan = [[str(point[key]) for key in KEYS] for point in item["sequence"]]
    receipt = audit(events, plan, state["target"])
    old_coverage = set(state["coverage_union"])
    current_coverage = coverage(run / "coverage.tsv")
    new_coverage = sorted(current_coverage - old_coverage) if receipt["pass"] else []
    current_io = {family(e) for e in events if relevant(e, state["target"]["block_id"])}
    old_io = set(state["io_union"])
    new_io = sorted(current_io - old_io) if receipt["pass"] else []
    if receipt["pass"]:
        state["coverage_union"] = sorted(old_coverage | current_coverage)
        state["io_union"] = sorted(old_io | current_io)
    candidate = (receipt["pass"] and receipt["postfault_target_exceptions"] > 0
                 and manifest["exit"] != 0)
    row = {"run": run_id, "sequence": item["sequence"], "id": item["id"],
           "reason": item["reason"], "receipt": receipt,
           "effective": receipt["pass"], "junit_exit": manifest["exit"],
           "elapsed_seconds": manifest["elapsed_seconds"],
           "new_coverage_ids": new_coverage,
           "new_coverage_method_branch": sum(v.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                                             for v in new_coverage),
           "new_io_families": len(new_io), "new_io_family_ids": new_io,
           "candidate": candidate,
           "bug_mark": "candidate" if candidate else "none",
           "completed_at_utc": utc()}
    return row


def step(state: dict) -> dict | None:
    if state["status"] != "running":
        return None
    if state["current"] is None:
        state["current"] = choose(state)
        state["current"]["attempt"] = 0
        write_json(STATE, state)
    item = state["current"]
    if "run_id" in item:
        run = ROOT / item["run_id"]
        if (run / "manifest.json").is_file():
            return finalize(state, item, item["run_id"])
        # The previous attempt was interrupted before its manifest. Preserve
        # the raw directory and choose a fresh immutable attempt ID.
        item.pop("run_id")
    item["attempt"] += 1
    trial = len(state["completed"]) + 1
    run_id = f"trial-{trial:04d}-attempt-{item['attempt']:02d}"
    plan = ROOT / "campaign-v2/plans" / (run_id + ".tsv")
    plan.parent.mkdir(parents=True, exist_ok=True)
    if plan.exists() or (ROOT / run_id).exists():
        raise RuntimeError(f"immutable run ID collision: {run_id}")
    plan.write_text("".join("\t".join(str(point[key]) for key in KEYS) + "\n"
                            for point in item["sequence"]))
    item["run_id"] = run_id
    write_json(STATE, state)
    subprocess.run([sys.executable, str(HERE / "run_original_v2.py"),
                    "--name", run_id, "--plan", str(plan)], check=True)
    if (ROOT / run_id / "jacoco.exec").is_file():
        subprocess.run([sys.executable, str(HERE / "coverage_v2.py"),
                        "--name", run_id], check=True)
    return finalize(state, item, run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--once", type=int, default=0,
                        help="run at most N selected plans; no JUnit with N=0")
    args = parser.parse_args()
    if args.once < 0:
        parser.error("--once must be nonnegative")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = initialize()
        if args.init or args.once == 0:
            print(json.dumps({"status": state["status"],
                              "completed": len(state["completed"]),
                              "effective": sum(r["effective"] for r in state["completed"]),
                              "queued": len(state["queue"])}))
            return
        for _ in range(args.once):
            row = step(state)
            if row is None:
                break
            print(json.dumps({"run": row["run"], "effective": row["effective"],
                              "seconds": row["elapsed_seconds"],
                              "candidate": row["candidate"],
                              "status": state["status"]}), flush=True)


if __name__ == "__main__":
    main()
