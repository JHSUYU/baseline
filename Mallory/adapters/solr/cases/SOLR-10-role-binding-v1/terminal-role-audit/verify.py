#!/usr/bin/env python3
"""Independent, read-only audit of the SHA-pinned node2 SOLR-10 role export.

The generic physical-point auditor deliberately does not admit role points.
This verifier applies the pinned role resolver's exact runtime semantics to
the archived trace; it does not modify the physical-point gate or the export.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = HERE.parent / "work"
sys.path.insert(0, str(PINNED))
from Mallory.core.feedback import _target_match  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

MANIFEST_SHA = "b70fbf2be6cdf61e6802af74d59d86fac9a3d56c1c8f3cb21f15019e9d0cd445"
SOURCE_SHA = {
    "Mallory/core/audit.py": "5da7ca183c5f47b2078ad4fb71808edeec12f4f8f31dc6dcbab13185e4c87466",
    "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/RoleBindingRegistry.java": "bfa0dbc0310e06e820ef16a97968027fe4c73cbc751bf51889a78b3e1617563b",
    "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/work/Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation/FaultPlan.java": "6894c70b0535e6e4bdfab0ceaf47bc8dd121f934978f50e8f028d3543b1142fe",
    "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/run_role_campaign.py": "02805e2f302f5ed8ec83a7588213da7df842b2aa7e0b8192b89b2c8319cc3237",
    "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/work/Mallory/core/graph.py": "d712040ee432ddca0e84b6ee7a22fe8da58e0755b8b8437e61ad28164b979f08",
    "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/work/Mallory/core/feedback.py": "7ae1953e388b644c15ce629d2688c38e9d15f66f5e5bb352e0020b20cc99101c",
}
ROLE = "overseer-leader"
SITE = "org.apache.solr.cloud.OverseerTaskProcessor#run()V@246:door:1"
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
FIELDS = ("site", "node", "epoch", "occurrence", "thread", "thread_id", "hit",
          "door_ordinal", "role", "role_resolution", "role_node", "role_epoch",
          "role_leader_id", "role_ordinal", "fault_type", "exception_class")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"not a JSON object: {path}")
    return value


def verify_manifest(export: Path) -> dict:
    manifest_file = export / "evidence-manifest.json"
    require(sha(manifest_file) == MANIFEST_SHA, "export manifest SHA mismatch")
    manifest = read_json(manifest_file)
    require(manifest.get("case_id") == "SOLR-10" and manifest.get("host") == "node2"
            and manifest.get("status") == "budget_exhausted" and manifest.get("trials") == 81,
            "export manifest identity/count mismatch")
    listed = set()
    for row in manifest["files"]:
        name = row["path"]
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and name not in listed,
                f"invalid or duplicate export path: {name}")
        listed.add(name)
        file = export / path
        require(file.is_file() and file.stat().st_size == row["bytes"]
                and sha(file) == row["sha256"], f"export file mismatch: {name}")
    table = export / "terminal-table.csv"
    require(sha(table) == manifest["table_sha256"], "terminal table SHA mismatch")
    actual = {str(path.relative_to(export)) for path in export.rglob("*") if path.is_file()}
    require(actual == listed | {"evidence-manifest.json", "terminal-table.csv"},
            "export file set differs from manifest")
    return manifest


def load_events(trial_dir: Path, result: dict) -> tuple[dict, ...]:
    receipt = result["events_evidence"]
    require(receipt.get("gzip_path") == "events.jsonl.gz" and not receipt.get("raw_path"),
            "unexpected event archive path")
    raw = gzip.decompress((trial_dir / "events.jsonl.gz").read_bytes())
    require(len(raw) == receipt["raw_bytes"]
            and hashlib.sha256(raw).hexdigest() == receipt["raw_sha256"]
            and receipt["raw_sha256"] == result["events_sha256"],
            "decompressed event receipt mismatch")
    require(raw.endswith(b"\n"), "incomplete final event line")
    events = tuple(json.loads(line) for line in raw.splitlines())
    ids = [e.get("id") for e in events]
    seqs = [e.get("seq") for e in events]
    require(len(set(ids)) == len(ids) and all(isinstance(s, int) and not isinstance(s, bool)
            for s in seqs) and seqs == sorted(set(seqs)), "event IDs or order invalid")
    return events


def role_identity(event: dict, point: dict) -> bool:
    return (event.get("site") == point.get("site") == SITE
            and event.get("role") == point.get("role") == ROLE
            and event.get("role_ordinal") == point.get("role_ordinal")
            and event.get("role_resolution") == "unique"
            and re.fullmatch(r"node[0-9]+", str(event.get("node"))) is not None
            and type(event.get("epoch")) is int and event["epoch"] >= 0
            and event.get("role_node") == event["node"]
            and event.get("role_epoch") == event["epoch"]
            and isinstance(event.get("role_leader_id"), str)
            and bool(event["role_leader_id"])
            and type(event.get("thread_id")) is int and event["thread_id"] > 0
            and isinstance(event.get("occurrence"), str) and bool(event["occurrence"])
            and type(event.get("hit")) is int and event["hit"] > 0
            and type(event.get("door_ordinal")) is int and event["door_ordinal"] > 0)


def verify_fault(events: tuple[dict, ...], fault: dict) -> dict:
    point = fault.get("point", {})
    require(set(point) == {"site", "role", "role_ordinal"}
            and type(point.get("role_ordinal")) is int and point["role_ordinal"] > 0
            and point["site"] == SITE and point["role"] == ROLE
            and fault.get("fault_type") == "EXCEPTION"
            and fault.get("exception_class") == EXCEPTION,
            f"nonexact role plan: {fault.get('fault_id')}")
    fid = fault["fault_id"]
    matched = [e for e in events if e.get("type") == "FAULT_MATCHED"
               and e.get("fault_id") == fid]
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
               and e.get("fault_id") == fid]
    require(len(matched) == len(applied) == 1, f"match/apply count: {fid}")
    match, apply = matched[0], applied[0]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
             and role_identity(e, point)]
    require(len(doors) == 1, f"role door count: {fid}")
    door = doors[0]
    require(all(role_identity(e, point) for e in (match, apply))
            and all(all(e.get(key) == apply.get(key) for key in FIELDS)
                    for e in (door, match)), f"runtime role identity mismatch: {fid}")
    require(all(e.get("fault_type") == fault["fault_type"]
                and e.get("exception_class") == fault["exception_class"]
                for e in (door, match, apply)), f"fault type mismatch: {fid}")
    require(door["seq"] < match["seq"] < apply["seq"], f"event order mismatch: {fid}")
    decisions = [e for e in events if e.get("type") == "ROLE_DECISION"
                 and e.get("role") == ROLE and e.get("seq", -1) < door["seq"]
                 and e.get("occurrence") == apply["occurrence"]]
    require(bool(decisions), f"missing leader decision: {fid}")
    latest = max(decisions, key=lambda e: e["seq"])
    require(latest.get("decision") == "YES"
            and all(latest.get(k) == apply.get(k) for k in
                    ("site", "node", "epoch", "occurrence", "thread_id", "role_leader_id")),
            f"leader decision mismatch: {fid}")
    between = [e for e in events if e.get("type") == "ROLE_DECISION"
               and latest["seq"] < e["seq"] < apply["seq"]]
    require(not between, f"intervening leader decision: {fid}")
    return {"fault_id": fid, "door_id": door["id"], "matched_id": match["id"],
            "applied_id": apply["id"], "node": apply["node"],
            "epoch": apply["epoch"], "leader_id": apply["role_leader_id"],
            "role_ordinal": apply["role_ordinal"], "applied_seq": apply["seq"]}


def verify_path(events: tuple[dict, ...], result: dict, target: dict,
                fault_rows: list[dict]) -> dict | None:
    feedback = result["feedback"]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK"
              and _target_match(e, target, throwing=False)]
    throws = [e for e in events if e.get("type") == "TARGET_THROW"
              and _target_match(e, target, throwing=True)]
    if not fault_rows:
        require(feedback["target_reached"] == bool(checks)
                and feedback["target_threw"] == bool(throws)
                and feedback["target_exception_candidate"] is False,
                "healthy target claims disagree with trace")
        require(feedback["postfault_event_path_valid"] is False
                and feedback["postfault_event_path"] is None, "healthy path claim invalid")
        return None
    last = max(fault_rows, key=lambda row: row["applied_seq"])
    post_checks = [e for e in checks if e["seq"] > last["applied_seq"]]
    post_throws = [e for e in throws if e["seq"] > last["applied_seq"]
                   and e.get("exception_class") == target["exception_class"]]
    require(feedback["target_reached"] == bool(post_checks or post_throws)
            and feedback["target_threw"] == bool(post_throws)
            and feedback["target_exception_candidate"] is False,
            "postfault target claims disagree with trace")
    by_id = {e["id"]: e for e in events}
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    paths = [(check, graph.event_path(by_id[last["applied_id"]], check,
                                      require_edge=True)) for check in post_checks]
    witnessed = [(check, path) for check, path in paths if path is not None
                 and all(edge.certainty == "observed" for edge in path)]
    claimed = feedback["postfault_event_path_valid"]
    require(claimed == bool(witnessed), "postfault path guidance differs from trace")
    receipt = feedback["postfault_event_path"]
    if witnessed:
        check, path = witnessed[0]
        apply = by_id[last["applied_id"]]
        require(re.fullmatch(r"node[0-9]+", str(check.get("node"))) is not None
                and type(check.get("epoch")) is int
                and isinstance(check.get("occurrence"), str) and bool(check["occurrence"])
                and type(check.get("thread_id")) is int
                and (check["node"], check["epoch"]) ==
                    (apply["node"], apply["epoch"]),
                "witness target actor is unnamed or differs from faulted leader")
        decisions = [e for e in events if e.get("type") == "ROLE_DECISION"
                     and apply["seq"] < e["seq"] < check["seq"]]
        require(bool(decisions) and all(e.get("decision") == "YES"
                and (e.get("node"), e.get("epoch"), e.get("role_leader_id")) ==
                    (apply["node"], apply["epoch"], apply["role_leader_id"])
                for e in decisions), "leader role changed between fault and target")
        require([edge.kind for edge in path] ==
                ["task", "region_parent", "region_parent"],
                "witness has unexpected handoff shape")
        for edge in path:
            producer, consumer = by_id[edge.producer_event], by_id[edge.consumer_event]
            require(apply["seq"] < producer["seq"] < consumer["seq"] < check["seq"]
                    and all(re.fullmatch(r"node[0-9]+", str(row.get("node"))) is not None
                            and type(row.get("epoch")) is int
                            and (row["node"], row["epoch"]) ==
                                (apply["node"], apply["epoch"])
                            for row in (producer, consumer)),
                    "witness edge is unordered or crosses actors")
        first = by_id[path[0].producer_event]
        last_consumer = by_id[path[-1].consumer_event]
        require(first.get("occurrence") == apply.get("occurrence")
                and first.get("thread_id") == apply.get("thread_id")
                and last_consumer.get("occurrence") == check.get("occurrence")
                and last_consumer.get("thread_id") == check.get("thread_id"),
                "witness does not bind fault and selected target occurrences")
        expected = {"fault_event_id": last["applied_id"],
                    "target_check_event_id": check["id"],
                    "edges": [{"kind": e.kind, "producer_event": e.producer_event,
                               "consumer_event": e.consumer_event,
                               "certainty": e.certainty} for e in path]}
        require(receipt == expected, "postfault path receipt differs from observed path")
        return {"applied_event_id": apply["id"], "target_check_event_id": check["id"],
                "fault_node": apply["node"], "target_node": check["node"],
                "epoch": apply["epoch"], "leader_id": apply["role_leader_id"],
                "target_occurrence": check["occurrence"],
                "postfault_role_decision_ids": [e["id"] for e in decisions],
                "edge_kinds": [edge.kind for edge in path]}
    else:
        require(receipt is None, "unwitnessed postfault path receipt")
    return None


def verify_guidance(fault: dict, trial_id: int, source_doors: dict[str, dict],
                    source_feedback: dict[int, dict]) -> None:
    source = fault["role_source"]
    source_id = source["event_id"]
    match = re.fullmatch(r"SOLR-10-r(\d{4}):\d+", source_id)
    require(match is not None, f"malformed guidance source: {trial_id}")
    source_trial = int(match.group(1))
    require(source_trial < trial_id and source_id in source_doors,
            f"unknown or future guidance source: {trial_id}")
    door = source_doors[source_id]
    prior = source_feedback[source_trial]
    guidance = [d for d in prior["doors"] if d.get("event_id") == source_id]
    require(len(guidance) == 1 and guidance[0]["in_closure"] is True
            and (source_trial == 0 or prior["postfault_event_path_valid"] is True)
            and source == {"event_id": source_id, "node": door["node"],
                           "epoch": door["epoch"],
                           "leader_id": door["role_leader_id"]}
            and fault["point"]["role_ordinal"] == door["role_ordinal"],
            f"guidance source is inconsistent: {trial_id}")


def verify(export: Path) -> dict:
    manifest = verify_manifest(export)
    for relative, expected in SOURCE_SHA.items():
        require(sha(ROOT / relative) == expected, f"pinned source changed: {relative}")
    config, summary = read_json(export / "config.json"), read_json(export / "result.json")
    require(config["case_id"] == summary["case_id"] == "SOLR-10"
            and config["budget"]["trials"] == summary["fault_trials_completed"] == 80
            and len(summary["trials"]) == 81, "campaign identity/count mismatch")
    with (export / "terminal-table.csv").open(newline="") as stream:
        table = {int(row["trial_id"]): row for row in csv.DictReader(stream)}
    require(set(table) == set(range(81)), "terminal table trial IDs invalid")
    source_doors: dict[str, dict] = {}
    source_feedback: dict[int, dict] = {}
    rows = []
    total_faults = paths = target_reached = target_threw = source_node_changes = 0
    for trial_id in range(81):
        trial_dir = export / "trials" / f"r{trial_id:04d}"
        result = read_json(trial_dir / "result.json")
        plan = read_json(trial_dir / "plan.json")["faults"]
        require(result["case_id"] == "SOLR-10" and result["trial_id"] == trial_id
                and result["plan"] == plan, f"trial plan/result mismatch: {trial_id}")
        summary_row = summary["trials"][trial_id]
        require(summary_row["trial_id"] == trial_id
                and summary_row["result"] == f"trials/r{trial_id:04d}/result.json",
                f"summary trial index mismatch: {trial_id}")
        events = load_events(trial_dir, result)
        role_doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                      and e.get("role") == ROLE and e.get("site") == SITE]
        ordinals = [e.get("role_ordinal") for e in role_doors]
        require(ordinals == list(range(1, len(ordinals) + 1)),
                f"role ordinals are not unique and consecutive: {trial_id}")
        decisions = [e for e in events if e.get("type") == "ROLE_DECISION"
                     and e.get("role") == ROLE]
        leaders = {(e.get("node"), e.get("epoch"), e.get("role_leader_id"))
                   for e in decisions}
        require(len(leaders) == 1 and all(e.get("decision") == "YES" for e in decisions),
                f"leader role is not unique: {trial_id}")
        fault_rows = [verify_fault(events, fault) for fault in plan]
        require(len({row["fault_id"] for row in fault_rows}) == len(fault_rows),
                f"duplicate planned fault ID: {trial_id}")
        feedback = result["feedback"]
        fault_ids = [row["fault_id"] for row in fault_rows]
        require(feedback["matched_fault_ids"] == fault_ids
                and feedback["applied_fault_ids"] == fault_ids
                and feedback["all_faults_matched"] is True
                and feedback["all_faults_applied"] is True
                and feedback["role_identity_valid"] is True
                and feedback["fault_identity_valid"] is True
                and feedback["all_faults_effective"] == bool(plan),
                f"fault guidance disagrees with receipts: {trial_id}")
        role_receipts = feedback["role_receipts"]
        require(len(role_receipts) == len(fault_rows) and all(
                role_receipts[i] == {"fault_id": row["fault_id"],
                                     "applied_event_id": row["applied_id"],
                                     "node": row["node"], "epoch": row["epoch"],
                                     "leader_id": row["leader_id"]}
                for i, row in enumerate(fault_rows)),
                f"role guidance receipt mismatch: {trial_id}")
        for fault in plan:
            verify_guidance(fault, trial_id, source_doors, source_feedback)
        source_node_changes += sum(
            source_doors[fault["role_source"]["event_id"]]["node"] != row["node"]
            for fault, row in zip(plan, fault_rows))
        # role_run_trial passes None as the physical target binding for every
        # trial. The healthy node recorded in the summary is diagnostic only.
        target = config["target"]
        witness = verify_path(events, result, target, fault_rows)
        target_reached += bool(feedback["target_reached"] and plan)
        target_threw += bool(feedback["target_threw"] and plan)
        paths += bool(witness)
        total_faults += len(plan)
        expected_status = "observed" if feedback["target_reached"] else "target_lost"
        require(feedback["status"] == expected_status and result["return_code"] == 0
                and not result["timed_out"] and result["junit_validation"]["status"] == "passed"
                and result["selection_reason"] == ("healthy_seed" if trial_id == 0
                                                    else "role_bound_dynamic_closure"),
                f"trial outcome/guidance mismatch: {trial_id}")
        for key in ("status", "all_faults_effective", "target_reached",
                    "target_exception_candidate"):
            require(summary_row[key] == feedback[key], f"summary {key} mismatch: {trial_id}")
        table_row = table[trial_id]
        require(table_row["status"] == feedback["status"]
                and table_row["faults"] == str(len(plan))
                and table_row["all_faults_effective"] == str(feedback["all_faults_effective"])
                and table_row["role_identity_valid"] == str(feedback["role_identity_valid"])
                and table_row["postfault_event_path_valid"] == str(bool(witness))
                and table_row["target_reached"] == str(feedback["target_reached"])
                and table_row["target_exception_candidate"] == "False"
                and table_row["junit_status"] == "passed",
                f"terminal table disagrees with trial: {trial_id}")
        for door in role_doors:
            source_doors[door["id"]] = door
        source_feedback[trial_id] = feedback
        rows.append({"trial_id": trial_id, "faults": len(plan),
                     "role_receipts_valid": True, "postfault_path": bool(witness),
                     "witness": witness,
                     "role_source_nodes": [source_doors[fault["role_source"]["event_id"]]["node"]
                                           for fault in plan],
                     "target_reached": feedback["target_reached"],
                     "target_threw": feedback["target_threw"],
                     "feedback_status": feedback["status"]})
    require(summary["strict_injected_trials"] == 80
            and summary["strict_target_trials"] == paths
            and summary["target_reached_trials"] == target_reached
            and summary["exact_exception_trials"] == target_threw
            and summary["target_exception_candidate_trials"] == [],
            "terminal summary counts disagree with audited trials")
    return {"schema_version": 1, "case_id": "SOLR-10", "host": "node2",
            "classification": "role_receipts_valid_no_target_exception_candidate",
            "export_origin": "/users/ZhenyuLi/baseline/data/mallory/export_solr10_role_v1_node2/SOLR-10",
            "export_manifest_sha256": MANIFEST_SHA,
            "export_manifest_files": len(manifest["files"]),
            "pinned_source_sha256": SOURCE_SHA,
            "verifier_sha256": sha(Path(__file__)),
            "healthy_trials": 1, "fault_trials": 80,
            "planned_and_applied_faults": total_faults,
            "guidance_source_to_runtime_node_changes": source_node_changes,
            "role_receipt_failures": 0, "guidance_mismatches": 0,
            "postfault_observed_path_trials": paths,
            "target_reached_fault_trials": target_reached,
            "target_throw_fault_trials": target_threw,
            "target_exception_candidates": 0,
            "target_lost_trials": [r["trial_id"] for r in rows if r["feedback_status"] == "target_lost"],
            "trials": rows,
            "limits": "Runtime role metadata and observed event-time paths are verified. They do not establish that an injected exception caused a later target check."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    export = args.export.resolve(strict=True)
    out = args.out.resolve()
    require(out != export and export not in out.parents, "audit receipt must be outside export")
    receipt = verify(export)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"audit": str(out), "sha256": sha(out),
                      "fault_trials": receipt["fault_trials"],
                      "faults": receipt["planned_and_applied_faults"],
                      "role_receipt_failures": receipt["role_receipt_failures"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
