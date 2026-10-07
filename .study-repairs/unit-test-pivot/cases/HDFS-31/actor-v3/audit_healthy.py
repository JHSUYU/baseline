#!/usr/bin/env python3
"""Fail-closed two-seed audit for the original HDFS31 embedded-cluster JUnit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block_key(row: dict) -> tuple:
    return tuple(row.get(k) for k in
                 ("actorKey", "dnObjectId", "dnUuidRaw", "blockPoolIdRaw", "blockIdRaw"))


def selector(row: dict) -> tuple:
    return tuple(row.get(k) for k in
                 ("marker", "siteId", "sourceKey", "hitOrdinal"))


def inspect(path: Path) -> dict:
    manifest = json.loads((path / "manifest.json").read_text())
    trace = rows(path / "runtime_trace.jsonl")
    registered = [r for r in trace if r["event"] == "ACTOR_REGISTERED"]
    entered = [r for r in trace if r["event"] == "ACTOR_ENTER"]
    transfers = [r for r in trace if r["event"] == "DIRECT_TRANSFER"
                 and r.get("caseId") == "HDFS-31"]
    checks = [r for r in trace if r["event"] == "DIRECT_TARGET_CHECK"
              and r.get("caseId") == "HDFS-31"]
    throws = [r for r in trace if r["event"] == "DIRECT_TARGET_THROW"
              and r.get("caseId") == "HDFS-31"]
    rpc = [r for r in trace if r["event"] == "FAULT_POINT_OBSERVED"
           and r.get("marker") == "FAULT:HDFS31_BP_RPC:RESPONSE"
           and r.get("peerRole") == "NN0" and r.get("sourceKey") != "unbound"]
    matched_targets = [c for c in checks if any(
        t["seq"] < c["seq"] and block_key(t) == block_key(c) for t in transfers)]
    eligible = [r for r in rpc if any(
        r["seq"] < t["seq"] and r.get("actorKey") == t.get("actorKey")
        and r.get("dnObjectId") == t.get("dnObjectId")
        for t in matched_targets)]
    endpoint_by_actor: dict[str, set[str]] = {}
    for r in rpc:
        endpoint_by_actor.setdefault(r["actorKey"], set()).add(r.get("endpointRaw", ""))
    registered_by_object = {r.get("dnObjectId"): r.get("actorKey") for r in registered}
    issues: list[str] = []
    if manifest.get("returncode") != 0:
        issues.append("original JUnit did not pass")
    if not (path / "jacoco.exec").is_file() or (path / "jacoco.exec").stat().st_size == 0:
        issues.append("JaCoCo execution data missing")
    if not (path / "covered_branch_counts.txt").is_file() or not (
            path / "covered_branch_counts.txt").read_text().strip():
        issues.append("production branch coverage missing")
    if not registered or not entered:
        issues.append("DataNode registration or BP actor adoption absent")
    if len(registered_by_object) != len(registered):
        issues.append("DataNode object registration collision")
    if not transfers or not matched_targets:
        issues.append("same-block transfer then selected target absent")
    for r in transfers + checks + throws:
        if (r.get("actorKey") in (None, "unbound") or r.get("dnObjectId") not in registered_by_object
                or registered_by_object.get(r.get("dnObjectId")) != r.get("actorKey")
                or not r.get("dnUuidRaw") or not r.get("blockPoolIdRaw")):
            issues.append("direct target/transfer lacks DN object, UUID, or BP identity")
            break
    if not eligible:
        issues.append("no actor-bound BP RPC before same-DN transfer and guard")
    if any(len(endpoints) != 1 or "" in endpoints
           for endpoints in endpoint_by_actor.values()):
        issues.append("actor NN0 role does not resolve to one raw endpoint")
    if any(r.get("endpointRaw") != r.get("actorNamenodeRaw") for r in rpc):
        issues.append("RPC remote address differs from actor NN address")
    if any(not any(c["seq"] < t["seq"] and block_key(c) == block_key(t)
                   for c in checks) for t in throws):
        issues.append("target throw lacks preceding same-DN/BP/block guard")
    return {
        "manifest": str(path / "manifest.json"), "trace_sha256": digest(path / "runtime_trace.jsonl"),
        "instrumentation_digest_sha256": manifest.get("instrumentation_digest_sha256"),
        "original_test_jar_sha256": manifest.get("original_test_jar_sha256"),
        "junit_exit": manifest.get("returncode"),
        "elapsed_seconds": manifest.get("elapsed_seconds"),
        "started_at_utc": manifest.get("started_at_utc"),
        "finished_at_utc": manifest.get("finished_at_utc"),
        "registered_dn": len(registered), "entered_bp_actor": len(entered),
        "transfer": len(transfers), "same_block_targets": len(matched_targets),
        "target_throws": len(throws), "bound_rpc": len(rpc), "eligible_rpc": len(eligible),
        "selectors": [list(selector(r)) for r in eligible],
        "target_actor_keys": sorted({r["actorKey"] for r in matched_targets}),
        "target_signatures": sorted({json.dumps({
            "siteId": r.get("siteId"), "actorKey": r.get("actorKey"),
            "servicePresent": r.get("servicePresent"), "exception": None}, sort_keys=True)
            for r in matched_targets}),
        "throw_signatures": sorted({json.dumps({
            "siteId": r.get("siteId"), "actorKey": r.get("actorKey"),
            "exception": r.get("exception")}, sort_keys=True) for r in throws}),
        "issues": sorted(set(issues)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", type=Path)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    seeds = [inspect(anchor / suffix) for suffix in ("healthy-a", "healthy-b")]
    issues = [f"{suffix}: {issue}" for suffix, seed in zip("ab", seeds)
              for issue in seed["issues"]]
    stable = sorted(set(map(tuple, seeds[0]["selectors"]))
                    & set(map(tuple, seeds[1]["selectors"])))
    if not stable:
        issues.append("no stable actor-bound producer selector across seeds")
    if seeds[0]["target_actor_keys"] != seeds[1]["target_actor_keys"]:
        issues.append("selected target actor keys vary across healthy seeds")
    if seeds[0]["target_signatures"] != seeds[1]["target_signatures"]:
        issues.append("selected target guard signatures vary across healthy seeds")
    if seeds[0]["throw_signatures"] != seeds[1]["throw_signatures"]:
        issues.append("selected target throw signatures vary across healthy seeds")
    if (not seeds[0]["instrumentation_digest_sha256"] or
            seeds[0]["instrumentation_digest_sha256"] != seeds[1]["instrumentation_digest_sha256"]):
        issues.append("instrumentation digest mismatch")
    if seeds[0]["original_test_jar_sha256"] != seeds[1]["original_test_jar_sha256"]:
        issues.append("original test JAR mismatch")
    receipt = {"schema": "hdfs31-actor-v3-healthy-1", "case_id": "HDFS-31",
               "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
               "seeds": seeds, "stable_selectors": [list(x) for x in stable],
               "issues": issues, "pass": not issues}
    temporary = anchor / "healthy_receipt.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(anchor / "healthy_receipt.json")
    print(json.dumps({"pass": receipt["pass"], "stable": len(stable),
                      "issues": issues, "seed_elapsed": [x["elapsed_seconds"] for x in seeds]}))
    if issues:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
