#!/usr/bin/env python3
"""Independent raw audit for at most two alternate-JUnit single-fault pilots."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
        "#testLeaseRecoveryAfterFailover")
SITE = ("<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: "
        "org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12")
FIELDS = ("marker", "siteId", "sourceKey", "occurrenceAddress", "hitOrdinal",
          "requestApi", "filePhase", "faultType")
METRICS = ("probes", "methods", "branch_counts")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()]


def root(address: str) -> str:
    return address.split("/rpc:", 1)[0].split("/server:", 1)[0]


def covered(directory: Path, metric: str) -> set[str]:
    path = directory / ("covered_" + metric + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def audit_one(plan: dict, baseline: dict[str, set[str]], healthy: dict) -> dict:
    number = plan["pilot"]
    directory = HERE / ("pilot-%02d" % number)
    manifest = json.loads((directory / "manifest.json").read_text())
    events = trace(directory)
    expected = plan["sequence"][0]
    errors = []
    if manifest.get("test") != TEST or manifest.get("instrumented") is not True:
        errors.append("wrong/non-instrumented original JUnit")
    if manifest.get("graphchecker_runtime_used") is not False:
        errors.append("unexpected GraphChecker runtime")
    for field in ("original_test_class_sha256", "original_tests_jar_sha256",
                  "original_test_resource_sha256", "instrumentation_source_sha256"):
        if manifest.get(field) != healthy.get(field):
            errors.append("source/JAR provenance mismatch " + field)
    if Path(manifest.get("plan", "")).resolve() != (directory / "fault-plan.tsv").resolve():
        errors.append("manifest plan path mismatch")
    if sha(directory / "fault-plan.tsv") != plan["plan_sha256"]:
        errors.append("plan SHA mismatch")
    if [e.get("seq") for e in events] != list(range(1, len(events) + 1)):
        errors.append("trace sequence gap")
    if not any(e.get("event") == "CLUSTER_REGISTER" and e.get("dataNodes") == 3
               for e in events):
        errors.append("three physical DataNodes absent")
    matched = [e for e in events if e.get("event") == "FAULT_MATCHED"]
    applied = [e for e in events if e.get("event") == "FAULT_APPLIED"]
    exact = len(matched) == len(applied) == 1
    if exact:
        m, a = matched[0], applied[0]
        exact = (m["seq"] < a["seq"] and m.get("planIndex") == a.get("planIndex") == 0
                 and all(m.get(k, "") == a.get(k, "") == expected[k] for k in FIELDS)
                 and expected["originSourceKey"] == a.get("sourceKey")
                 and root(a.get("occurrenceAddress", "")) == root(expected["occurrenceAddress"]))
        prior = [e for e in events if e.get("event") == "FAULT_POINT_OBSERVED"
                 and e.get("seq", 0) < m["seq"]
                 and all(e.get(k, "") == expected[k] for k in
                         ("marker", "siteId", "sourceKey", "occurrenceAddress",
                          "hitOrdinal", "requestApi", "filePhase"))]
        owner = a.get("sourceKey")
        beginnings = [e for e in events if e.get("event") == "RECOVERY_BEGIN"
                      and e.get("seq", 0) < a["seq"] and e.get("sourceKey") == owner
                      and e.get("occurrenceAddress") == root(a.get("occurrenceAddress", ""))
                      and e.get("blockId") == a.get("blockId")
                      and (a.get("recoveryId") is None
                           or e.get("recoveryId") == a.get("recoveryId"))]
        exact = exact and bool(prior) and bool(beginnings) and owner in {"dn0", "dn1", "dn2"}
    last = applied[0] if exact else None
    checks = [e for e in events if last is not None
              and e.get("event") == "TARGET_CHECK" and e.get("caseId") == "HDFS-28"
              and e.get("siteId") == SITE and e.get("seq", 0) > last["seq"]
              and e.get("sourceKey") == last.get("sourceKey")
              and e.get("occurrenceAddress") == root(last.get("occurrenceAddress", ""))
              and e.get("blockId") == last.get("blockId")
              and (last.get("recoveryId") is None
                   or e.get("recoveryId") == last.get("recoveryId"))]
    throws = [e for e in events if e.get("event") == "TARGET_THROW"
              and e.get("caseId") == "HDFS-28" and e.get("siteId") == SITE
              and e.get("runtimeType") == "java.io.IOException"
              and any(check.get("outcome") is True and check["seq"] < e.get("seq", 0)
                      for check in checks)
              and last is not None and e.get("seq", 0) > last["seq"]
              and e.get("sourceKey") == last.get("sourceKey")
              and e.get("occurrenceAddress") == root(last.get("occurrenceAddress", ""))
              and e.get("blockId") == last.get("blockId")
              and (last.get("recoveryId") is None
                   or e.get("recoveryId") == last.get("recoveryId"))]
    feedback_ok = (directory / "jacoco.exec").is_file() and all(
        (directory / ("covered_" + metric + ".txt")).is_file() for metric in METRICS)
    if not feedback_ok:
        errors.append("production JaCoCo feedback missing")
    coverage_gain = {metric: len(covered(directory, metric) - baseline[metric])
                     if checks else 0 for metric in METRICS}
    files = ("manifest.json", "runtime_trace.jsonl", "junit.log", "jacoco.exec",
             "fault-plan.tsv", "covered_probes.txt", "covered_methods.txt",
             "covered_branch_counts.txt")
    return {"pilot": number, "sequence_id": plan["id"], "seed": plan["seed"],
            "requested_faults": 1, "matched_faults": len(matched),
            "applied_faults": len(applied), "exact_actor_bound": bool(exact),
            "same_root_postfault_hdfs28_checks": len(checks),
            "effective_hdfs28": bool(exact and checks and feedback_ok),
            "hdfs28_target_throws": [e["seq"] for e in throws],
            "junit_exit": manifest.get("returncode"),
            "timeout_exceeded": manifest.get("timeout_exceeded"),
            "elapsed_seconds": manifest.get("elapsed_seconds"),
            "production_coverage_gain_vs_two_healthy": coverage_gain,
            "raw_sha256": {name: sha(directory / name) if (directory / name).is_file()
                           else None for name in files},
            "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    plans = json.loads((HERE / "pilot-plans.json").read_text())
    validation = json.loads((HERE / "healthy-validation.json").read_text())
    if (plans.get("test") != TEST or validation.get("test") != TEST
            or plans.get("healthy_validation_sha256") != sha(HERE / "healthy-validation.json")):
        raise RuntimeError("independent seed provenance mismatch")
    healthy = json.loads((HERE / "healthy-a" / "manifest.json").read_text())
    baseline = {metric: set().union(*(covered(HERE / name, metric)
                                     for name in ("healthy-a", "healthy-b")))
                for metric in METRICS}
    rows = [audit_one(plan, baseline, healthy) for plan in plans["plans"][:args.count]]
    result = {"schema": 1, "test": TEST, "fault_trials": len(rows),
              "independent_from_prior_ha_budget": True,
              "pilot_plans_sha256": sha(HERE / "pilot-plans.json"),
              "healthy_validation_sha256": sha(HERE / "healthy-validation.json"),
              "effective_hdfs28": sum(row["effective_hdfs28"] for row in rows),
              "target_exception_candidates": [row["pilot"] for row in rows
                                              if row["hdfs28_target_throws"]],
              "errors": ["pilot %d: %s" % (row["pilot"], error)
                         for row in rows for error in row["errors"]],
              "trials": rows}
    pending = HERE / "pilot-audit.json.tmp"
    pending.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    pending.replace(HERE / "pilot-audit.json")
    print(json.dumps({"fault_trials": result["fault_trials"],
                      "effective_hdfs28": result["effective_hdfs28"],
                      "candidates": result["target_exception_candidates"],
                      "errors": result["errors"]}, sort_keys=True))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
