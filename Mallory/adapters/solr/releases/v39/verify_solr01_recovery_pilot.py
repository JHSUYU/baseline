#!/usr/bin/env python3
"""SHA-bind exact IOException-to-retry witnesses in the SOLR-01 bounded pilot."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

SITE = ("org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider"
        "#getAliases(Z)Ljava/util/Map;@247:door:1")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return digest(path.read_bytes())


def trial_events(root: Path, trial_id: int) -> tuple[dict, list[dict], dict]:
    trial = root / "trials" / f"r{trial_id:04d}"
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text())
    evidence = result["events_evidence"]
    packed_path = trial / evidence["gzip_path"]
    packed = packed_path.read_bytes()
    assert digest(packed) == evidence["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert digest(raw) == evidence["raw_sha256"] and len(raw) == evidence["raw_bytes"]
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    hashes = {"trial_result_sha256": file_hash(result_path),
              "gzip_sha256": file_hash(packed_path),
              "raw_sha256": digest(raw), "raw_bytes": len(raw)}
    return result, events, hashes


def inspect(root: Path, source: Path) -> dict:
    config_path = root / "config.json"
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    config = json.loads(config_path.read_text())
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    assert config["case_id"] == result["case_id"] == "SOLR-01"
    assert config["static_fault_sites"] == [SITE]
    assert config["budget"]["max_faults_per_trial"] == 1
    assert result["status"] in {"budget_exhausted", "queue_exhausted"}
    assert 1 <= result["fault_trials_completed"] <= 5
    assert audit["campaign_result_sha256"] == file_hash(result_path)
    assert audit["archive_integrity_valid"] and audit["guidance_consistent"]
    assert file_hash(source) == config["mapping"]["target_source_sha256"]
    source_text = source.read_text()
    assert 'new CollectionAdminRequest.ListAliases().process(client)' in source_text
    assert 'catch (SolrServerException | RemoteSolrException | IOException e)' in source_text
    assert 'for (String nodeName: liveNodes)' in source_text
    checks = set(config["target"]["check_sites"])
    rows = []
    for trial_id in range(1, result["fault_trials_completed"] + 1):
        trial, events, hashes = trial_events(root, trial_id)
        plan = trial.get("plan", [])
        assert len(plan) == 1 and plan[0]["point"]["site"] == SITE
        assert plan[0]["fault_type"] == "EXCEPTION"
        assert plan[0]["exception_class"] == "java.io.IOException"
        assert (trial["site_catalog_validation"]["observed_target_class_sha256"]
                == config["expected_target_class_sha256"])
        applied = [event for event in events if event.get("type") == "FAULT_APPLIED"
                   and event.get("fault_id") == plan[0]["fault_id"]]
        witnesses = []
        for fault in applied:
            assert (fault["site"] == SITE and fault["fault_type"] == "EXCEPTION"
                    and fault["exception_class"] == "java.io.IOException"
                    and fault["node"] == "client" and isinstance(fault.get("thread_id"), int))
            assert fault["door_ordinal"] == plan[0]["point"]["door_ordinal"]
            preceding = [event for event in events if event.get("type") == "DOOR_OBSERVED"
                         and event.get("site") == SITE
                         and event.get("door_ordinal") == fault["door_ordinal"]
                         and event.get("occurrence") == fault["occurrence"]
                         and event.get("thread_id") == fault["thread_id"]
                         and event["seq"] < fault["seq"]]
            assert preceding
            exits = [event["seq"] for event in events
                     if event.get("type") == "REGION_EXIT"
                     and event.get("occurrence") == fault["occurrence"]
                     and event.get("thread_id") == fault["thread_id"]
                     and event["seq"] > fault["seq"]]
            limit = min(exits) if exits else float("inf")
            later = [event for event in events if event.get("type") == "TARGET_CHECK"
                     and event.get("site") in checks
                     and event.get("node") == fault["node"]
                     and event.get("epoch") == fault["epoch"]
                     and event.get("thread_id") == fault["thread_id"]
                     and event.get("occurrence") == fault["occurrence"]
                     and fault["seq"] < event["seq"] < limit]
            for check in later:
                witnesses.append({"door_id": preceding[-1]["id"],
                                  "fault_id": fault["id"], "target_check_id": check["id"],
                                  "door_seq": preceding[-1]["seq"],
                                  "fault_seq": fault["seq"], "target_seq": check["seq"],
                                  "node": fault["node"], "epoch": fault["epoch"],
                                  "thread_id": fault["thread_id"],
                                  "occurrence": fault["occurrence"],
                                  "door_ordinal": fault["door_ordinal"]})
        rows.append({"trial_id": trial_id, **hashes,
                     "all_faults_effective": trial["feedback"]["all_faults_effective"],
                     "target_reached": trial["feedback"]["target_reached"],
                     "junit_status": trial.get("junit_validation", {}).get("status"),
                     "applied_exact_faults": len(applied),
                     "same_invocation_retry_witnesses": witnesses})
    positives = [row for row in rows if row["same_invocation_retry_witnesses"]]
    assert positives, "no exact same-invocation retry witness"
    assert all(row["all_faults_effective"] and row["target_reached"] for row in positives)
    return {"schema_version": 1, "case_id": "SOLR-01",
            "classification": "bounded_typed_io_recovery_path_proven",
            "full_campaign_promoted": False,
            "new_bug_confirmed": False,
            "source_snapshot_sha256": file_hash(source),
            "campaign_result_sha256": file_hash(result_path),
            "offline_audit_sha256": file_hash(audit_path),
            "offline_audit_gate": audit["report_gate_passed"],
            "sync_receipt_sha256": file_hash(root / "sync-receipt.json"),
            "config_sha256": file_hash(config_path),
            "fault_trials_completed": len(rows),
            "strict_same_invocation_retry_trials": [row["trial_id"] for row in positives],
            "trials": rows,
            "evidence_kind": "observed_local_timeline",
            "source_finding": "The exact ListAliases.process IOException is caught inside BaseHttpClusterStateProvider.getAliases; the loop advances to the next live node and reevaluates the original @243 guard in the same invocation. Each accepted witness requires the applied fault and later check to share named client, epoch, numeric thread, and occurrence before region exit."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = inspect(args.campaign, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": receipt["classification"],
                      "positive_trials": receipt["strict_same_invocation_retry_trials"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
