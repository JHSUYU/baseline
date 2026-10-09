#!/usr/bin/env python3
"""Audit HDFS-24 terminal raw trials for a physical DN retry/RPC/target path.

Run only on a terminal, immutable campaign copy. This does not infer causality
from target retention, matching node names, or the core graph summary.
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from verify_hdfs24_retry_v3 import CHECK, DOOR, numeric_thread, point_equal, scoped


class EvidenceError(ValueError):
    pass


def ensure(ok: bool, message: str) -> None:
    if not ok:
        raise EvidenceError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def trace(trial: Path, result: dict) -> list[dict]:
    path = trial / "events.jsonl.gz"
    evidence = result.get("events_evidence", {})
    ensure(digest(path) == evidence.get("gzip_sha256"), f"{trial.name}: gzip hash mismatch")
    with gzip.open(path, "rb") as stream:
        raw = stream.read(128 * 1024 * 1024 + 1)
    ensure(len(raw) <= 128 * 1024 * 1024, f"{trial.name}: oversized raw trace")
    ensure(hashlib.sha256(raw).hexdigest() == evidence.get("raw_sha256"),
           f"{trial.name}: raw trace hash mismatch")
    events = [json.loads(line) for line in raw.splitlines()]
    ensure(len(events) == len({e.get("id") for e in events}) ==
           len({e.get("seq") for e in events}), f"{trial.name}: duplicate events")
    ensure(all(isinstance(e.get("seq"), int) for e in events),
           f"{trial.name}: nonnumeric event sequence")
    ensure([e["seq"] for e in events] == sorted(e["seq"] for e in events),
           f"{trial.name}: trace out of order")
    return events


def unique_rpc(events: list[dict], token: str, transport: str) -> dict | None:
    pairs = {}
    for label, typ, port in (("request_send", "SEND", "request"),
                             ("request_recv", "RECV", "request"),
                             ("response_send", "SEND", "response"),
                             ("response_recv", "RECV", "response")):
        rows = [e for e in events if e.get("type") == typ and
                e.get("port") == port and e.get("transport") == transport and
                e.get("correlation") == token]
        if len(rows) != 1:
            return None
        pairs[label] = rows[0]
    return pairs


def witness_for_fault(events: list[dict], fault: dict) -> tuple[str, dict | None]:
    """Return the first strict witness for this exact applied retry fault."""
    point = fault["point"]
    if point.get("site") != DOOR or fault.get("exception_class") != "java.io.IOException":
        return "other_fault_site", None
    fid = fault["fault_id"]
    hits = {}
    for typ in ("DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"):
        rows = [e for e in events if e.get("type") == typ and
                (point_equal(e, point) if typ == "DOOR_OBSERVED" else
                 e.get("fault_id") == fid)]
        if len(rows) != 1:
            return "fault_receipt_missing_or_ambiguous", None
        hits[typ] = rows[0]
    obs, matched, applied = (hits[t] for t in
                             ("DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"))
    if not (all(point_equal(e, point) and
                e.get("exception_class") == "java.io.IOException" and scoped(e)
                for e in (obs, matched, applied)) and
            obs["node"] == matched["node"] == applied["node"] and
            obs["epoch"] == matched["epoch"] == applied["epoch"] and
            obs["thread_id"] == matched["thread_id"] == applied["thread_id"] and
            obs["occurrence"] == matched["occurrence"] == applied["occurrence"] and
            obs["seq"] < matched["seq"] < applied["seq"] and
            applied["node"].startswith("hdfs-cluster-") and
            "/dn" in applied["node"]):
        return "fault_identity_mismatch", None

    actor = (applied["node"], applied["epoch"], applied["thread_id"])
    retries = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
               e.get("site") == DOOR and e.get("exception_class") == "java.io.IOException" and
               (e.get("node"), e.get("epoch"), e.get("thread_id")) == actor and
               e.get("occurrence") == applied["occurrence"] and
               e["seq"] > applied["seq"] and scoped(e)]
    if not retries:
        return "no_same_thread_retry", None

    failure = "no_unique_retry_rpc_target_path"
    for retry in retries:
        later_door = min((e["seq"] for e in retries if e["seq"] > retry["seq"]),
                         default=float("inf"))
        sends = [e for e in events if e.get("type") == "SEND" and
                 e.get("site") == "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest" and
                 e.get("port") == "request" and e.get("transport") == "hadoop-ipc" and
                 (e.get("node"), e.get("epoch"), e.get("thread_id")) == actor and
                 e.get("occurrence") == applied["occurrence"] and scoped(e) and
                 retry["seq"] < e["seq"] < later_door]
        for send in sends:
            token = send.get("correlation")
            if not isinstance(token, str) or not token:
                continue
            pairs = unique_rpc(events, token, "hadoop-ipc")
            if pairs is None or pairs["request_send"] is not send:
                continue
            rr, rs, cr = (pairs[k] for k in
                          ("request_recv", "response_send", "response_recv"))
            if not (all(scoped(e) for e in (rr, rs, cr)) and
                    rr.get("node", "").startswith("hdfs-cluster-") and
                    "/nn" in rr["node"] and
                    (rs.get("node"), rs.get("epoch"), rs.get("thread_id"),
                     rs.get("occurrence")) ==
                    (rr.get("node"), rr.get("epoch"), rr.get("thread_id"),
                     rr.get("occurrence")) and
                    (cr.get("node"), cr.get("epoch"), cr.get("thread_id")) == actor and
                    rr.get("context") == rs.get("context") == cr.get("context") == token and
                    applied["seq"] < retry["seq"] < send["seq"] < rr["seq"] <
                    rs["seq"] < cr["seq"]):
                continue
            regions = [e for e in events if e.get("type") == "REGION_ENTER" and
                       e.get("site", "").startswith(
                           "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage#doTransition") and
                       e.get("parent_id") == token and e.get("context") == token and
                       (e.get("node"), e.get("epoch"), e.get("thread_id")) == actor and
                       e["seq"] > cr["seq"] and numeric_thread(e)]
            for region in regions:
                checks = [e for e in events if e.get("type") == "TARGET_CHECK" and
                          e.get("site") == CHECK and e.get("occurrence") == region.get("occurrence") and
                          e.get("context") == token and
                          (e.get("node"), e.get("epoch"), e.get("thread_id")) == actor and
                          e["seq"] > region["seq"] and numeric_thread(e)]
                if not checks:
                    continue
                check = min(checks, key=lambda e: e["seq"])
                path = {"fault_id": fid, "point": point,
                        "actor": {"node": actor[0], "epoch": actor[1], "thread_id": actor[2]},
                        "rpc_token": token,
                        "event_ids": {"door": obs["id"], "fault_matched": matched["id"],
                                      "fault_applied": applied["id"], "retry_door": retry["id"],
                                      "request_send": send["id"], "request_recv": rr["id"],
                                      "response_send": rs["id"], "response_recv": cr["id"],
                                      "region_enter": region["id"], "target_check": check["id"]},
                        "event_seqs": {"fault_applied": applied["seq"],
                                       "retry_door": retry["seq"], "request_send": send["seq"],
                                       "request_recv": rr["seq"], "response_send": rs["seq"],
                                       "response_recv": cr["seq"], "region_enter": region["seq"],
                                       "target_check": check["seq"]},
                        "intervening_applied_fault_ids": [e.get("fault_id") for e in events
                            if e.get("type") == "FAULT_APPLIED" and e.get("fault_id") != fid
                            and applied["seq"] < e["seq"] < check["seq"]]}
                return "strict_event_time_retry_rpc_target", path
    return failure, None


def file_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file()}


def audit_campaign(campaign: Path) -> dict:
    campaign = campaign.resolve()
    config, summary, audit = (read(campaign / name) for name in
                              ("config.json", "result.json", "offline-causal-audit.json"))
    ensure(config.get("case_id") == summary.get("case_id") == "HDFS-24",
           "wrong campaign case")
    ensure(summary.get("status") in {"budget_exhausted", "queue_exhausted"} and
           summary.get("healthy_seed_valid") is True and
           summary.get("fault_trials_completed", 0) > 0,
           "campaign not terminal with valid healthy seed")
    ensure(config.get("target", {}).get("check_sites") == [CHECK] and
           config["target"].get("exception_class") == "java.io.IOException" and
           config.get("reject_coarse_roots") is True and
           config.get("require_event_time_paths") is True,
           "wrong exact target or permissive graph")
    ensure(audit.get("report_gate_passed") is True and
           audit.get("applied_fault_identity_valid") is True,
           "frozen offline audit failed")
    count = summary["fault_trials_completed"]
    expected = {f"r{i:04d}" for i in range(count + 1)}
    trials_root = campaign / "trials"
    ensure({p.name for p in trials_root.iterdir() if p.is_dir()} == expected,
           "trial directory set does not match terminal count")
    hashes = file_hashes(campaign)
    if (campaign / "archive-manifest.json").exists():
        archive = read(campaign / "archive-manifest.json")
        ensure(isinstance(archive.get("files"), dict) and
               all(hashes.get(name) == value for name, value in archive["files"].items()),
               "terminal archive manifest mismatch")
    ensure(len(summary.get("trials", [])) == count + 1 and
           {r.get("trial_id") for r in summary["trials"]} == set(range(count + 1)),
           "terminal summary trial set mismatch")
    rows = []
    classes: Counter[str] = Counter()
    for number in range(count + 1):
        trial = trials_root / f"r{number:04d}"
        result, junit, plan = (read(trial / name) for name in
                               ("result.json", "junit-receipt.json", "plan.json"))
        ensure(result.get("case_id") == "HDFS-24" and
               result.get("junit_receipt_sha256") == hashes[str((trial / "junit-receipt.json").relative_to(campaign))] and
               result.get("site_catalog_sha256") == hashes[str((trial / "sites.jsonl").relative_to(campaign))],
               f"{trial.name}: trial artifact mismatch")
        events = trace(trial, result)
        throws = [e for e in events if e.get("type") == "TARGET_THROW" and
                  e.get("site") == config["target"].get("throw_site")]
        checks = [e for e in events if e.get("type") == "TARGET_CHECK" and e.get("site") == CHECK]
        row = {"trial_id": number, "trial": trial.name,
               "trial_result_sha256": hashes[str((trial / "result.json").relative_to(campaign))],
               "trace_gzip_sha256": result["events_evidence"]["gzip_sha256"],
               "trace_raw_sha256": result["events_evidence"]["raw_sha256"],
               "junit": {k: junit.get(k) for k in ("status", "tests", "errors", "failures")},
               "exact_target_check_count": len(checks),
               "exact_target_throw_count": len(throws),
               "exact_target_throw_event_ids": [e["id"] for e in throws],
               "feedback_status": result.get("feedback", {}).get("status"),
               "faults": []}
        if number == 0:
            ensure(junit.get("status") == "passed" and junit.get("tests", 0) > 0 and
                   junit.get("errors") == junit.get("failures") == 0 and
                   checks and not throws and not plan.get("faults"),
                   "healthy seed failed exact zero-throw/JUnit gate")
        else:
            ensure(result.get("trial_id") == number and
                   len(plan.get("faults", [])) <= config["budget"]["max_faults_per_trial"] and
                   len({f.get("fault_id") for f in plan.get("faults", [])}) == len(plan.get("faults", [])),
                   f"{trial.name}: invalid fault plan")
            ensure(summary["trials"][number].get("trial_id") == number,
                   f"{trial.name}: summary order mismatch")
            for fault in plan["faults"]:
                classification, witness = witness_for_fault(events, fault)
                classes[classification] += 1
                row["faults"].append({"fault_id": fault["fault_id"],
                                      "point": fault["point"],
                                      "classification": classification,
                                      "witness": witness})
            row["target_exception_candidate"] = bool(throws) and bool(
                result.get("feedback", {}).get("target_exception_candidate"))
        rows.append(row)
    return {"schema_version": 1, "case_id": "HDFS-24",
            "status": "terminal_event_time_rpc_retry_audit",
            "scope": "causal_path_only_no_bug_claim",
            "campaign": str(campaign), "terminal_status": summary["status"],
            "fault_trials_completed": count, "files_sha256": hashes,
            "config_sha256": hashes["config.json"], "result_sha256": hashes["result.json"],
            "offline_audit_sha256": hashes["offline-causal-audit.json"],
            "fault_classification_counts": dict(sorted(classes.items())),
            "strict_witness_trials": sum(any(f["witness"] for f in row["faults"])
                                         for row in rows[1:]),
            "exact_target_throw_trials": sum(row["exact_target_throw_count"] > 0
                                             for row in rows[1:]),
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    ensure(not args.out.resolve().is_relative_to(args.campaign.resolve()),
           "output must be outside the immutable campaign")
    report = audit_campaign(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"],
                      "strict_witness_trials": report["strict_witness_trials"],
                      "exact_target_throw_trials": report["exact_target_throw_trials"],
                      "out": str(args.out)}))


if __name__ == "__main__":
    main()
