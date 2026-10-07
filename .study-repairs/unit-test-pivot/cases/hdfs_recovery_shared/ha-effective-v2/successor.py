#!/usr/bin/env python3
"""Resume HA JUnit after a natural or verified unstarted-plan boundary.

The handoff retains every completed trial, queued sequence, and seen ID.  Its
only checkpoint changes are a recorded scheduler anchor, a cleared exhausted
attempt cap (320 -> 512), and the corresponding stop reason.  It keeps the
original trial evaluator and Java launch path, including the shared JVM lock.
"""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import audit_raw
import campaign


HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
INTENT = HERE / "successor-handoff-intent.json"
RECEIPT = HERE / "successor-handoff-receipt.json"
EARLY_RECEIPT = HERE / "early-quiesce-receipt.json"
EARLY_BACKUP = HERE / "checkpoint.pre-successor-early.json"
POLICY = "four_rpc_one_file_target_eligible_focus28_after_peer80"
MIN_FREE_BYTES = 10 * 1024**3


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def durable_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def lane(point: dict) -> str:
    marker = point["marker"]
    if marker.startswith("FAULT:HDFS_FILE:"):
        return "FILE"
    if marker.startswith(("FAULT:HDFS_RPC:", "FAULT:HADOOP_IPC:")):
        return "RPC"
    return "OTHER"


def choose(state: dict) -> int:
    """Choose four RPC slots and one file slot, favoring HDFS-28 after peer 80s."""
    completed = state["completed"]
    queue = state["queue"]
    counts = campaign.effective(state)
    deficit = {case for case in campaign.CASES
               if len(counts[case]) < state["goals"][case]}
    focus_28 = (len(counts["HDFS-29"]) >= campaign.BASE
                and len(counts["HDFS-30"]) >= campaign.BASE
                and "HDFS-28" in deficit)
    relevant = [i for i, item in enumerate(queue)
                if deficit.intersection(item["eligible"])]
    pool = relevant if relevant else list(range(len(queue)))
    ordinal = len(completed) - state["successor_scheduler"]["anchor_completed"]
    desired = "FILE" if ordinal % 5 == 4 else "RPC"
    selected_lane = [i for i in pool if lane(queue[i]["sequence"][-1]) == desired]
    if selected_lane:
        pool = selected_lane
    else:
        alternate = "RPC" if desired == "FILE" else "FILE"
        selected_lane = [i for i in pool if lane(queue[i]["sequence"][-1]) == alternate]
        if selected_lane:
            pool = selected_lane
    types = Counter(t["sequence"][-1]["faultType"] for t in completed)
    families = Counter(campaign.family(t["sequence"][-1]) for t in completed)
    return max(pool, key=lambda i: (
        int(focus_28 and "HDFS-28" in queue[i]["eligible"]),
        len(deficit.intersection(queue[i]["eligible"])),
        -types[queue[i]["sequence"][-1]["faultType"]],
        -families[campaign.family(queue[i]["sequence"][-1])],
        min(len(queue[i]["sequence"]), 6),
        queue[i]["priority"], -queue[i]["created"], -i))


def verify_last_raw(state: dict) -> None:
    if not state["completed"]:
        raise RuntimeError("handoff requires completed original trials")
    number = len(state["completed"])
    last = state["completed"][-1]
    directory = HERE / "runs" / ("trial-%04d" % number)
    if Path(last["run"]).resolve() != directory.resolve():
        raise RuntimeError("last completed trial path differs from checkpoint")
    manifest = json.loads((directory / "manifest.json").read_text())
    raw = (directory / "runtime_trace.jsonl").read_bytes()
    if (manifest.get("returncode") != last["junit_exit"] or
            manifest.get("elapsed_seconds") != last["elapsed_seconds"] or
            sha(raw) != last["raw_trace_sha256"]):
        raise RuntimeError("last completed raw trial differs from checkpoint")
    plan = [line.split("\t") for line in
            (directory / "fault-plan.tsv").read_text().splitlines()]
    expected = [[str(item[key]) for key in
                 ("marker", "siteId", "sourceKey", "occurrenceAddress",
                  "hitOrdinal", "faultType")] + [item["filePhase"]]
                for item in last["sequence"]]
    if plan != expected:
        raise RuntimeError("last completed plan differs from checkpoint")


