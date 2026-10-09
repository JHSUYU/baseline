#!/usr/bin/env python3
"""Isolated, resumable SOLR-10 campaign with strict Overseer role replay.

The pinned Mallory core supplies checkpointing, coverage, and scheduling. This
module adds role identity at the exact Overseer queue door and requires an
observed event-time path before expanding a fault sequence or reporting a
target-exception candidate. The original core tree is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PINNED = HERE / "work"
sys.path.insert(0, str(PINNED))
sys.path.insert(1, str(ROOT))
sys.path.insert(2, str(HERE))

from Mallory.core import campaign  # noqa: E402
from Mallory.core.events import event_address, event_seq  # noqa: E402
from Mallory.core.feedback import _target_match  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402
from role_plan import ROLE, SITE  # noqa: E402
from run_pilot_role_v1 import preflight  # noqa: E402

BASE_ANALYZE = campaign.analyze
BASE_MUTATE = campaign.mutate
BASE_RUN_TRIAL = campaign._run_trial
BASE_SCORE = campaign.score


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_role(event: dict, point: dict, reference: dict | None = None) -> bool:
    if (event.get("site") != SITE or event.get("role") != ROLE
            or event.get("role_ordinal") != point["role_ordinal"]
            or event.get("role_resolution") != "unique"
            or not isinstance(event.get("node"), str) or not event["node"]
            or event["node"] == "unknown"
            or not isinstance(event.get("epoch"), int)
            or not isinstance(event.get("thread_id"), int)
            or event.get("role_node") != event.get("node")
            or event.get("role_epoch") != event.get("epoch")
            or not isinstance(event.get("role_leader_id"), str)
            or not event["role_leader_id"]):
        return False
    return (reference is None or all(event.get(key) == reference.get(key)
                                     for key in ("node", "epoch", "occurrence",
                                                 "thread_id", "role_leader_id")))


def role_analyze(trace, target, plan, **kwargs):
    if not kwargs.get("require_event_time_paths") or not kwargs.get("reject_coarse_roots"):
        raise ValueError("SOLR-10 full campaign requires strict root and event-time gates")
    feedback = BASE_ANALYZE(trace, target, plan, **kwargs)
    events = trace.events
    by_id = {e.get("id"): e for e in events if isinstance(e.get("id"), str)}
    for door in feedback.get("doors", []):
        source = by_id.get(door.get("event_id"))
        if source is not None and source.get("site") == SITE:
            for key in ("role", "role_ordinal", "role_resolution", "role_node",
                        "role_epoch", "role_leader_id"):
                door[key] = source.get(key)
    valid = True
    role_receipts = []
    for fault in plan:
        point = fault.get("point", {})
        if point.get("role") != ROLE:
            continue
        if (set(point) != {"site", "role", "role_ordinal"}
                or point["site"] != SITE
                or isinstance(point["role_ordinal"], bool)
                or not isinstance(point["role_ordinal"], int)
                or point["role_ordinal"] <= 0
                or fault.get("fault_type") != "EXCEPTION"
                or fault.get("exception_class") !=
                    "org.apache.zookeeper.KeeperException$ConnectionLossException"):
            valid = False
            continue
        fid = fault.get("fault_id")
        matched = [e for e in events if e.get("type") == "FAULT_MATCHED"
                   and e.get("fault_id") == fid]
        applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
                   and e.get("fault_id") == fid]
        if len(matched) != 1 or len(applied) != 1:
            valid = False
            continue
        match, apply = matched[0], applied[0]
        doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                 and same_role(e, point, apply)
                 and event_seq(e) < event_seq(match)]
        if (len(doors) != 1 or not same_role(match, point, apply)
                or not same_role(apply, point)
                or not event_seq(doors[0]) < event_seq(match) < event_seq(apply)):
            valid = False
            continue
        decisions = [e for e in events if e.get("type") == "ROLE_DECISION"
                     and e.get("role") == ROLE and e.get("node") == apply.get("node")
                     and e.get("epoch") == apply.get("epoch")
                     and e.get("occurrence") == apply.get("occurrence")
                     and event_seq(e) < event_seq(doors[0])]
        if not decisions or decisions[-1].get("decision") != "YES" or (
                decisions[-1].get("role_leader_id") != apply.get("role_leader_id")):
            valid = False
            continue
        role_receipts.append({"fault_id": fid, "applied_event_id": apply["id"],
                              "node": apply["node"], "epoch": apply["epoch"],
                              "leader_id": apply["role_leader_id"]})
    feedback["role_identity_valid"] = valid
    feedback["role_receipts"] = role_receipts
    if not valid:
        feedback["all_faults_effective"] = False
        feedback["fault_identity_valid"] = False
        feedback["target_exception_candidate"] = False
        feedback["status"] = "fault_role_identity_invalid"

    postfault_path = False
    path_receipt = None
    if plan and feedback.get("all_faults_effective"):
        applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
                   and e.get("fault_id") in {f["fault_id"] for f in plan}]
        if applied:
            last = max(applied, key=event_seq)
            graph = OccurrenceGraph(events, reject_coarse_roots=True)
            checks = [e for e in events if e.get("type") == "TARGET_CHECK"
                      and _target_match(e, target, throwing=False)
                      and event_seq(e) > event_seq(last)]
            for check in checks:
                path = graph.event_path(last, check, require_edge=True)
                if path is not None and all(edge.certainty == "observed" for edge in path):
                    postfault_path = True
                    path_receipt = {"fault_event_id": last.get("id"),
                                    "target_check_event_id": check.get("id"),
                                    "edges": [{"kind": e.kind, "producer_event": e.producer_event,
                                               "consumer_event": e.consumer_event,
                                               "certainty": e.certainty} for e in path]}
                    break
    feedback["postfault_event_path_valid"] = postfault_path
    feedback["postfault_event_path"] = path_receipt
    if plan and not postfault_path:
        feedback["target_exception_candidate"] = False
    return feedback


def role_mutate(parent, feedback, config):
    if parent and not feedback.get("postfault_event_path_valid"):
        return []
    candidates = BASE_MUTATE(parent, feedback, config)
    doors = [door for door in feedback.get("doors", []) if door.get("site") == SITE
             and door.get("role") == ROLE
             and door.get("role_resolution") == "unique"
             and door.get("in_closure")]
    by_point = {json.dumps(door["point"], sort_keys=True): door for door in doors}
    result = []
    seen = set()
    for candidate in candidates:
        fault = candidate["faults"][-1]
        point = fault["point"]
        if point.get("site") == SITE:
            door = by_point.get(json.dumps(point, sort_keys=True))
            if door is None or not isinstance(door.get("role_ordinal"), int):
                continue
            fault["point"] = {"site": SITE, "role": ROLE,
                              "role_ordinal": door["role_ordinal"]}
            fault["role_source"] = {"event_id": door["event_id"],
                                    "node": door["role_node"],
                                    "epoch": door["role_epoch"],
                                    "leader_id": door["role_leader_id"]}
            candidate["selection_reason"] = "role_bound_dynamic_closure"
        signature = sequence_signature(candidate["faults"])
        if signature not in seen:
            candidate["signature"] = signature
            result.append(candidate)
            seen.add(signature)
    return result


def role_score(candidate, parent_feedback, tried_sites, waiting_rounds):
    priority = BASE_SCORE(candidate, parent_feedback, tried_sites, waiting_rounds)
    return priority + (30.0 if candidate["faults"][-1]["point"].get("role") == ROLE else 0.0)


def role_run_trial(config, out, trial_id, plan, save_running, target_binding):
    # The healthy physical leader may migrate across fresh MiniCluster runs.
    # The role receipt and event-time path, rather than healthy node IDs,
    # identify an effective fault and retained target.
    return BASE_RUN_TRIAL(config, out, trial_id, plan, save_running, None)


def preflight_full(config_file: Path, admission_file: Path | None, out: Path) -> dict:
    config = json.loads(config_file.read_text())
    positive_file = ROOT / "data/mallory/pilot_solr10_role_v1_node2/SOLR-10/observed-path-audit.json"
    admission = json.loads(admission_file.read_text()) if admission_file else None
    if admission is not None and (
            admission.get("admitted") is not True or admission.get("host") != "node2"
            or admission.get("case_id") != "SOLR-10"
            or admission.get("config_sha256") != sha(config_file)
            or admission.get("runner_sha256") != sha(Path(__file__))
            or admission.get("positive_pilot_audit_sha256") != sha(positive_file)
            or admission.get("intended_output") != str(out.resolve())):
        raise ValueError("independent node2 full admission missing or mismatched")
    if (config.get("budget") != {"trials": 80, "seconds": 3600,
                                  "max_faults_per_trial": 6,
                                  "trial_timeout_seconds": 480}
            or not config.get("require_event_time_paths")
            or not config.get("reject_coarse_roots")
            or not config.get("auto_promote_if_healthy")
            or config.get("calibration_only")):
        raise ValueError("full budget or strict path config differs")
    for item in config.get("runtime_artifacts", []):
        path = Path(item["path"])
        if sha(path) != item["sha256"]:
            raise ValueError(f"pinned runtime artifact SHA mismatch: {path}")
    positive = json.loads(positive_file.read_text())
    if (positive.get("classification") != "same_actor_observed_path_retained_no_bug"
            or positive.get("event_path_from_applied_succeeds") is not True
            or config.get("role_pilot_audit", {}).get("sha256") != sha(positive_file)):
        raise ValueError("positive role pilot audit missing strict event path")
    source = preflight(Path(config["cwd"]), Path(config["mapping"]["distribution_root"]))
    campaign.validate_config(config)
    if not Path(campaign.__file__).resolve().is_relative_to(PINNED):
        raise ValueError("campaign core did not load from isolated pinned source")
    return {"config_sha256": sha(config_file),
            "admission_sha256": sha(admission_file) if admission_file else None,
            "positive_pilot_audit_sha256": sha(positive_file),
            "source_head": source["source_head"], "pinned_core": str(campaign.__file__)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not args.preflight_only and args.admission_receipt is None:
        parser.error("--admission-receipt is required for campaign launch")
    receipt = preflight_full(args.config, args.admission_receipt, args.out)
    print(json.dumps({"preflight": "passed", **receipt}, sort_keys=True), flush=True)
    if args.preflight_only:
        return 0
    campaign.analyze = role_analyze
    campaign.mutate = role_mutate
    campaign.score = role_score
    campaign._run_trial = role_run_trial
    state = campaign.run(args.config, args.out)
    print(json.dumps({"status": state["status"], "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
