#!/usr/bin/env python3
"""Pin the v37 Solr unregistered reader identity gap to exact healthy trace and audit."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(root: Path) -> dict:
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    sync_path = root / "sync-receipt.json"
    trial = root / "trials/r0000"
    pilot_path = trial / "pilot-result.json"
    trace_path = trial / "events.jsonl.gz"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    pilot = json.loads(pilot_path.read_text())
    assert result["case_id"] == "SOLR-18" and result["status"] == "calibration_complete"
    assert pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert pilot["adapter_sha256"] == "2fc81200cff69abc93b608484805fe4bdf88ff3074a46fe7142221dfd0b2ce50"
    assert audit["report_gate_passed"] is False
    assert audit["healthy_observed_path_doors"] == 0
    raw = gzip.decompress(trace_path.read_bytes())
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    nodes = Counter(event.get("node") for event in events
                    if event.get("type") == "TARGET_CHECK")
    gaps = Counter(event.get("reason") for event in events
                   if event.get("type") == "NODE_IDENTITY_GAP")
    assert nodes["unknown"] == 3 and nodes["node1"] == 36 and nodes["client"] == 12
    assert gaps["unregistered_receiver"] >= 23
    return {"schema_version": 1, "case_id": "SOLR-18",
            "classification": "v37_unregistered_enclosing_reader_identity_gap",
            "full_campaign_promoted": False,
            "result_sha256": digest(result_path),
            "offline_audit_sha256": digest(audit_path),
            "sync_receipt_sha256": digest(sync_path),
            "pilot_result_sha256": digest(pilot_path),
            "gzip_trace_sha256": digest(trace_path),
            "raw_trace_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_trace_bytes": len(raw),
            "exact_check_counts_by_actor": dict(nodes),
            "identity_gaps": dict(gaps),
            "healthy_observed_path_doors": 0,
            "source_finding": "The watcher TASK_SUBMIT and TASK_CLAIM are named client, but the enclosing ZkStateReader at setIfNewer is unregistered; its SolrZkClient has a uniquely registered actor that can be checked at this boundary",
            "fault_trials_authorized_by_this_receipt": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "identity_gaps": report["identity_gaps"]}, sort_keys=True))


if __name__ == "__main__":
    main()