def verify_boundary(state: dict, original: bytes, old_source_sha: str) -> str:
    if EARLY_RECEIPT.exists():
        receipt = json.loads(EARLY_RECEIPT.read_text())
        active = state.get("active")
        directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
        counts = {case: len(rows) for case, rows in campaign.effective(state).items()}
        absent = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")
        expected = {"schema": 1, "boundary": "unstarted_reserved_plan",
                    "old_runner_sha256": old_source_sha,
                    "checkpoint_sha256": sha(original),
                    "backup_sha256": sha(original),
                    "completed": len(state["completed"]),
                    "queue": len(state["queue"]), "seen": len(state["seen"]),
                    "active_plan": active["id"] if active else None,
                    "unstarted_trial_directory": str(directory),
                    "effective": counts, "junit_started": False}
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise RuntimeError("early boundary receipt disagrees with checkpoint/source")
        if (active is None or not EARLY_BACKUP.is_file()
                or EARLY_BACKUP.read_bytes() != original
                or counts["HDFS-29"] < campaign.BASE
                or counts["HDFS-30"] < campaign.BASE
                or counts["HDFS-28"] >= state["goals"]["HDFS-28"]
                or campaign.stop_reason(state) is not None
                or any((directory / name).exists() for name in absent)
                or campaign.child_java_started(directory)
                or campaign.previous_runner_alive(directory)):
            raise RuntimeError("early boundary is no longer an unstarted reserved trial")
        plan = directory / "fault-plan.tsv"
        expected_plan = "".join("\t".join(str(item[key]) for key in
                                           ("marker", "siteId", "sourceKey",
                                            "occurrenceAddress", "hitOrdinal", "faultType"))
                                + "\t" + item["filePhase"] + "\n"
                                for item in active["sequence"])
        if not plan.is_file() or plan.read_text() != expected_plan:
            raise RuntimeError("reserved plan differs from active checkpoint")
        return "early_unstarted_reserved_plan"
    log = HERE / "full-campaign.log"
    last_line = log.read_bytes()[-8192:].splitlines()[-1].decode(errors="replace")
    terminal = campaign.stop_reason(state)
    if terminal == "attempt_cap_inconclusive":
        expected = "terminal attempt_cap_inconclusive"
    elif terminal is None:
        expected = "wall cap reached; resume this checkpoint"
    else:
        raise RuntimeError("old controller ended with a non-resumable outcome")
    if last_line != expected:
        raise RuntimeError("old controller has no matching natural-boundary log")
    return "natural"


def migrated(state: dict, boundary: str) -> dict:
    if state.get("schema") != 2 or tuple(state.get("cases", ())) != campaign.CASES:
        raise RuntimeError("unexpected campaign checkpoint schema/cases")
    if boundary == "natural" and state["active"] is not None:
        raise RuntimeError("natural handoff requires an inactive checkpoint")
    if boundary == "early_unstarted_reserved_plan" and state["active"] is None:
        raise RuntimeError("early handoff requires a reserved active plan")
    if not state["queue"] and state["active"] is None:
        raise RuntimeError("no queued sequences left for successor")
    if state.get("successor_scheduler"):
        raise RuntimeError("successor scheduler already installed")
    terminal = campaign.stop_reason(state)
    if terminal in ("candidate_requires_replay_and_source_review",
                    "effective_budget_met_pending_independent_audit"):
        raise RuntimeError("candidate or completed budget requires review")
    if terminal == "attempt_cap_inconclusive" and state["attempt_cap"] != 320:
        raise RuntimeError("no authorized attempt-cap extension remains")
    out = json.loads(json.dumps(state))
    out["successor_scheduler"] = {"policy": POLICY,
                                  "anchor_completed": len(state["completed"]),
                                  "rpc_slots_per_five": 4,
                                  "file_slots_per_five": 1}
    if terminal == "attempt_cap_inconclusive":
        out["attempt_cap"] = 512
        out["stop_reason"] = None
    if (out["completed"] != state["completed"] or out["queue"] != state["queue"]
            or out["seen"] != state["seen"] or out["active"] != state["active"]):
        raise RuntimeError("handoff would alter completed/queue/seen/active")
    return out


