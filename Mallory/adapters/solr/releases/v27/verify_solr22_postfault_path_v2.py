#!/usr/bin/env python3
"""Verify SOLR-22 postfault HTTP paths against observed RPC edges and raw hashes."""

import gzip
import hashlib
import json
from pathlib import Path
import sys

from Mallory.core.graph import OccurrenceGraph


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def one_trial(root, exact_sites):
    result_path = root / "result.json"
    result = json.loads(result_path.read_text())
    archive = root / "events.jsonl.gz"
    evidence = result["events_evidence"]
    archive_sha = digest(archive)
    if archive_sha != evidence["gzip_sha256"] or archive.stat().st_size != evidence["gzip_bytes"]:
        raise ValueError(f"{root.name}: gzip mismatch")
    raw_sha = hashlib.sha256()
    raw_bytes = 0
    events = []
    with gzip.open(archive, "rb") as stream:
        for line in stream:
            raw_sha.update(line)
            raw_bytes += len(line)
            events.append(json.loads(line))
    if raw_sha.hexdigest() != evidence["raw_sha256"] or raw_bytes != evidence["raw_bytes"]:
        raise ValueError(f"{root.name}: raw trace mismatch")
    graph = OccurrenceGraph(tuple(events))
    observed_rpc = {(edge.producer_event, edge.consumer_event) for edge in graph.edges
                    if edge.kind == "rpc"}
    faults = [row for row in events if row.get("type") == "FAULT_APPLIED"
              and row.get("node") not in (None, "unknown")]
    sends = [row for row in events if row.get("type") == "SEND"
             and row.get("node") not in (None, "unknown")]
    receives = [row for row in events if row.get("type") == "RECV"
                and row.get("node") not in (None, "unknown")]
    checks = [row for row in events if row.get("type") == "TARGET_CHECK"
              and row.get("site") in exact_sites]
    paths = []
    for fault in faults:
        for send in sends:
            if (send.get("seq", -1) <= fault["seq"]
                    or send.get("node") != fault.get("node")
                    or send.get("epoch") != fault.get("epoch")
                    or send.get("thread") != fault.get("thread")
                    or not fault.get("context")
                    or send.get("context") != fault.get("context")):
                continue
            for recv in receives:
                if ((send["id"], recv["id"]) not in observed_rpc
                        or recv["seq"] <= send["seq"]):
                    continue
                matches = [check for check in checks
                           if check["seq"] > recv["seq"]
                           and check.get("node") == recv.get("node")
                           and check.get("epoch") == recv.get("epoch")
                           and check.get("context") == recv.get("context")]
                if matches:
                    check = min(matches, key=lambda row: row["seq"])
                    paths.append({
                        "fault": {"id": fault["id"], "seq": fault["seq"],
                                  "site": fault["site"], "node": fault["node"],
                                  "epoch": fault["epoch"], "context": fault["context"],
                                  "thread": fault["thread"]},
                        "send": {"id": send["id"], "seq": send["seq"],
                                 "correlation": send.get("correlation")},
                        "receive": {"id": recv["id"], "seq": recv["seq"],
                                    "node": recv["node"], "epoch": recv["epoch"],
                                    "context": recv["context"]},
                        "target_check": {"id": check["id"], "seq": check["seq"],
                                         "site": check["site"]},
                        "edge_kind": "observed_rpc",
                    })
                    break
            if paths and paths[-1]["fault"]["id"] == fault["id"]:
                break
    return {"trial_id": result["trial_id"], "trial_result_sha256": digest(result_path),
            "trace_gzip_sha256": archive_sha, "trace_raw_sha256": raw_sha.hexdigest(),
            "trace_raw_bytes": raw_bytes,
            "all_faults_effective": result.get("feedback", {}).get("all_faults_effective"),
            "target_reached": result.get("feedback", {}).get("target_reached"),
            "paths": paths}


def main():
    campaign = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (result.get("case_id") != "SOLR-22"
            or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80
            or not audit.get("report_gate_passed")
            or audit.get("campaign_result_sha256") != digest(result_path)):
        raise ValueError("terminal SOLR-22 result/audit mismatch")
    exact_sites = set(result["target"]["check_sites"])
    trials = [one_trial(campaign / "trials" / f"r{trial_id:04d}", exact_sites)
              for trial_id in range(81)]
    strict = [row for row in trials[1:]
              if row["all_faults_effective"] and row["target_reached"] and row["paths"]]
    report = {"schema_version": 2, "case_id": "SOLR-22",
              "evidence_kind": "same_context_fault_send_observed_rpc_receive_exact_target",
              "campaign_result_sha256": digest(result_path),
              "offline_causal_audit_sha256": digest(audit_path),
              "fault_trials_completed": 80,
              "strict_postfault_observed_rpc_path_trials": len(strict),
              "trials": trials}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"path": str(destination), "sha256": digest(destination),
                      "strict_path_trials": len(strict)}, sort_keys=True))


if __name__ == "__main__":
    main()
