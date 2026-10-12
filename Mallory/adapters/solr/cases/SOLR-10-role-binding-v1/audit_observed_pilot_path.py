#!/usr/bin/env python3
"""Read-only, SHA-bound audit of the one admitted SOLR-10 role fault trial.

This attests an observed post-fault task/region path. It does not claim that
the injected exception caused the later target check or revealed a bug.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from Mallory.core.events import event_address, load_trace
from Mallory.core.feedback import analyze
from Mallory.core.graph import OccurrenceGraph


CASE = Path(__file__).resolve().parent
HEALTHY = ROOT / "data/mallory/calibration_solr10_role_v1_node2/SOLR-10"
PILOT = ROOT / "data/mallory/pilot_solr10_role_v1_node2/SOLR-10"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def only(events: tuple[dict, ...], kind: str, fault_id: str) -> dict:
    rows = [e for e in events if e.get("type") == kind and e.get("fault_id") == fault_id]
    require(len(rows) == 1, f"expected exactly one {kind} for {fault_id}; got {len(rows)}")
    return rows[0]


def path_between(edges: list[dict], source: str, target: str,
                 by_id: dict[str, dict], start_seq: int, end_seq: int,
                 node: str, epoch: int) -> list[dict]:
    """Find a strictly time-ordered path of observed, same-actor edges."""
    queue = deque([(source, start_seq, [])])
    while queue:
        current, after_seq, path = queue.popleft()
        if current == target and path:
            return path
        for edge in edges:
            if edge["certainty"] != "observed" or edge["source"] != current:
                continue
            a, b = by_id[edge["producer_event"]], by_id[edge["consumer_event"]]
            if not (after_seq <= a["seq"] < b["seq"] < end_seq):
                continue
            if any(e.get("node") != node or e.get("epoch") != epoch for e in (a, b)):
                continue
            if any(entry["target"] == edge["target"] for entry in path):
                continue
            queue.append((edge["target"], b["seq"], path + [edge]))
    raise ValueError("no observed, time-ordered same-actor task/region path")


def main() -> None:
    admission_file = CASE / "admission-one-pilot-node2.json"
    admission = json.loads(admission_file.read_text())
    pilot_receipt_file = PILOT / "role-pilot-receipt.json"
    pilot_receipt = json.loads(pilot_receipt_file.read_text())
    config_file = CASE / "config-role-v1-healthy-node2.json"
    plan_file = HEALTHY / "role-plan-v1.json"
    healthy_result_file = HEALTHY / "result.json"
    healthy_events_file = HEALTHY / "trials/r0000/events.jsonl.gz"
    trial_result_file = PILOT / "r0001/pilot-result.json"
    trial_events_file = PILOT / "r0001/events.jsonl"
    plan_receipt_file = HEALTHY / "role-plan-v1-receipt.json"
    sources = {
        "admission": admission_file,
        "config": config_file,
        "plan": plan_file,
        "healthy_result": healthy_result_file,
        "healthy_events_gzip": healthy_events_file,
        "healthy_plan_receipt": plan_receipt_file,
        "trial_result": trial_result_file,
        "trial_events_raw": trial_events_file,
        "trial_receipt": pilot_receipt_file,
        "feedback_source": ROOT / "Mallory/core/feedback.py",
        "graph_source": ROOT / "Mallory/core/graph.py",
        "events_source": ROOT / "Mallory/core/events.py",
    }
    hashes = {name: sha(path) for name, path in sources.items()}
    require(admission["admitted"] is True and admission["max_trials"] == 1
            and admission["host"] == "node2", "not the admitted node2 one-trial pilot")
    for name, key in (("config", "config_sha256"), ("plan", "plan_sha256"),
                      ("healthy_result", "healthy_result_sha256"),
                      ("healthy_events_gzip", "healthy_events_sha256")):
        require(hashes[name] == admission[key], f"admission {name} SHA mismatch")
    require(hashes["admission"] == pilot_receipt["admission_sha256"],
            "pilot receipt/admission SHA mismatch")
    require(hashes["trial_events_raw"] == pilot_receipt["events_sha256"],
            "pilot raw trace SHA mismatch")
    require(hashes["plan"] == pilot_receipt["plan_sha256"],
            "pilot plan SHA mismatch")
    require(hashes["healthy_events_gzip"] == json.loads(plan_receipt_file.read_text())[
        "healthy_events_sha256"], "healthy plan receipt/gzip mismatch")
    require(pilot_receipt["trial_count"] == 1 and pilot_receipt["return_code"] == 0
            and not pilot_receipt["timed_out"] and pilot_receipt["junit"] == {
                "run": 1, "failures": 0, "ignored": 0}, "pilot did not finish one passing JUnit")

    plan = json.loads(plan_file.read_text())
    config = json.loads(config_file.read_text())
    trial_result = json.loads(trial_result_file.read_text())
    require(trial_result["source_revision"] == "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
            and trial_result["junit"] == {"run": 1, "failures": 0, "ignored": 0},
            "trial result source or JUnit mismatch")
    require(len(plan["faults"]) == 1, "expected single-fault plan")
    fault = plan["faults"][0]
    trace = load_trace(trial_events_file)
    require(not trace.incomplete_last_line, "incomplete pilot trace")
    events = trace.events
    by_id = {e["id"]: e for e in events if isinstance(e.get("id"), str)}
    require(len(by_id) == len(events), "duplicate or missing pilot event IDs")
    matched = only(events, "FAULT_MATCHED", fault["fault_id"])
    applied = only(events, "FAULT_APPLIED", fault["fault_id"])
    door = by_id["SOLR-10-role-v1-r0001:2939"]
    require(applied["id"] == "SOLR-10-role-v1-r0001:2941"
            and matched["id"] == "SOLR-10-role-v1-r0001:2940",
            "selected fault event IDs changed")
    for event in (door, matched, applied):
        require(event["site"] == fault["point"]["site"]
                and event["role"] == fault["point"]["role"]
                and event["role_ordinal"] == fault["point"]["role_ordinal"]
                and event["role_resolution"] == "unique", "exact role receipt mismatch")
        require(event["role_node"] == event["node"] == applied["node"]
                and event["role_epoch"] == event["epoch"] == applied["epoch"]
                and event["role_leader_id"] == applied["role_leader_id"],
                "physical leader or epoch mismatch")
    require(door["seq"] < matched["seq"] < applied["seq"], "fault sequence out of order")
    audit = pilot_receipt["strict_role_audit"]
    require(audit["physical_node"] == applied["node"]
            and audit["physical_epoch"] == applied["epoch"]
            and audit["leader_id"] == applied["role_leader_id"],
            "pilot receipt physical leader mismatch")
    check = by_id[audit["first_postfault_target_check_id"]]
    require(check["id"] == "SOLR-10-role-v1-r0001:3007"
            and check["type"] == "TARGET_CHECK"
            and check["site"] in config["target"]["check_sites"]
            and check["seq"] > applied["seq"], "later exact target check mismatch")
    require((check["node"], check["epoch"]) == (applied["node"], applied["epoch"]),
            "later target moved to another physical actor or epoch")
    decisions = [e for e in events if e.get("type") == "ROLE_DECISION"
                 and e.get("role") == "overseer-leader"
                 and applied["seq"] < e["seq"] < check["seq"]]
    require(decisions and all(e.get("decision") == "YES"
                              and e.get("node") == applied["node"]
                              and e.get("epoch") == applied["epoch"]
                              and e.get("role_leader_id") == applied["role_leader_id"]
                              for e in decisions),
            "leader role changed or was ambiguous between fault and target")
    first_decision = by_id["SOLR-10-role-v1-r0001:2938"]
    require(first_decision["type"] == "ROLE_DECISION"
            and first_decision["decision"] == "YES"
            and first_decision["role_leader_id"] == applied["role_leader_id"]
            and first_decision["node"] == applied["node"]
            and first_decision["epoch"] == applied["epoch"]
            and first_decision["seq"] < door["seq"],
            "missing immediate pre-door affirmative leader decision")

    feedback = analyze(trace, config["target"], plan["faults"], return_code=0,
                       timed_out=False, require_event_time_paths=True)
    require(feedback["status"] == "observed" and feedback["all_faults_effective"]
            and feedback["fault_identity_valid"] and feedback["target_reached"]
            and not feedback["target_threw"], "strict target/fault feedback mismatch")
    matching_doors = [d for d in feedback["doors"] if d["event_id"] == door["id"]]
    require(len(matching_doors) == 1 and matching_doors[0]["in_closure"],
            "selected door lacks event-time target closure evidence")
    path = path_between(feedback["closure_edges"], event_address(applied),
                        event_address(check), by_id, applied["seq"], check["seq"],
                        applied["node"], applied["epoch"])
    require([edge["kind"] for edge in path] == ["task", "region_parent", "region_parent"],
            "expected exact task-to-handler-to-target path")
    submit = by_id[path[0]["producer_event"]]
    source_region_enters = [e for e in events if e.get("type") == "REGION_ENTER"
                            and e.get("occurrence") == applied["occurrence"]]
    source_region_exits = [e for e in events if e.get("type") == "REGION_EXIT"
                           and e.get("occurrence") == applied["occurrence"]]
    require(len(source_region_enters) == len(source_region_exits) == 1,
            "source Overseer occurrence has no unique entry/exit")
    source_enter, source_exit = source_region_enters[0], source_region_exits[0]
    require(source_enter["id"] == "SOLR-10-role-v1-r0001:136"
            and source_exit["id"] == "SOLR-10-role-v1-r0001:3564"
            and source_enter["seq"] < applied["seq"] < submit["seq"] < source_exit["seq"],
            "fault or task submit falls outside the same exact Overseer region")
    require(submit["type"] == "TASK_SUBMIT"
            and submit["occurrence"] == applied["occurrence"]
            and isinstance(applied["thread_id"], int)
            and submit["thread_id"] == applied["thread_id"]
            and source_enter["thread_id"] == applied["thread_id"]
            and source_exit["thread_id"] == applied["thread_id"],
            "task was not submitted from the faulted Overseer run thread")
    region = by_id[path[-1]["consumer_event"]]
    require(region["type"] == "REGION_ENTER"
            and region["occurrence"] == check["occurrence"]
            and region["thread_id"] == check["thread_id"]
            and region["seq"] < check["seq"],
            "target check was not in the reached region")
    require(not [e for e in events if e.get("type") == "TARGET_THROW"
                 and e.get("seq", -1) > applied["seq"]],
            "unexpected post-fault TARGET_THROW")
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    graph_path = graph.event_path(applied, check, require_edge=True)
    require(graph_path is not None and len(graph_path) == len(path)
            and all((edge.producer_event, edge.consumer_event, edge.certainty) ==
                    (row["producer_event"], row["consumer_event"], "observed")
                    for edge, row in zip(graph_path, path)),
            "strict graph.event_path from FAULT_APPLIED to TARGET_CHECK failed")
    source_parent = source_enter.get("parent_id")
    source_parent_linked = any(edge.target == event_address(source_enter)
                               and edge.kind == "region_parent" for edge in graph.edges)
    require(source_parent and not source_parent_linked
            and graph.gaps.get("unmatched_parent") == 1,
            "pre-source root-parent gap changed; review before classifying")

    output = {
        "schema_version": 1, "case_id": "SOLR-10", "host": "node2",
        "classification": "same_actor_observed_path_retained_no_bug",
        "limits": "Observed local continuation and task/region edges do not prove the injected exception caused the later check. The source region's predecessor scoped-root parent is unmatched but is not traversed by the fault-to-target witness.",
        "physical_actor": {"node": applied["node"], "epoch": applied["epoch"],
                           "overseer_election_id": applied["role_leader_id"]},
        "fault": {"door_id": door["id"], "matched_id": matched["id"],
                  "applied_id": applied["id"], "site": applied["site"],
                  "role_ordinal": applied["role_ordinal"]},
        "postfault_role_decision_ids": [e["id"] for e in decisions],
        "observed_path": [{k: edge[k] for k in ("kind", "evidence", "certainty",
                                                  "producer_event", "consumer_event")}
                          for edge in path],
        "event_path_from_applied_succeeds": True,
        "source_region": {"entry_id": source_enter["id"], "exit_id": source_exit["id"],
                          "occurrence": source_enter["occurrence"],
                          "thread_id": source_enter["thread_id"],
                          "predecessor_parent_id": source_parent,
                          "predecessor_parent_linked": source_parent_linked},
        "target_check_id": check["id"], "target_check_outcome": check.get("outcome"),
        "junit": pilot_receipt["junit"], "target_throw_count": 0,
        "sha256": hashes,
    }
    destination = PILOT / "observed-path-audit.json"
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(destination), "sha256": sha(destination),
                      "classification": output["classification"]}, sort_keys=True))


if __name__ == "__main__":
    main()