def handoff(expected_old_sha: str) -> dict:
    old_source_sha = sha((HERE / "campaign.py").read_bytes())
    if old_source_sha != expected_old_sha:
        raise RuntimeError("original runner source SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        anchor = receipt["completed_before_after"][0]
        if (receipt["old_runner_sha256"] != old_source_sha or
                receipt["successor_sha256"] != sha(Path(__file__).read_bytes()) or
                state.get("successor_scheduler", {}).get("policy") != POLICY or
                state["successor_scheduler"]["anchor_completed"] != anchor or
                len(state["completed"]) < anchor or
                sha(encoded(state["completed"][:anchor])) !=
                receipt["completed_prefix_sha256"] or
                state["attempt_cap"] < receipt["new_attempt_cap"]):
            raise RuntimeError("existing handoff receipt conflicts with checkpoint")
        return receipt
    if INTENT.exists():
        intent = json.loads(INTENT.read_text())
        if (intent["old_runner_sha256"] != old_source_sha or
                intent["successor_sha256"] != sha(Path(__file__).read_bytes())):
            raise RuntimeError("pending handoff intent has different source SHA")
        current_sha = sha(STATE.read_bytes())
        if current_sha == intent["new_checkpoint_sha256"]:
            durable_json(RECEIPT, intent)
            return intent
        if current_sha != intent["old_checkpoint_sha256"]:
            raise RuntimeError("pending handoff intent conflicts with checkpoint")
    else:
        intent = None
    original = STATE.read_bytes()
    state = json.loads(original)
    verify_last_raw(state)
    boundary = verify_boundary(state, original, old_source_sha)
    if audit_raw.main() != 0:
        raise RuntimeError("independent raw audit rejected old checkpoint")
    raw_audit = HERE / "raw-audit.json"
    audit = json.loads(raw_audit.read_text())
    if (audit["checkpoint_sha256"] != sha(original) or audit["errors"] or
            audit["completed_attempts"] != len(state["completed"])):
        raise RuntimeError("independent raw audit receipt differs from old checkpoint")
    changed = migrated(state, boundary)
    new_bytes = encoded(changed)
    receipt = {"schema": 1, "policy": POLICY, "boundary": boundary,
               "created_at_utc": campaign.utc(),
               "old_runner_sha256": old_source_sha,
               "successor_sha256": sha(Path(__file__).read_bytes()),
               "old_checkpoint_sha256": sha(original),
               "new_checkpoint_sha256": sha(new_bytes),
               "completed_before_after": [len(state["completed"]),
                                          len(changed["completed"])],
               "queue_before_after": [len(state["queue"]), len(changed["queue"])],
               "seen_before_after": [len(state["seen"]), len(changed["seen"])],
               "active_before_after": [state["active"], changed["active"]],
               "old_attempt_cap": state["attempt_cap"],
               "new_attempt_cap": changed["attempt_cap"],
               "completed_prefix_sha256": sha(encoded(state["completed"])),
               "independent_raw_audit_sha256": sha(raw_audit.read_bytes()),
               "last_trial_trace_sha256": state["completed"][-1]["raw_trace_sha256"],
               "early_backup_sha256": sha(EARLY_BACKUP.read_bytes()) if
               boundary == "early_unstarted_reserved_plan" else None}
    if intent is not None:
        if {k: v for k, v in receipt.items() if k != "created_at_utc"} != {
                k: v for k, v in intent.items() if k != "created_at_utc"}:
            raise RuntimeError("pending handoff intent does not match recomputed state")
        receipt = intent
    else:
        durable_json(INTENT, receipt)
    durable_json(STATE, changed)
    if sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("handoff checkpoint SHA mismatch after replace")
    durable_json(RECEIPT, receipt)
    return receipt


def run(args: argparse.Namespace) -> None:
    with campaign.LOCK.open("a+") as lock:
        # The original controller holds this lock for its entire lifetime.
        # No state is read or mutated until the old controller has released it.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff(args.expected_old_sha256)
        campaign.MIN_FREE_BYTES = MIN_FREE_BYTES
        campaign.choose = choose
        state = json.loads(STATE.read_text())
        if state["successor_scheduler"]["policy"] != POLICY:
            raise RuntimeError("checkpoint lacks expected successor policy")
        campaign.write_summary(state)
        deadline = time.monotonic() + args.wall_seconds
        print(json.dumps({"handoff": receipt, "min_free_gib": 10,
                          "max_java_before_start": campaign.MAX_JAVA_BEFORE_START,
                          "shared_start_lock": str(campaign.START_LOCK)},
                         sort_keys=True), flush=True)
        while time.monotonic() < deadline:
            reason = campaign.stop_reason(state)
            if reason:
                state["stop_reason"] = reason
                campaign.atomic_json(STATE, state)
                campaign.write_summary(state)
                print("terminal " + reason, flush=True)
                return
            if not campaign.run_trial(state):
                time.sleep(min(args.poll_seconds,
                               max(0, deadline - time.monotonic())))
        print("successor wall cap reached; resume this checkpoint", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--expected-old-sha256", required=True)
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        print(json.dumps({"old_source_sha256": sha((HERE / "campaign.py").read_bytes()),
                          "expected_old_sha256": args.expected_old_sha256,
                          "successor_sha256": sha(Path(__file__).read_bytes()),
                          "checkpoint": campaign.preview(),
                          "free_gib": round(shutil.disk_usage(HERE).free / 1024**3, 2)},
                         sort_keys=True))
    elif args.run:
        run(args)
    else:
        parser.error("choose --preview or --run")


if __name__ == "__main__":
    main()
