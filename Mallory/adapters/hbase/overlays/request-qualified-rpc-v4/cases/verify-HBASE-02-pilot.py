#!/usr/bin/env python3
"""Independently verify the HBASE-02 scoped Get fault pilot."""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def one(events, kind, predicate, reason):
    matches = [event for event in events if event.get("type") == kind and predicate(event)]
    require(len(matches) == 1, "%s: found %d" % (reason, len(matches)))
    return matches[0]


def verify_chain(events, trial_result, plan):
    feedback = trial_result["feedback"]
    require(feedback["all_faults_effective"] is True, "fault not effective")
    require(feedback["target_reached"] is True, "target missing")
    require(feedback["target_threw"] is False, "pilot unexpectedly threw selected target")
    require(feedback["fault_identity_valid"] is True, "fault identity invalid")
    require(len(plan) == 1, "pilot must have one planned fault")
    fault_id = plan[0]["fault_id"]
    site = plan[0]["point"]["site"]
    require(site.endswith(":rpc:hbase.pb.ClientService.Get:request:120"), "wrong selected Get")
    applied = one(events, "FAULT_APPLIED", lambda e: e.get("fault_id") == fault_id,
                  "unique applied fault")
    matched = one(events, "FAULT_MATCHED", lambda e: e.get("fault_id") == fault_id,
                  "unique matched fault")
    door = one(events, "DOOR_OBSERVED", lambda e: e.get("site") == site and
               e.get("occurrence") == applied.get("occurrence"), "unique selected door")
    actor = (applied.get("node"), applied.get("epoch"), applied.get("occurrence"),
             applied.get("thread_id"), applied.get("context"))
    require(actor[0] in ("rs0", "rs1") and actor[0] != "unknown", "unnamed server actor")
    require(actor[2] and not actor[2].startswith("unscoped:"), "unscoped server region")
    for event in (door, matched):
        require((event.get("node"), event.get("epoch"), event.get("occurrence"),
                 event.get("thread_id"), event.get("context")) == actor,
                "door/match actor mismatch")
    require(door["seq"] < matched["seq"] < applied["seq"], "fault order invalid")
    token = actor[4]
    require(token.endswith(":task:120"), "wrong transported request token")
    request = one(events, "RECV", lambda e: e.get("site") == "hbase:RpcServer.call" and
                  e.get("correlation") == token and e.get("node") == actor[0] and
                  e.get("thread_id") == actor[3] and
                  e.get("port") == "hbase.pb.ClientService.Get", "typed server request")
    enter = one(events, "REGION_ENTER", lambda e: e.get("occurrence") == actor[2],
                "server region entry")
    response = one(events, "SEND", lambda e: e.get("site") ==
                   "hbase:RpcServer.call:completion" and e.get("correlation") == token and
                   e.get("occurrence") == actor[2] and
                   e.get("port") == "hbase.pb.ClientService.Get", "real server response")
    region_exit = one(events, "REGION_EXIT", lambda e: e.get("occurrence") == actor[2],
                      "balanced server region exit")
    require(request["seq"] < enter["seq"] < door["seq"] and
            applied["seq"] < response["seq"] < region_exit["seq"],
            "server request/response order invalid")
    client_recv = one(events, "RECV", lambda e: e.get("site") ==
                      "hbase:RpcConnection.readResponse" and e.get("correlation") == token and
                      e.get("node") == "client" and e.get("port") ==
                      "hbase.pb.ClientService.Get", "correlated client response")
    submit = one(events, "TASK_SUBMIT", lambda e: e.get("site") ==
                 "hbase:RpcConnection.response-ready" and e.get("parent_id") == token and
                 e.get("node") == "client", "response handoff submit")
    claim = one(events, "TASK_CLAIM", lambda e: e.get("site") ==
                "hbase:AbstractRpcClient.callBlockingMethod" and
                e.get("correlation") == submit.get("correlation") and
                e.get("node") == "client", "response handoff claim")
    require(response["seq"] < client_recv["seq"] < submit["seq"] < claim["seq"],
            "response handoff order invalid")
    followups = feedback["qualified_request_followups"]
    require(len(followups) == 1 and followups[0]["fault_event_id"] == applied["id"],
            "missing exact qualified followup")
    target_id = followups[0]["target_event_id"]
    target = one(events, "TARGET_CHECK", lambda e: e.get("id") == target_id,
                 "exact retained target")
    require(target["site"].endswith("@910:branch:2") and target.get("node") == "client",
            "wrong target site/actor")
    require(target.get("occurrence") == claim.get("occurrence") and
            target.get("thread_id") == claim.get("thread_id") and
            claim["seq"] < target["seq"], "target is not after handoff in same client call")
    edge_ids = {(edge["producer_event"], edge["consumer_event"], edge["kind"])
                for edge in followups[0]["edges"]}
    require((response["id"], client_recv["id"], "rpc") in edge_ids and
            (submit["id"], claim["id"], "task") in edge_ids,
            "response/task edges do not match the raw trace")
    return {"request_token": token, "server_node": actor[0], "server_epoch": actor[1],
            "server_occurrence": actor[2], "server_thread_id": actor[3],
            "target_occurrence": target["occurrence"],
            "target_thread_id": target["thread_id"],
            "witness_events": {label: event["id"] for label, event in
                               (("request", request), ("enter", enter), ("door", door),
                                ("matched", matched), ("applied", applied),
                                ("response", response), ("exit", region_exit),
                                ("client_recv", client_recv), ("task_submit", submit),
                                ("task_claim", claim), ("target", target))}}


