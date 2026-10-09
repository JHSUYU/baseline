#!/usr/bin/env python3
"""Verify why a retryable HTTP exception cannot replay SOLR-37's subshard request."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_line(path: Path, number: int) -> str:
    return path.read_text().splitlines()[number - 1]


def inspect(base: Path, source_root: Path) -> dict:
    processor = source_root / "solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java"
    distributor = source_root / "solr/core/src/java/org/apache/solr/update/SolrCmdDistributor.java"
    junit = source_root / "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"
    healthy = base / "data/mallory/calibration_v29a_lane3/SOLR-37"
    pilot = base / "data/mallory/pilot_v29p_lane3/SOLR-37"
    path_sidecar = base / "data/mallory/audit_sidecars/SOLR-37-v29p-postfault-paths.json"
    prior_gap = base / "data/mallory/quality_reviews/solr37_v29p_gap/SOLR-37.json"
    healthy_result = json.loads((healthy / "result.json").read_text())
    pilot_result = json.loads((pilot / "result.json").read_text())
    paths = json.loads(path_sidecar.read_text())
    assert healthy_result["case_id"] == pilot_result["case_id"] == "SOLR-37"
    assert healthy_result["status"] == "calibration_complete"
    assert healthy_result["healthy_junit_validation"]["status"] == "passed"
    assert healthy_result["trials"][0]["target_reached"] is True
    assert pilot_result["status"] == "budget_exhausted"
    assert pilot_result["fault_trials_completed"] == 8
    assert pilot_result["strict_injected_trials"] == pilot_result["strict_target_trials"] == 7
    assert paths["trials_with_time_respecting_observed_path"] == 0
    assert "cmdDistrib.distribAdd(cmd, subShardLeaders, params, true)" in source_line(processor, 261)
    assert "doDefensiveChecks(phase)" in source_line(processor, 655)
    assert "new SolrCmdDistributor.StdNode(nodeProps, coll.getName(), aslice.getName())" in source_line(processor, 885)
    assert "this(nodeProps, collection, shardId, 0)" in source_line(distributor, 497)
    assert "this.retry = maxRetries > 0" in source_line(distributor, 504)
    assert "if (!retry) return false" in source_line(distributor, 528)
    assert "return isRetry && retries < node.getMaxRetries()" in source_line(distributor, 389)
    assert "SocketTimeoutException" in source_line(distributor, 552)
    assert "@Nightly" in source_line(junit, 99)
    assert "public void test()" in source_line(junit, 100)
    return {
        "schema_version": 1, "case_id": "SOLR-37",
        "classification": "subshard_http_fault_has_no_configured_retry",
        "full_campaign_promoted": False, "new_bug_confirmed": False,
        "source_paths": {
            "processor": {"path": str(processor.relative_to(source_root)), "sha256": sha(processor)},
            "distributor": {"path": str(distributor.relative_to(source_root)), "sha256": sha(distributor)},
            "cluster_test": {"path": str(junit.relative_to(source_root)), "sha256": sha(junit)},
        },
        "healthy_result_sha256": sha(healthy / "result.json"),
        "healthy_audit_sha256": sha(healthy / "offline-causal-audit.json"),
        "pilot_result_sha256": sha(pilot / "result.json"),
        "pilot_audit_sha256": sha(pilot / "offline-causal-audit.json"),
        "pilot_postfault_path_sidecar_sha256": sha(path_sidecar),
        "prior_gap_receipt_sha256": sha(prior_gap),
        "pilot_fault_trials": 8, "pilot_strict_applied": 7,
        "pilot_strict_target_retained_any_request": 7,
        "pilot_time_respecting_fault_to_target_paths": 0,
        "source_finding": (
            "The selected ShardSplitTest#test sends a parent-to-subshard FROMLEADER update "
            "through DistributedZkUpdateProcessor.doDistribAdd:253-261. "
            "getSubShardLeaders constructs the three-argument SolrCmdDistributor.StdNode "
            "at line 885. Its constructor sets maxRetries=0 (SolrCmdDistributor:496-505), "
            "so checkRetry returns false at line 528 even for SocketTimeoutException. "
            "The sending node runs doDefensiveChecks at processor:655 before its "
            "later forwarding I/O; the receiver can check the subshard range only "
            "after it receives that forwarded request. The prior plain IOException pilot observed "
            "later checks in other request contexts, but no fault-to-target path."
        ),
        "next_step": (
            "Do not run a typed SocketTimeoutException pilot for this same subshard Req. "
            "A different existing test or a separately justified background I/O path "
            "needs a fresh healthy proof before any fault campaign."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    row = inspect(args.base, args.source_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": row["case_id"], "classification": row["classification"]}, sort_keys=True))


if __name__ == "__main__":
    main()
