#!/usr/bin/env python3
"""Stage bounded, source-pinned Solr healthy trials without running a JVM.

The eight source configs are copied into this isolated directory so dispatch
can review each candidate. This script intentionally never edits a live case,
release, source checkout, or canonical checklist.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parents[4]
CASES = HERE.parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
PINNED_COMMIT = "e27f44e3d78dfcec230c97e0a1240e3751daeff9"

SEEDS = {
    "SOLR-01": "config-v10-state-lane1-junit.json",
    "SOLR-09": "config-v19-lane1-calibration.json",
    "SOLR-13": "config-v23-configset-auth-healthy.json",
    "SOLR-14": "config-v19-lane1-calibration.json",
    "SOLR-18": "config-v19-lane1-calibration.json",
    "SOLR-38": "config-v24-lane1-calibration.json",
    "SOLR-39": "config-v23-configset-auth-healthy.json",
    "SOLR-40": "config-v23-configset-auth-healthy.json",
}

TEST_LINES = {
    "SOLR-01": [197, 242],
    "SOLR-09": [149, 170],
    "SOLR-13": [282, 302],
    "SOLR-14": [76, 92],
    "SOLR-18": [439, 504],
    "SOLR-37": [98, 112],
    "SOLR-38": [197, 242],
    "SOLR-39": [106, 139],
    "SOLR-40": [106, 139],
}

GUARD_NOTES = {
    "SOLR-01": "HTTP client loops over live nodes for LISTALIASES; the exception needs every attempt to fail.",
    "SOLR-09": "Synchronous DELETE replica checks that core-node deletion became visible; an asynchronous deletion takes another branch.",
    "SOLR-13": "Time-routed alias update synchronously creates a collection, refreshes aliases, and checks the new collection is listed.",
    "SOLR-14": "Overseer finds the parent-shard leader, then checks its live-node znode still exists before splitting.",
    "SOLR-18": "Under enabled assertions, equal alias ZK versions must carry identical serialized alias contents.",
    "SOLR-37": "A receiving subshard leader checks that its hash range is contained by the parent shard range on FROMLEADER updates.",
    "SOLR-38": "An update handler retries local leader state before comparing it with the cluster-state leader designation.",
    "SOLR-39": "Routed alias leader lookup checks that the alias still maps to a collection list.",
    "SOLR-40": "Routed alias update setup checks that the alias still has routing properties.",
}

TEST_NOTES = {
    "SOLR-01": "CloudHttp2SolrClientTest creates aliases and issues queries through the HTTP-backed client.",
    "SOLR-09": "DeleteReplicaTest deletes the leader replica, waits for its replacement, and checks directories were removed.",
    "SOLR-13": "testPreemptiveCreation first calls addOneDocSynchCreation, which writes to future time buckets and waits for synchronous collection creation (helper lines 588-599).",
    "SOLR-14": "SplitShardTest creates a two-shard collection and synchronously splits shard1.",
    "SOLR-18": "AliasIntegrationTest creates, changes, and deletes aliases while waiting for ZK alias versions.",
    "SOLR-37": "ShardSplitTest performs several split scenarios and produced exact target hits in a prior trace, but that trace was truncated.",
    "SOLR-38": "CloudHttp2SolrClientTest sends distributed updates while alias operations run.",
    "SOLR-39": "TimeRoutedAliasUpdateProcessorTest creates a time-routed alias and indexes documents through it.",
    "SOLR-40": "TimeRoutedAliasUpdateProcessorTest creates a time-routed alias and indexes documents through it.",
}

ARCHIVED = {
    "SOLR-01": "data/mallory/calibration_v4/SOLR-01/result.json",
    "SOLR-09": "data/mallory/calibration_v10_lane1/SOLR-09/result.json",
    "SOLR-13": "data/mallory/calibration_v10_lane1_remaining/SOLR-13/result.json",
    "SOLR-14": "data/mallory/calibration_v10_lane1/SOLR-14/result.json",
    "SOLR-18": "data/mallory/calibration_v10_lane1/SOLR-18/result.json",
    "SOLR-37": "data/mallory/calibration_v14a_config_lane1/SOLR-37/result.json",
    "SOLR-38": "data/mallory/calibration_v24_lane1/SOLR-38/result.json",
    "SOLR-39": "data/mallory/calibration_v10_lane1_remaining/SOLR-39/result.json",
    "SOLR-40": "data/mallory/calibration_v10_lane1_remaining/SOLR-40/result.json",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def localize(path: str) -> str:
    """Use the clean pinned checkout when an old disposable worktree vanished."""
    if "/.mallory-worktrees/" in path:
        for marker in ("solr/core/src/test/", "solr/solrj/src/test/"):
            if marker in path:
                return str(SOURCE / (marker + path.split(marker, 1)[1]))
    return path


def stage_config(case_id: str, source_name: str) -> tuple[str, str]:
    seed = CASES / case_id / source_name
    config = copy.deepcopy(json.loads(seed.read_text()))
    config["command"] = [str(SOURCE) if part.startswith("/users/ZhenyuLi/.mallory-worktrees/solr") else part
                         for part in config["command"]]
    config["cwd"] = str(SOURCE)
    config["source_equivalent_root"] = str(SOURCE)
    config["budget"] = {"trials": 1, "seconds": 900,
                        "trial_timeout_seconds": 480, "max_faults_per_trial": 1}
    config["calibration_only"] = True
    config["auto_promote_if_healthy"] = False
    config["revision"] = "pending-solr-source-triage-v1-healthy-only"
    config["triage_seed_config"] = str(seed.relative_to(BASELINE))
    config["triage_seed_sha256"] = sha(seed)
    for artifact in config.get("runtime_artifacts", []):
        artifact["path"] = localize(artifact["path"])
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise RuntimeError(f"runtime artifact mismatch for {case_id}: {path}")
    if not SOURCE.is_dir():
        raise RuntimeError(f"source checkout missing: {SOURCE}")
    output = HERE / f"{case_id}.healthy.json"
    output.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    return str(output.relative_to(BASELINE)), sha(output)


def main() -> None:
    inventory = json.loads((BASELINE / "Mallory/cases/inventory.json").read_text())
    checklist = json.loads((BASELINE / "data/mallory/checklist102.json").read_text())
    inventory_rows = {row["case_id"]: row for row in inventory["cases"]}
    check_rows = {row["case_id"]: row for row in checklist["rows"]}
    import subprocess
    observed_commit = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if observed_commit != PINNED_COMMIT:
        raise RuntimeError(f"source commit mismatch: {observed_commit}")
    if subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"], text=True).strip():
        raise RuntimeError("source checkout is dirty")
    rows = []
    for case_id in [*SEEDS, "SOLR-37"]:
        row = check_rows[case_id]
        inv = inventory_rows[case_id]
        workload = inv["workload"]
        target_source = SOURCE / row["source_path"]
        test_source = SOURCE / workload["test_source_path"]
        if not target_source.is_file() or not test_source.is_file():
            raise RuntimeError(f"missing pinned source for {case_id}")
        archive = BASELINE / ARCHIVED[case_id]
        archived = json.loads(archive.read_text())
        config_path, config_sha = stage_config(case_id, SEEDS[case_id]) if case_id in SEEDS else (None, None)
        rows.append({
            "case_id": case_id,
            "target": {"source_path": row["source_path"], "source_line": row["source_line"],
                       "function": row["function"], "source_sha256": sha(target_source),
                       "guard": GUARD_NOTES[case_id]},
            "cluster_test": {"selector": workload["selected_selector"],
                             "source_path": workload["test_source_path"],
                             "source_lines": TEST_LINES[case_id],
                             "source_sha256": sha(test_source),
                             "operation": TEST_NOTES[case_id]},
            "archived_healthy": {"result_path": ARCHIVED[case_id], "result_sha256": sha(archive),
                                 "status": archived.get("status"),
                                 "junit_status": (archived.get("healthy_junit_validation") or {}).get("status"),
                                 "target_node_named": archived.get("target_node_named"),
                                 "duration_seconds": archived.get("duration_seconds"),
                                 "healthy_eligible_doors": archived.get("healthy_eligible_doors"),
                                 "closure_edges": archived.get("closure_edge_fingerprints_seen")},
            "staged_healthy_config": config_path,
            "staged_healthy_config_sha256": config_sha,
            "state": ("existing_exact_hit_trace_truncated; SOLR-37 owned by solr_adapter"
                      if case_id == "SOLR-37" else
                      "source_mapped_configset_auth_overlay_awaiting_healthy_probe"
                      if case_id in {"SOLR-13", "SOLR-39", "SOLR-40"} else
                      "exact_healthy_hit_archived; causal_admission_pending"),
        })
    manifest = {"schema_version": 1, "source_commit": PINNED_COMMIT,
                "scope": "source-only triage; no JVM run, fault trial, or checklist mutation",
                "cases": rows}
    (HERE / "triage.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
