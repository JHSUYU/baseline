#!/usr/bin/env python3
"""Pin the SOLR-14 direct-door exception control-flow gap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(calibration: Path, source: Path, source_review: Path,
            staged_config: Path) -> dict:
    result_path = calibration / "result.json"
    audit_path = calibration / "offline-causal-audit.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    config = json.loads((calibration / "config.json").read_text())
    next_config = json.loads(staged_config.read_text())
    assert config["case_id"] == result["case_id"] == next_config["case_id"] == "SOLR-14"
    assert result["status"] == "calibration_complete"
    assert result["healthy_seed_valid"] and result["healthy_junit_validation"]["status"] == "passed"
    assert result["target_binding"]["nodes"] == ["node1"]
    assert audit["campaign_result_sha256"] == sha(result_path)
    assert audit["healthy_closure_included_named_doors"] == 15
    assert next_config["calibration_only"] is True
    assert sha(source) == next_config["mapping"]["target_source_sha256"]
    lines = source.read_text().splitlines()
    assert "public boolean split(" in lines[105] and "throws Exception" in lines[105]
    assert "getZkClient().exists(" in lines[163]
    assert "if (leaderZnodeStat == null)" in lines[164]
    assert "try {" in lines[148] and "catch (InterruptedException e)" in lines[150]
    assert "try {" in lines[192]  # the broad catch begins after the selected guard
    assert not any("catch (" in line for line in lines[151:164])
    return {"schema_version": 1, "case_id": "SOLR-14",
            "classification": "source_proven_direct_door_aborts_before_target",
            "full_campaign_promoted": False, "fault_pilot_authorized": False,
            "new_bug_confirmed": False,
            "prior_healthy_result_sha256": sha(result_path),
            "prior_healthy_audit_sha256": sha(audit_path),
            "prior_config_sha256": sha(calibration / "config.json"),
            "prior_source_review_sha256": sha(source_review),
            "staged_future_healthy_config_sha256": sha(staged_config),
            "staged_future_healthy_executed": False,
            "source_sha256": sha(source),
            "source_finding": ("SplitShardCmd.split calls SolrZkClient.exists at line 164 "
                               "immediately before the exact line-165 null-stat guard. "
                               "The only preceding local catch handles InterruptedException "
                               "from getLeaderRetry; the broad split try/catch begins at "
                               "line 193. An injected ConnectionLossException at exists "
                               "therefore leaves the split invocation before this guard."),
            "next_step": "A distinct caught or retrying upstream door would need a new healthy and postfault pilot."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-review", required=True, type=Path)
    parser.add_argument("--staged-config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    row = inspect(args.calibration, args.source, args.source_review, args.staged_config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": row["classification"],
                      "fault_pilot_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