def verify(campaign):
    summary = load(campaign / "result.json")
    audit = load(campaign / "offline-causal-audit.json")
    require(summary["case_id"] == "HBASE-02" and summary["status"] == "queue_exhausted",
            "unexpected campaign result")
    require(summary["fault_trials_completed"] == 1 and
            summary["strict_injected_trials"] == 1 and
            summary["strict_target_trials"] == 1 and
            summary["exact_exception_trials"] == 0, "wrong pilot counts")
    require(audit["report_gate_passed"] is True and
            audit["campaign_result_sha256"] == sha256(campaign / "result.json") and
            audit["require_event_time_paths"] is True,
            "offline causal audit/binding invalid")
    trial = campaign / "trials" / "r0001"
    result = load(trial / "result.json")
    junit = load(trial / "junit-receipt.json")
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == 0, "JUnit did not pass")
    evidence = result["events_evidence"]
    gzip_path = trial / evidence["gzip_path"]
    raw = gzip.open(gzip_path, "rb").read()
    require(sha256(gzip_path) == evidence["gzip_sha256"] and
            hashlib.sha256(raw).hexdigest() == evidence["raw_sha256"],
            "raw trace hash mismatch")
    events = [json.loads(line) for line in raw.splitlines()]
    witness = verify_chain(events, result, load(trial / "plan.json")["faults"])
    files = {str(path.relative_to(campaign)): sha256(path) for path in
             sorted(campaign.rglob("*")) if path.is_file() and path.name != ".campaign.lock"}
    return {"schema_version": 1, "case_id": "HBASE-02", "status": "pilot_strict_path_passed",
            "new_bug": False, "fault_trials_completed": 1, "exact_exception_trials": 0,
            "source_check": "hbase-client/src/main/java/org/apache/hadoop/hbase/client/ConnectionImplementation.java:910-911",
            "witness": witness, "file_sha256": files}


def tamper_tests(campaign):
    trial = campaign / "trials" / "r0001"
    result = load(trial / "result.json")
    plan = load(trial / "plan.json")["faults"]
    events = [json.loads(line) for line in gzip.open(trial / "events.jsonl.gz", "rb")]
    mutations = (
        ("wrong_applied_actor", "FAULT_APPLIED", "node", "rs9"),
        ("wrong_response_token", "SEND", "correlation", "unrelated"),
        ("missing_region_exit", "REGION_EXIT", "type", "OTHER"),
        ("wrong_target_occurrence", "TARGET_CHECK", "occurrence", "other-call"),
    )
    for name, kind, field, value in mutations:
        altered = copy.deepcopy(events)
        if name == "wrong_response_token":
            event = next(e for e in altered if e.get("type") == "SEND" and
                         e.get("site") == "hbase:RpcServer.call:completion" and
                         e.get("correlation", "").endswith(":task:120"))
        elif name == "wrong_target_occurrence":
            target_id = result["feedback"]["qualified_request_followups"][0]["target_event_id"]
            event = next(e for e in altered if e.get("id") == target_id)
        else:
            event = next(e for e in altered if e.get("type") == kind and
                         e.get("context", "").endswith(":task:120"))
        event[field] = value
        try:
            verify_chain(altered, result, plan)
        except ValueError:
            continue
        raise ValueError("tamper mutation accepted: " + name)
    return len(mutations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tamper-check", action="store_true")
    args = parser.parse_args()
    result = verify(args.campaign)
    if args.tamper_check:
        count = tamper_tests(args.campaign)
        result["tamper_mutations_rejected"] = count
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("PASS HBASE-02 strict request/response/target path")


if __name__ == "__main__":
    main()
