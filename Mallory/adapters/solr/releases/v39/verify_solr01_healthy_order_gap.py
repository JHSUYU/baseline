#!/usr/bin/env python3
"""Verify exact SOLR-01 LISTALIASES door ordering in a healthy cluster test."""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return digest(path.read_bytes())


def inspect(root: Path, source: Path) -> dict:
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    config_path = root / "config.json"
    trial = root / "trials/r0000"
    trial_result_path = trial / "result.json"
    pilot_path = trial / "pilot-result.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    config = json.loads(config_path.read_text())
    trial_result = json.loads(trial_result_path.read_text())
    pilot = json.loads(pilot_path.read_text())
    assert config["case_id"] == result["case_id"] == "SOLR-01"
    assert result["status"] == "calibration_complete" and result["healthy_seed_valid"]
    assert result["fault_trials_completed"] == 0
    assert pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert pilot["adapter_sha256"] == "86915aa43203d934431126f9cfbe6f534125dc8a198bf7e9a074a3695d8f5947"
    assert pilot["agent_sha256"] == "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
    assert pilot["target_throw_count"] == 0
    assert audit["campaign_result_sha256"] == file_hash(result_path)
    assert audit["archive_integrity_valid"] and audit["guidance_consistent"]
    assert audit["healthy_observed_path_doors"] == 0 and not audit["report_gate_passed"]

    evidence = trial_result["events_evidence"]
    packed_path = trial / evidence["gzip_path"]
    packed = packed_path.read_bytes()
    assert digest(packed) == evidence["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert digest(raw) == evidence["raw_sha256"] and len(raw) == evidence["raw_bytes"]
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    target_sites = set(config["target"]["check_sites"])
    checks = [e for e in events if e.get("type") == "TARGET_CHECK"
              and e.get("site") in target_sites]
    direct_doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                    and "BaseHttpClusterStateProvider#getAliases" in str(e.get("site"))
                    and e.get("exception_class") == "java.io.IOException"]
    assert len(checks) == len(direct_doors) == pilot["target_check_count"] == 15
    assert all(e.get("node") == "client" and isinstance(e.get("thread_id"), int)
               for e in checks + direct_doors)
    by_occurrence: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"checks": [], "doors": []})
    for check in checks:
        by_occurrence[check["occurrence"]]["checks"].append(check)
    for door in direct_doors:
        by_occurrence[door["occurrence"]]["doors"].append(door)
    assert len(by_occurrence) == 15
    assert all(len(row["checks"]) == len(row["doors"]) == 1
               and row["checks"][0]["seq"] < row["doors"][0]["seq"]
               and row["checks"][0]["thread_id"] == row["doors"][0]["thread_id"]
               for row in by_occurrence.values())
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    strict_paths = sum(graph.event_path(door, check, require_edge=True) is not None
                       for door in direct_doors for check in checks)
    assert strict_paths == 0
    source_text = source.read_text()
    assert 'new CollectionAdminRequest.ListAliases().process(client)' in source_text
    assert 'catch (SolrServerException | RemoteSolrException | IOException e)' in source_text
    assert file_hash(source) == config["mapping"]["target_source_sha256"]

    first = min(by_occurrence.values(), key=lambda row: row["checks"][0]["seq"])
    return {"schema_version": 1, "case_id": "SOLR-01",
            "classification": "healthy_direct_listaliases_door_after_exact_retry_guard",
            "fault_trials_authorized_by_this_receipt": False,
            "full_campaign_promoted": False,
            "healthy_result_sha256": file_hash(result_path),
            "offline_audit_sha256": file_hash(audit_path),
            "sync_receipt_sha256": file_hash(root / "sync-receipt.json"),
            "config_sha256": file_hash(config_path),
            "pilot_result_sha256": file_hash(pilot_path),
            "trial_result_sha256": file_hash(trial_result_path),
            "gzip_trace_sha256": file_hash(packed_path),
            "raw_trace_sha256": digest(raw), "raw_trace_bytes": len(raw),
            "source_snapshot_sha256": file_hash(source),
            "named_exact_check_count": len(checks),
            "named_caught_io_door_count": len(direct_doors),
            "healthy_same_invocation_postdoor_exact_checks": 0,
            "strict_door_target_path_pairs": strict_paths,
            "first_guard_door_pair": {"check_id": first["checks"][0]["id"],
                                      "door_id": first["doors"][0]["id"],
                                      "node": "client", "thread_id": first["checks"][0]["thread_id"]},
            "source_finding": "The exact @243 loop guard executes before the LISTALIASES process call in each healthy invocation. IOException from that call is caught and can cause a later loop iteration, but the healthy trace has one successful attempt per invocation and thus no post-door target check or strict observed path. A fault pilot is not promoted from this healthy seed."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = inspect(args.campaign, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in
                      ("classification", "named_exact_check_count",
                       "named_caught_io_door_count", "strict_door_target_path_pairs")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
