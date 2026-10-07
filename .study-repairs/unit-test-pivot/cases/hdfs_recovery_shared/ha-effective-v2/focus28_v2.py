#!/usr/bin/env python3
"""Versioned HDFS-28 queue focus after an audited HA controller boundary.

The input remains the released HA JUnit and its existing runtime-bound fault
queue.  Healthy traces supply a provable priority set; seen IDs are never
removed, so a tested plan is not rerun.  The existing four-RPC/one-file lane
is retained, as are all per-case effective goals and fault-depth limits.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import audit_raw
import campaign
import successor


HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
INTENT = HERE / "focus28-v2-handoff-intent.json"
RECEIPT = HERE / "focus28-v2-handoff-receipt.json"
SAFE_STOP = HERE / "focus28-v2-quiesce-receipt.json"
SAFE_BACKUP = HERE / "checkpoint.pre-focus28-v2.json"
POLICY = "healthy_early_same_root_one_fault_focus28_with_four_rpc_one_file"
MIN_FREE_BYTES = 10 * 1024**3
SOURCE_TEST = "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def healthy_early(state: dict, base: Path = HERE) -> dict[str, list[dict]]:
    """Return exact selector IDs backed by pre-HDFS-28 healthy RPC events."""
    if state.get("test") != SOURCE_TEST or len(state.get("healthy", ())) != 2:
        raise RuntimeError("unexpected original HA JUnit/healthy seed ledger")
    found: dict[str, list[dict]] = {}
    for index, name in enumerate(("healthy-a", "healthy-b")):
        directory = base / name
        manifest = json.loads((directory / "manifest.json").read_text())
        raw = (directory / "runtime_trace.jsonl").read_bytes()
        if (manifest.get("returncode") != 0 or manifest.get("instrumented") is not True
                or manifest.get("graphchecker_runtime_used") is not False
                or manifest.get("test") != SOURCE_TEST
                or sha(raw) != state["healthy"][index]["trace_sha256"]):
            raise RuntimeError("healthy JUnit identity/provenance changed: " + name)
        events = [json.loads(line) for line in raw.splitlines() if line]
        if (not any(row.get("event") == "CLUSTER_REGISTER" and
                    row.get("dataNodes") == 3 for row in events)
                or any(row.get("event") == "TARGET_THROW" for row in events)):
            raise RuntimeError("healthy HA cluster/target outcome changed: " + name)
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or not event.get("marker", "").startswith(
                        ("FAULT:HDFS_RPC:", "FAULT:HADOOP_IPC:"))
                    or not campaign.identity_verified(events, event)
                    or "HDFS-28" not in campaign.later_targets(event, events)):
                continue
            later = [row for row in events if row.get("event") == "TARGET_CHECK"
                     and row.get("caseId") == "HDFS-28"
                     and row.get("siteId") == campaign.SITES["HDFS-28"]
                     and row.get("seq", -1) > event["seq"]
                     and campaign.same_owner(event, row)]
            if not later:
                continue
            for fault in campaign.kinds(event):
                point = campaign.point(event, fault)
                ident = campaign.identity([point])
                found.setdefault(ident, []).append({
                    "seed": name, "io_seq": event["seq"],
                    "first_later_target_seq": min(row["seq"] for row in later),
                    "owner": campaign.origin(event), "recovery_root": campaign.root(event),
                    "block_id": event.get("blockId"), "recovery_id": event.get("recoveryId"),
                    "marker": point["marker"], "fault_type": fault})
    if not found:
        raise RuntimeError("no healthy pre-HDFS-28 actor-bound RPC selectors")
    return found


def candidate_counts(state: dict, canonical: dict) -> dict:
    seen = set(state["seen"])
    queue = {item["id"]: item for item in state["queue"]}
    completed = {item["id"] for item in state["completed"]}
    exact_tested = {item["id"] for item in state["completed"]
                    if item["exact_order_applied"]}
    active = {state["active"]["id"]} if state["active"] else set()
    if not set(canonical).issubset(seen):
        raise RuntimeError("healthy one-fault plan absent from original seen ledger")
    if set(canonical) - (set(queue) | completed | active):
        raise RuntimeError("seen healthy plan has no queued, active, or completed owner")
    if set(canonical) & set(queue) & exact_tested:
        raise RuntimeError("already exact-tested healthy plan was requeued")
    for ident in set(canonical) & set(queue):
        item = queue[ident]
        if len(item["sequence"]) != 1 or "HDFS-28" not in item["eligible"]:
            raise RuntimeError("healthy queue selector lost HDFS-28 eligibility")
    return {"canonical_total": len(canonical),
            "canonical_completed": len(set(canonical) & completed),
            "canonical_exact_tested": len(set(canonical) & exact_tested),
            "canonical_missed_attempted": len((set(canonical) & completed) - exact_tested),
            "canonical_queued": len(set(canonical) & set(queue)),
            "canonical_active": len(set(canonical) & active)}


def focus_needed(state: dict) -> bool:
    counts = {case: len(rows) for case, rows in campaign.effective(state).items()}
    return (counts["HDFS-28"] < state["goals"]["HDFS-28"] and
            (min(counts["HDFS-29"], counts["HDFS-30"]) >= campaign.BASE
             or min(counts["HDFS-29"], counts["HDFS-30"]) - counts["HDFS-28"] >= 10))


def choose(state: dict) -> int:
    """Keep the old lane schedule; prefer early one-fault HDFS-28 within it."""
    queue = state["queue"]
    fallback = successor.choose(state)
    if not focus_needed(state):
        return fallback
    deficit = {case for case in campaign.CASES
               if len(campaign.effective(state)[case]) < state["goals"][case]}
    relevant = [i for i, item in enumerate(queue) if deficit.intersection(item["eligible"])]
    pool = relevant if relevant else list(range(len(queue)))
    ordinal = len(state["completed"]) - state["successor_scheduler"]["anchor_completed"]
    wanted = "FILE" if ordinal % 5 == 4 else "RPC"
    lane_pool = [i for i in pool if successor.lane(queue[i]["sequence"][-1]) == wanted]
    if not lane_pool:
        other = "RPC" if wanted == "FILE" else "FILE"
        lane_pool = [i for i in pool if successor.lane(queue[i]["sequence"][-1]) == other]
    if not lane_pool:
        return fallback
    eligible = [i for i in lane_pool if "HDFS-28" in queue[i]["eligible"]]
    if not eligible:
        return fallback
    canonical = set(state["focus28_scheduler"]["canonical_ids"])
    early = [i for i in eligible if len(queue[i]["sequence"]) == 1]
    healthy = [i for i in early if queue[i]["id"] in canonical]
    chosen_pool = healthy or early or eligible
    subset = {**state, "queue": [queue[i] for i in chosen_pool]}
    return chosen_pool[successor.choose(subset)]


def verify_boundary(state: dict, original: bytes, old_sha: str) -> str:
    if SAFE_STOP.exists():
        receipt = json.loads(SAFE_STOP.read_text())
        active = state.get("active")
        trial = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
        plan = trial / "fault-plan.tsv"
        raw_audit = HERE / "raw-audit.json"
        counts = {case: len(rows) for case, rows in campaign.effective(state).items()}
        canonical = healthy_early(state)
        queued_early = sum("HDFS-28" in item["eligible"] and len(item["sequence"]) == 1
                           and successor.lane(item["sequence"][-1]) == "RPC"
                           for item in state["queue"])
        basis = {"effective": counts, "canonical": candidate_counts(state, canonical),
                 "queued_one_fault_28_rpc": queued_early,
                 "focus_gap": min(counts["HDFS-29"], counts["HDFS-30"]) - counts["HDFS-28"]}
        if (receipt.get("source_sha256") != old_sha
                or receipt.get("checkpoint_sha256") != sha(original)
                or not SAFE_BACKUP.is_file() or SAFE_BACKUP.read_bytes() != original
                or receipt.get("backup_sha256") != sha(original)
                or receipt.get("completed") != len(state["completed"])
                or receipt.get("active_plan") != (active["id"] if active else None)
                or receipt.get("trial_directory") != str(trial)
                or receipt.get("junit_started") is not False
                or receipt.get("basis") != basis or queued_early == 0
                or not focus_needed(state)
                or campaign.stop_reason(state) is not None
                or any((trial / name).exists() for name in
                       ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json"))
                or campaign.child_java_started(trial)
                or campaign.previous_runner_alive(trial)
                or not plan.is_file()
                or receipt.get("active_plan_sha256") != sha(plan.read_bytes())
                or not raw_audit.is_file()
                or receipt.get("raw_audit_sha256") != sha(raw_audit.read_bytes())):
            raise RuntimeError("focus28 safe-stop boundary is not an unstarted reserved trial")
        expected_plan = "".join("\t".join(str(item[key]) for key in
                                           ("marker", "siteId", "sourceKey",
                                            "occurrenceAddress", "hitOrdinal", "faultType"))
                                + "\t" + item["filePhase"] + "\n"
                                for item in active["sequence"])
        if plan.read_text() != expected_plan:
            raise RuntimeError("safe-stop plan differs from active checkpoint")
        return "safe_unstarted_reserved_plan"
    log = HERE / "successor-campaign.log"
    last = log.read_bytes()[-8192:].splitlines()[-1].decode(errors="replace")
    terminal = campaign.stop_reason(state)
    if terminal == "attempt_cap_inconclusive":
        expected = "terminal attempt_cap_inconclusive"
    elif terminal is None:
        expected = "successor wall cap reached; resume this checkpoint"
    else:
        raise RuntimeError("candidate/completed/queue-exhausted state needs separate review")
    if last != expected:
        raise RuntimeError("running predecessor has no natural-boundary log")
    if state["active"] is not None:
        trial = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
        if any((trial / name).exists() for name in
               ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")) or (
               campaign.child_java_started(trial) or campaign.previous_runner_alive(trial)):
            raise RuntimeError("natural boundary left a started trial")
        active = state["active"]
        plan = trial / "fault-plan.tsv"
        expected_plan = "".join("\t".join(str(item[key]) for key in
                                           ("marker", "siteId", "sourceKey",
                                            "occurrenceAddress", "hitOrdinal", "faultType"))
                                + "\t" + item["filePhase"] + "\n"
                                for item in active["sequence"])
        if not plan.is_file() or plan.read_text() != expected_plan:
            raise RuntimeError("natural stop reserved plan differs from active checkpoint")
        return "natural_unstarted_reserved_plan"
    return "natural"


def migrated(state: dict, canonical: dict, boundary: str) -> dict:
    if (state.get("schema") != 2 or tuple(state.get("cases", ())) != campaign.CASES
            or state.get("successor_scheduler", {}).get("policy") != successor.POLICY
            or state.get("focus28_scheduler")):
        raise RuntimeError("unexpected predecessor scheduler/schema")
    if boundary == "natural" and state["active"] is not None:
        raise RuntimeError("natural checkpoint contains active trial")
    if boundary.endswith("unstarted_reserved_plan") and state["active"] is None:
        raise RuntimeError("reserved-plan boundary lacks active trial")
    if not state["queue"] and state["active"] is None:
        raise RuntimeError("no remaining plan")
    reason = campaign.stop_reason(state)
    if reason in ("candidate_requires_replay_and_source_review",
                  "effective_budget_met_pending_independent_audit",
                  "queue_exhausted_inconclusive"):
        raise RuntimeError("predecessor is terminal or needs candidate review")
    if reason == "attempt_cap_inconclusive" and state["attempt_cap"] != 320:
        raise RuntimeError("no authorized attempt-cap extension remains")
    stats = candidate_counts(state, canonical)
    output = json.loads(json.dumps(state))
    output["focus28_scheduler"] = {
        "policy": POLICY, "anchor_completed": len(state["completed"]),
        "canonical_ids": sorted(canonical),
        "canonical_ids_sha256": sha("\n".join(sorted(canonical)).encode()),
        **stats, "rpc_slots_per_five": 4, "file_slots_per_five": 1,
        "focus_gap": 10,
        "healthy_trace_sha256": [entry["trace_sha256"] for entry in state["healthy"]]}
    if reason == "attempt_cap_inconclusive":
        output["attempt_cap"] = 512
        output["stop_reason"] = None
    if any(output[key] != state[key] for key in ("completed", "queue", "seen", "active")):
        raise RuntimeError("focus28 migration changed original ledger/queue/active")
    return output


def handoff(expected_old_sha: str) -> dict:
    old_sha = sha((HERE / "successor.py").read_bytes())
    if old_sha != expected_old_sha:
        raise RuntimeError("running predecessor source SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        if (receipt["old_source_sha256"] != old_sha
                or receipt["new_source_sha256"] != sha(Path(__file__).read_bytes())
                or state.get("focus28_scheduler", {}).get("policy") != POLICY
                or len(state["completed"]) < receipt["completed_before_after"][0]
                or sha(successor.encoded(state["completed"][:receipt["completed_before_after"][0]])) !=
                   receipt["completed_prefix_sha256"]):
            raise RuntimeError("existing focus28 handoff conflicts with checkpoint")
        return receipt
    if INTENT.exists():
        pending = json.loads(INTENT.read_text())
        if (pending["old_source_sha256"] != old_sha
                or pending["new_source_sha256"] != sha(Path(__file__).read_bytes())):
            raise RuntimeError("pending focus28 intent uses different sources")
        current_sha = sha(STATE.read_bytes())
        if current_sha == pending["new_checkpoint_sha256"]:
            successor.durable_json(RECEIPT, pending)
            return pending
        if current_sha != pending["old_checkpoint_sha256"]:
            raise RuntimeError("pending focus28 intent conflicts with checkpoint")
    original = STATE.read_bytes()
    state = json.loads(original)
    successor.verify_last_raw(state)
    boundary = verify_boundary(state, original, old_sha)
    if audit_raw.main() != 0:
        raise RuntimeError("independent raw audit rejected old checkpoint")
    audit = json.loads((HERE / "raw-audit.json").read_text())
    if (audit["checkpoint_sha256"] != sha(original) or audit["errors"]
            or audit["completed_attempts"] != len(state["completed"])):
        raise RuntimeError("raw audit disagrees with old checkpoint")
    canonical = healthy_early(state)
    changed = migrated(state, canonical, boundary)
    new = successor.encoded(changed)
    receipt = {"schema": 1, "created_at_utc": campaign.utc(),
               "policy": POLICY, "boundary": boundary,
               "old_source_sha256": old_sha,
               "new_source_sha256": sha(Path(__file__).read_bytes()),
               "old_checkpoint_sha256": sha(original),
               "new_checkpoint_sha256": sha(new),
               "completed_before_after": [len(state["completed"]), len(changed["completed"])],
               "queue_before_after": [len(state["queue"]), len(changed["queue"])],
               "seen_before_after": [len(state["seen"]), len(changed["seen"])],
               "active_before_after": [state["active"], changed["active"]],
               "attempt_cap_before_after": [state["attempt_cap"], changed["attempt_cap"]],
               "completed_prefix_sha256": sha(successor.encoded(state["completed"])),
               "raw_audit_sha256": sha((HERE / "raw-audit.json").read_bytes()),
               "canonical_ids_sha256": changed["focus28_scheduler"]["canonical_ids_sha256"],
               "canonical_counts": candidate_counts(state, canonical)}
    if INTENT.exists():
        intent = json.loads(INTENT.read_text())
        if {key: value for key, value in receipt.items() if key != "created_at_utc"} != {
                key: value for key, value in intent.items() if key != "created_at_utc"}:
            raise RuntimeError("pending focus28 intent differs from recomputed handoff")
        receipt = intent
    else:
        successor.durable_json(INTENT, receipt)
    successor.durable_json(STATE, changed)
    if sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("focus28 checkpoint replace SHA mismatch")
    successor.durable_json(RECEIPT, receipt)
    return receipt


def run(args: argparse.Namespace) -> None:
    with campaign.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff(args.expected_old_sha256)
        campaign.MIN_FREE_BYTES = MIN_FREE_BYTES
        campaign.choose = choose
        state = json.loads(STATE.read_text())
        deadline = time.monotonic() + args.wall_seconds
        print(json.dumps({"handoff_checkpoint": receipt["new_checkpoint_sha256"],
                          "boundary": receipt["boundary"], "policy": POLICY,
                          "shared_start_lock": str(campaign.START_LOCK),
                          "min_free_gib": 10, "max_java_before_start": campaign.MAX_JAVA_BEFORE_START},
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
                time.sleep(min(args.poll_seconds, max(0, deadline - time.monotonic())))
        print("focus28 wall cap reached; resume this checkpoint", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--expected-old-sha256", required=True)
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        state = json.loads(STATE.read_text())
        canonical = healthy_early(state)
        print(json.dumps({"old_source_sha256": sha((HERE / "successor.py").read_bytes()),
                          "expected_old_sha256": args.expected_old_sha256,
                          "new_source_sha256": sha(Path(__file__).read_bytes()),
                          "canonical_counts": candidate_counts(state, canonical),
                          "focus_needed": focus_needed(state),
                          "attempts": len(state["completed"]),
                          "effective": {case: len(rows) for case, rows in campaign.effective(state).items()},
                          "attempt_cap": state["attempt_cap"],
                          "max_faults": state["max_faults"],
                          "free_gib": round(shutil.disk_usage(HERE).free / 1024**3, 2)},
                         sort_keys=True))
    elif args.run:
        run(args)
    else:
        parser.error("choose --preview or --run")


if __name__ == "__main__":
    main()
