#!/usr/bin/env python3
"""Bind the SOLR-18 v38 healthy graph-path gap to immutable raw evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes())


def inspect(campaign: Path, source: Path) -> dict:
    config_path = campaign / "config.json"
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    trial = campaign / "trials/r0000"
    trial_result_path = trial / "result.json"
    pilot_path = trial / "pilot-result.json"
    config = json.loads(config_path.read_text())
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    trial_result = json.loads(trial_result_path.read_text())
    pilot = json.loads(pilot_path.read_text())
    assert config["case_id"] == result["case_id"] == "SOLR-18"
    assert result["status"] == "calibration_complete"
    assert result["healthy_seed_valid"] is True
    assert result["fault_trials_completed"] == 0
    assert pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert pilot["target_throw_count"] == 0
    assert pilot["adapter_sha256"] == "86915aa43203d934431126f9cfbe6f534125dc8a198bf7e9a074a3695d8f5947"
    assert pilot["agent_sha256"] == "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
    assert audit["campaign_result_sha256"] == file_hash(result_path)
    assert audit["archive_integrity_valid"] and audit["guidance_consistent"]
    assert audit["healthy_observed_path_doors"] == 0
    assert audit["report_gate_passed"] is False

    evidence = trial_result["events_evidence"]
    packed_path = trial / evidence["gzip_path"]
    packed = packed_path.read_bytes()
    assert sha256(packed) == evidence["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert sha256(raw) == evidence["raw_sha256"]
    assert len(raw) == evidence["raw_bytes"]
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    exact = set(config["target"]["check_sites"])
    checks = [event for event in events if event.get("type") == "TARGET_CHECK"
              and event.get("site") in exact]
    doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"
             and event.get("node") not in (None, "unknown")
             and isinstance(event.get("thread_id"), int)]
    assert len(checks) == pilot["target_check_count"] == 51
    assert all(event.get("node") in ("client", "node2")
               and isinstance(event.get("thread_id"), int) for event in checks)
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    strict_pairs = sum(graph.event_path(door, check, require_edge=True) is not None
                       for check in checks for door in doors if door["seq"] < check["seq"])
    assert strict_pairs == 0

    parents = {event["occurrence"]: event for event in events
               if event.get("type") == "REGION_ENTER"}
    doors_by_occurrence: dict[str, list[dict]] = defaultdict(list)
    for door in doors:
        doors_by_occurrence[door.get("occurrence")].append(door)
    temporal = []
    for check in checks:
        enter = parents.get(check["occurrence"])
        if enter is None:
            continue
        for door in doors_by_occurrence.get(enter.get("parent_id"), []):
            if (door["seq"] < enter["seq"] < check["seq"]
                    and door["node"] == check["node"]
                    and door.get("epoch") == check.get("epoch")
                    and door["thread_id"] == check["thread_id"]):
                temporal.append((door, check, enter))
    assert len(temporal) == len(checks)
    assert len({door["id"] for door, _, _ in temporal}) == 17
    source_text = source.read_text()
    assert "return setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in source_text
    assert "setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in source_text
    assert "zkClient.getData(ALIASES, this, stat, true)" in source_text
    assert "zkClient.getData(ALIASES, null, stat, true)" in source_text

    witness = temporal[0]
    return {
        "schema_version": 1, "case_id": "SOLR-18",
        "classification": "healthy_named_parent_io_but_no_strict_event_path",
        "fault_trials_authorized_by_this_receipt": False,
        "full_campaign_promoted": False,
        "healthy_result_sha256": file_hash(result_path),
        "offline_audit_sha256": file_hash(audit_path),
        "sync_receipt_sha256": file_hash(campaign / "sync-receipt.json"),
        "config_sha256": file_hash(config_path),
        "trial_result_sha256": file_hash(trial_result_path),
        "pilot_result_sha256": file_hash(pilot_path),
        "gzip_trace_sha256": file_hash(packed_path),
        "raw_trace_sha256": sha256(raw), "raw_trace_bytes": len(raw),
        "source_snapshot_sha256": file_hash(source),
        "exact_checks_by_actor": dict(sorted(Counter(event["node"] for event in checks).items())),
        "strict_door_target_path_pairs": strict_pairs,
        "same_actor_thread_direct_parent_door_target_pairs": len(temporal),
        "distinct_direct_parent_doors": len({door["id"] for door, _, _ in temporal}),
        "parent_door_sites": dict(sorted(Counter(door["site"] for door, _, _ in temporal).items())),
        "temporal_pair_sample": {"door_id": witness[0]["id"],
                                 "target_check_id": witness[1]["id"],
                                 "child_region_enter_id": witness[2]["id"],
                                 "node": witness[1]["node"],
                                 "epoch": witness[1]["epoch"],
                                 "thread_id": witness[1]["thread_id"]},
        "source_finding": "AliasesManager.update and process read /aliases.json through SolrZkClient.getData before calling setIfNewer. The instrumented parent REGION_ENTER precedes the DOOR, and the child REGION_ENTER follows it. The current strict event-time graph has a parent-entry edge but no event edge from the later parent DOOR to the child target; temporal co-location alone is not promoted to an observed causal path.",
    }


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
                      ("classification", "strict_door_target_path_pairs",
                       "distinct_direct_parent_doors")}, sort_keys=True))


if __name__ == "__main__":
    main()
