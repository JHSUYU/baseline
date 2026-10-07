#!/usr/bin/env python3
"""Reconstruct HDFS-31 V3 trial credit from immutable original-JUnit traces.

This reader does not use campaign.py's matching or mutation functions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


CASE = "HDFS-31"
MARKER = "FAULT:HDFS31_BP_RPC:RESPONSE"
TEST = "org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero"
MATCH_FIELDS = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
                "actorKey", "peerRole", "faultType")
BLOCK_FIELDS = ("actorKey", "dnObjectId", "dnUuidRaw", "blockPoolIdRaw", "blockIdRaw")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def same(row: dict, other: dict, keys: tuple[str, ...]) -> bool:
    return all(row.get(k) == other.get(k) for k in keys)


def inspect(anchor: Path, state: dict, item: dict, saved: dict,
            healthy_signatures: set[str]) -> dict:
    issues: list[str] = []
    run = anchor / "runs" / item["id"] / "attempt-1"
    manifest_path = run / "manifest.json"
    trace_path = run / "runtime_trace.jsonl"
    manifest = json.loads(manifest_path.read_text())
    trace = rows(trace_path)
    if digest(trace_path) != saved.get("trace_sha256"):
        issues.append("trace SHA differs from checkpoint")
    if manifest.get("instrumentation_digest_sha256") != state["instrumentation_digest_sha256"]:
        issues.append("trial instrumentation differs from healthy calibration")
    if manifest.get("test") != TEST or manifest.get("returncode") != saved.get("junit_exit"):
        issues.append("original JUnit identity or exit differs from checkpoint")
    if not (run / "jacoco.exec").is_file() or not (run / "jacoco.exec").stat().st_size:
        issues.append("JaCoCo execution data missing")
    for category in ("probes", "methods", "branch_counts", "lines"):
        if not (run / f"covered_{category}.txt").is_file():
            issues.append(f"production {category} coverage missing")

    sequence = item["sequence"]
    applied = [r for r in trace if r.get("event") == "FAULT_APPLIED"]
    exact = bool(sequence) and len(sequence) == len(applied) and all(
        a.get("faultIndex") == i and same(a, step, MATCH_FIELDS)
        for i, (step, a) in enumerate(zip(sequence, applied)))
    if exact:
        first = applied[0]
        endpoint = {r.get("endpointRaw") for r in trace
                    if r.get("event") == "FAULT_POINT_OBSERVED"
                    and r.get("actorKey") == first.get("actorKey")
                    and r.get("peerRole") == "NN0"}
        exact = (len(endpoint) == 1 and None not in endpoint and "" not in endpoint
                 and first.get("actorKey") not in (None, "unbound")
                 and first.get("dnUuidRaw") not in (None, "", "null")
                 and first.get("serviceObjectId", -1) > 0)
        for row in applied:
            if (row.get("marker") != MARKER or row.get("peerRole") != "NN0"
                    or row.get("endpointRaw") not in endpoint
                    or row.get("actorNamenodeRaw") != row.get("endpointRaw")
                    or not same(row, first, ("actorKey", "dnObjectId", "dnUuidRaw",
                                             "serviceObjectId"))):
                exact = False
                break
            if not any(o.get("event") == "FAULT_POINT_OBSERVED" and o["seq"] < row["seq"]
                       and same(o, row, ("marker", "siteId", "sourceKey", "occurrence",
                                         "hitOrdinal", "actorKey", "dnObjectId",
                                         "dnUuidRaw", "serviceObjectId", "endpointRaw"))
                       for o in trace):
                exact = False
                break
    if exact != saved.get("exact_order_applied"):
        issues.append("raw ordered fault match differs from checkpoint")

    checks: list[dict] = []
    throws: list[dict] = []
    if exact:
        first, last = applied[0], applied[-1]
        for row in trace:
            if (row.get("event") != "DIRECT_TARGET_CHECK"
                    or row.get("caseId") != CASE or row["seq"] <= last["seq"]
                    or not same(row, first, ("actorKey", "dnObjectId", "dnUuidRaw"))
                    or not row.get("blockPoolIdRaw")):
                continue
            if not any(t.get("event") == "DIRECT_TRANSFER" and t.get("caseId") == CASE
                       and t["seq"] < row["seq"] and same(t, row, BLOCK_FIELDS)
                       for t in trace):
                continue
            if not any(p.get("event") == "POOL_ADD" and p["seq"] < row["seq"]
                       and same(p, first, ("actorKey", "dnObjectId", "serviceObjectId"))
                       and p.get("blockPoolIdRaw") == row.get("blockPoolIdRaw")
                       for p in trace):
                continue
            if row.get("servicePresent"):
                if (row.get("serviceObjectId") != first.get("serviceObjectId")
                        or row.get("serviceOwnerSameDnBp") is not True):
                    continue
            elif row.get("priorPoolOwnerSameDnBp") is not True:
                continue
            checks.append(row)
        for row in trace:
            if row.get("event") != "DIRECT_TARGET_THROW" or row.get("caseId") != CASE:
                continue
            if any(c["seq"] < row["seq"] and same(c, row, BLOCK_FIELDS) for c in checks):
                throws.append(row)
    if bool(checks) != saved.get("valid_for_feedback"):
        issues.append("same DN/BP postfault credit differs from checkpoint")
    if len(checks) != saved.get("same_dn_bp_post_target"):
        issues.append("postfault target count differs from checkpoint")
    if len(throws) != saved.get("target_exceptions_after_fault"):
        issues.append("postfault selected throw count differs from checkpoint")
    signatures = {json.dumps({"siteId": r.get("siteId"),
                              "actorKey": r.get("actorKey"),
                              "exception": r.get("exception")}, sort_keys=True)
                  for r in throws}
    novel = signatures - healthy_signatures
    if len(novel) != saved.get("target_exceptions_with_novel_signature"):
        issues.append("novel target exception signatures differ from checkpoint")
    return {"plan_id": item["id"], "exact": exact, "effective": bool(checks),
            "postfault_target_checks": len(checks), "selected_throws": len(throws),
            "novel_signatures": sorted(novel), "junit_exit": manifest.get("returncode"),
            "elapsed_seconds": manifest.get("elapsed_seconds"), "issues": issues}


def audit(anchor: Path) -> dict:
    state_path = anchor / "campaign-state.json"
    receipt_path = anchor / "healthy_receipt.json"
    state = json.loads(state_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    issues: list[str] = []
    if (state.get("schema") != "hdfs31-actor-v3-campaign-1"
            or receipt.get("schema") != "hdfs31-actor-v3-healthy-1"
            or not receipt.get("pass")
            or digest(receipt_path) != state.get("healthy_receipt_sha256")):
        issues.append("healthy receipt or checkpoint identity invalid")
    ids = state.get("completion_order", [])
    if len(ids) != len(set(ids)) or set(ids) != set(state.get("completed", {})):
        issues.append("completed plan IDs duplicated or absent")
    healthy_signatures = set(receipt["seeds"][0]["throw_signatures"])
    if healthy_signatures != set(receipt["seeds"][1]["throw_signatures"]):
        issues.append("healthy target throw signatures disagree")
    trials = []
    for plan_id in ids:
        entry = state["completed"][plan_id]
        trial = inspect(anchor, state, entry["item"], entry["result"], healthy_signatures)
        trials.append(trial)
        issues.extend(f"{plan_id}: {issue}" for issue in trial["issues"])
    counts = Counter(t["effective"] for t in trials)
    if counts[True] != state.get("effective"):
        issues.append("effective count differs from raw traces")
    return {"schema": "hdfs31-actor-v3-independent-audit-1",
            "case_id": CASE, "checkpoint_sha256": digest(state_path),
            "healthy_receipt_sha256": digest(receipt_path),
            "completed": len(trials), "strict": sum(t["exact"] for t in trials),
            "effective": counts[True], "target_exceptions": sum(t["selected_throws"] for t in trials),
            "novel_target_signatures": sorted({s for t in trials for s in t["novel_signatures"]}),
            "junit_exit_counts": dict(Counter(str(t["junit_exit"]) for t in trials)),
            "sum_junit_seconds": round(sum(t["elapsed_seconds"] or 0 for t in trials), 3),
            "status": state.get("status"), "pass": not issues, "issues": issues}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", type=Path)
    args = parser.parse_args()
    result = audit(args.anchor.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
