#!/usr/bin/env python3
"""Require SOLR-22's matched RPC to be the next local send after a fault."""

import gzip
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    campaign = Path(sys.argv[1]).resolve()
    prior = Path(sys.argv[2]).resolve()
    destination = Path(sys.argv[3]).resolve()
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    previous = json.loads(prior.read_text())
    if (result.get("case_id") != "SOLR-22"
            or result.get("fault_trials_completed") != 80
            or not audit.get("report_gate_passed")
            or previous.get("campaign_result_sha256") != digest(result_path)
            or previous.get("offline_causal_audit_sha256") != digest(audit_path)):
        raise ValueError("terminal result/audit/strict path receipt mismatch")
    checked = []
    for row in previous["trials"][1:]:
        if not (row["all_faults_effective"] and row["target_reached"] and row["paths"]):
            continue
        trial_id = row["trial_id"]
        archive = campaign / "trials" / f"r{trial_id:04d}" / "events.jsonl.gz"
        trial_result = archive.parent / "result.json"
        if (digest(archive) != row["trace_gzip_sha256"]
                or digest(trial_result) != row["trial_result_sha256"]):
            raise ValueError(f"r{trial_id:04d}: archived evidence differs")
        raw_hash = hashlib.sha256()
        events = []
        with gzip.open(archive, "rb") as stream:
            for line in stream:
                raw_hash.update(line)
                events.append(json.loads(line))
        if raw_hash.hexdigest() != row["trace_raw_sha256"]:
            raise ValueError(f"r{trial_id:04d}: decompressed trace differs")
        next_send_paths = []
        for path in row["paths"]:
            fault, matched_send = path["fault"], path["send"]
            candidates = [event for event in events
                          if event.get("type") == "SEND"
                          and event.get("node") == fault["node"]
                          and event.get("epoch") == fault["epoch"]
                          and event.get("thread") == fault["thread"]
                          and event.get("context") == fault["context"]
                          and event.get("seq", -1) > fault["seq"]]
            if candidates and min(candidates, key=lambda event: event["seq"])["id"] == matched_send["id"]:
                next_send_paths.append(path)
        checked.append({"trial_id": trial_id,
                        "trial_result_sha256": row["trial_result_sha256"],
                        "trace_gzip_sha256": row["trace_gzip_sha256"],
                        "trace_raw_sha256": row["trace_raw_sha256"],
                        "next_send_paths": next_send_paths})
    report = {"schema_version": 1, "case_id": "SOLR-22",
              "evidence_kind": "first_same_thread_context_send_observed_rpc_exact_target",
              "campaign_result_sha256": digest(result_path),
              "offline_causal_audit_sha256": digest(audit_path),
              "strict_path_receipt_sha256": digest(prior),
              "strict_path_trials": len(checked),
              "next_send_observed_path_trials": sum(bool(row["next_send_paths"]) for row in checked),
              "trials": checked}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"path": str(destination), "sha256": digest(destination),
                      "next_send_path_trials": report["next_send_observed_path_trials"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
