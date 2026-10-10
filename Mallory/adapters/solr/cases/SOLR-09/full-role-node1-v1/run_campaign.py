#!/usr/bin/env python3
"""GO-gated SOLR-09 campaign on one named deleteCore command role."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import shutil
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
HEALTHY = HERE.parent / "healthy-role-node1-v1"
PINNED = HERE.parent / "runtime-role-v1/work"
OUT = ROOT / "data/mallory/full_solr09_runtime_role_v1_node1/SOLR-09"
LANE_LOCK = "/tmp/mallory-lanes/solr-node1-v1.lock"
SOURCE_LOCK = "/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock"

sys.path.insert(0, str(HEALTHY))
from audit_healthy import summarize as audit_healthy  # noqa: E402
sys.path.insert(0, str(PINNED))
from Mallory.core import campaign  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402

ROLE = "delete-replica-deletecore"
SITE = ("org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler"
        "#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1")
REGION = ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd"
          "#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;"
          "Ljava/lang/String;Lorg/apache/solr/common/cloud/ZkNodeProps;"
          "Ljava/lang/String;Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V")
CHECK = REGION + "@277:branch:7"
THROW = REGION + "@278:throw:1"
EXCEPTION = "java.util.concurrent.TimeoutException"
BASE_ANALYZE = campaign.analyze
BASE_MUTATE = campaign.mutate
BASE_APPLY_RESULT = campaign._apply_result
BASE_RUN_TRIAL = campaign._run_trial


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def role_point(point: dict) -> bool:
    return (set(point) == {"site", "role", "role_ordinal"}
            and point["site"] == SITE and point["role"] == ROLE
            and isinstance(point["role_ordinal"], int)
            and not isinstance(point["role_ordinal"], bool)
            and point["role_ordinal"] > 0)


def valid_plan(plan: list[dict]) -> bool:
    ordinals = []
    for fault in plan:
        point = fault.get("point", {})
        if (not role_point(point) or fault.get("fault_type") != "EXCEPTION"
                or fault.get("exception_class") != EXCEPTION):
            return False
        ordinals.append(point["role_ordinal"])
    return len(ordinals) == len(set(ordinals)) and len(plan) <= 3


def role_receipt(event: dict, point: dict) -> bool:
    node = event.get("node")
    return (role_point(point) and event.get("site") == SITE
            and event.get("role") == ROLE
            and event.get("role_resolution") == "unique"
            and event.get("role_ordinal") == point["role_ordinal"]
            and bool(re.fullmatch(r"node[0-9]+", str(node)))
            and event.get("role_node") == node
            and isinstance(event.get("epoch"), int)
            and event.get("role_epoch") == event.get("epoch")
            and event.get("role_source_occurrence") == event.get("occurrence")
            and event.get("region") == REGION
            and isinstance(event.get("thread_id"), int))


def analyze(trace, target, plan, **kwargs):
    feedback = BASE_ANALYZE(trace, target, plan, **kwargs)
    by_id = {event.get("id"): event for event in trace.events}
    for door in feedback.get("doors", []):
        event = by_id.get(door.get("event_id"))
        if event and event.get("site") == SITE:
            for key in ("role", "role_resolution", "role_ordinal", "role_node",
                        "role_epoch", "role_source_occurrence", "thread_id", "context"):
                door[key] = event.get(key)
    receipts = []
    valid = valid_plan(plan)
    for fault in plan:
        fid = fault.get("fault_id")
        matched = [e for e in trace.events if e.get("type") == "FAULT_MATCHED"
                   and e.get("fault_id") == fid]
        applied = [e for e in trace.events if e.get("type") == "FAULT_APPLIED"
                   and e.get("fault_id") == fid]
        if (len(matched) != 1 or len(applied) != 1
                or not role_receipt(matched[0], fault["point"])
                or not role_receipt(applied[0], fault["point"])
                or matched[0].get("exception_class") != EXCEPTION
                or applied[0].get("exception_class") != EXCEPTION
                or any(matched[0].get(key) != applied[0].get(key)
                       for key in ("node", "epoch", "occurrence", "thread_id", "context"))
                or matched[0].get("seq", -1) >= applied[0].get("seq", -1)):
            valid = False
            continue
        receipts.append({"fault_id": fid, "node": applied[0]["node"],
                         "epoch": applied[0]["epoch"],
                         "occurrence": applied[0]["occurrence"],
                         "thread_id": applied[0]["thread_id"],
                         "context": applied[0].get("context"),
                         "seq": applied[0]["seq"],
                         "applied_event_id": applied[0]["id"]})
    feedback["command_role_identity_valid"] = valid
    feedback["command_role_receipts"] = receipts
    if not valid:
        feedback["all_faults_effective"] = False
        feedback["fault_identity_valid"] = False
        feedback["target_exception_candidate"] = False
        if plan:
            feedback["status"] = "fault_command_role_identity_invalid"
        return feedback
    if feedback.get("target_exception_candidate"):
        qualified = [e for e in trace.events if e.get("type") == "TARGET_THROW"
                     and e.get("site") == THROW
                     and e.get("exception_class") == target.get("exception_class")]
        causally_bound = any(
            e.get("node") == r["node"] and e.get("epoch") == r["epoch"]
            and e.get("occurrence") == r["occurrence"]
            and e.get("thread_id") == r["thread_id"]
            and e.get("context") == r["context"] and e.get("seq", -1) > r["seq"]
            for e in qualified for r in receipts)
        feedback["target_exception_same_command"] = causally_bound
        if not causally_bound:
            feedback["target_exception_candidate"] = False
            feedback["status"] = "target_throw_other_command"
    return feedback


def mutate(parent, feedback, config):
    if not valid_plan(parent):
        return []
    candidates = BASE_MUTATE(parent, feedback, config)
    exact = {json.dumps(door["point"], sort_keys=True): door
             for door in feedback.get("doors", []) if door.get("site") == SITE
             and door.get("exception_class") == EXCEPTION
             and door.get("role") == ROLE
             and door.get("role_resolution") == "unique"
             and isinstance(door.get("role_ordinal"), int)
             and door.get("role_node") == door.get("point", {}).get("node")
             and door.get("role_epoch") == door.get("point", {}).get("epoch")
             and isinstance(door.get("local_timeline_evidence"), dict)}
    result = []
    seen = set()
    for candidate in candidates:
        fault = candidate["faults"][-1]
        door = exact.get(json.dumps(fault.get("point", {}), sort_keys=True))
        if door is None or fault.get("fault_type") != "EXCEPTION":
            continue
        fault["point"] = {"site": SITE, "role": ROLE,
                          "role_ordinal": door["role_ordinal"]}
        fault["role_source"] = {"event_id": door["event_id"],
                                "node": door["role_node"],
                                "epoch": door["role_epoch"],
                                "occurrence": door["role_source_occurrence"]}
        if not valid_plan(candidate["faults"]):
            continue
        candidate["selection_reason"] = "runtime_deletecore_role"
        signature = sequence_signature(candidate["faults"])
        if signature not in seen:
            candidate["signature"] = signature
            result.append(candidate)
            seen.add(signature)
    return result


def run_trial(config, out, trial_id, plan, save_running, target_binding):
    if not valid_plan(plan):
        raise ValueError("non-role fault plan refused before JVM start")
    # The Overseer may move to another physical node in a fresh MiniCluster.
    return BASE_RUN_TRIAL(config, out, trial_id, plan, save_running, None)


def apply_result(state, config, result, item):
    BASE_APPLY_RESULT(state, config, result, item)
    if result["trial_id"] != 0:
        return
    try:
        audit = audit_healthy(Path(state["out"]))
    except Exception as exc:
        audit = {"case_id": "SOLR-09", "status": "healthy_role_gap",
                 "audit_error": f"{type(exc).__name__}: {exc}"}
    campaign.atomic_json(Path(state["out"]) / "fresh-healthy-role-audit.json", audit)
    if audit.get("status") != "healthy_role_admitted":
        state["status"] = "healthy_role_gap"
        state["queue"].clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    import verify_full
    pins = verify_full.main()
    if args.preflight_only:
        print(json.dumps(pins, sort_keys=True), flush=True)
        return 0
    if args.admission_receipt is None:
        parser.error("independent dispatch GO receipt required before JVM campaign")
    receipt = json.loads(args.admission_receipt.read_text())
    if not (receipt.get("go") is True and receipt.get("case_id") == "SOLR-09"
            and receipt.get("host") == "node1" and receipt.get("mode") == "full"
            and receipt.get("config_sha256") == pins["config_sha256"]
            and receipt.get("runner_sha256") == sha(Path(__file__))
            and receipt.get("manifest_sha256") == sha(HERE / "manifest.json")
            and receipt.get("healthy_audit_sha256") == pins["healthy_audit_sha256"]
            and receipt.get("lane_lock") == LANE_LOCK
            and receipt.get("source_lock") == SOURCE_LOCK
            and receipt.get("intended_output") == str(OUT)):
        raise ValueError("independent dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("node1 host required")
    if shutil.disk_usage(ROOT).free < 7_650_410_496:
        raise ValueError("insufficient free disk for Solr full campaign")
    available_kib = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
    if available_kib < 8_388_608:
        raise ValueError("insufficient available RAM for Solr full campaign")
    Path(LANE_LOCK).parent.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in (LANE_LOCK, SOURCE_LOCK):
            handle = Path(name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        campaign.analyze = analyze
        campaign.mutate = mutate
        campaign._run_trial = run_trial
        campaign._apply_result = apply_result
        state = campaign.run(HERE / "config.json", OUT)
        print(json.dumps({"case_id": "SOLR-09", "status": state["status"],
                          "completed_trials": state["completed_trials"],
                          "target_exception_candidates": state["target_exception_candidates"]},
                         sort_keys=True), flush=True)
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
