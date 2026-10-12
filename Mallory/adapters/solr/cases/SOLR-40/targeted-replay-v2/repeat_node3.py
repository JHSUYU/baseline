#!/usr/bin/env python3
"""Replay the one node3 first-watch plan in ten fresh Solr JUnit clusters."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from Mallory.core import campaign  # noqa: E402

BASE = ROOT / "data/mallory/solr40_targeted_replay_v2_node0/SOLR-40"
OUT = ROOT / "data/mallory/solr40_node3_first_watch_replay_v1_node0/SOLR-40"
SOURCE = BASE / "trials/r0007/plan.json"
LOCKS = ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    plan = json.loads(SOURCE.read_text())["faults"]
    assert len(plan) == 1
    point = plan[0]["point"]
    assert (point["node"], point["epoch"], point["door_ordinal"]) == (
        "node3", 0, 1)
    assert point["site"] == (
        "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
        "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
    assert plan[0]["exception_class"] == (
        "org.apache.zookeeper.KeeperException$ConnectionLossException")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "case_id": "SOLR-40",
        "classification": "prior-witness-seeded exact-plan replay; not Mallory auto-discovery",
        "source_plan": str(SOURCE),
        "source_plan_sha256": sha(SOURCE),
        "config_sha256": sha(config_path),
        "agent_jar_sha256": sha(Path(config["agent_jar"])),
        "original_cluster_junit": config["cluster_test"],
        "plan": plan,
        "requested_replays": 10,
    }
    manifest_path = OUT / "replay-manifest.json"
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text()) == manifest
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        for trial_id in range(1, 11):
            trial = OUT / "trials" / f"r{trial_id:04d}"
            result_path = trial / "result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if result.get("plan") != plan:
                    raise ValueError(f"plan drift: {trial}")
            elif trial.exists():
                raise ValueError(f"incomplete trial requires manual review: {trial}")
            else:
                result = campaign._run_trial(config, OUT, trial_id, plan,
                                             lambda pid: None, None)
            feedback = result.get("feedback") or {}
            print(json.dumps({"trial": trial_id,
                              "fault_applied": feedback.get("all_faults_applied"),
                              "target_exception_candidate":
                              feedback.get("target_exception_candidate"),
                              "junit_status":
                              (result.get("junit_validation") or {}).get("status"),
                              "feedback_status": feedback.get("status")},
                             sort_keys=True), flush=True)
    finally:
        for handle in reversed(handles):
            handle.close()


if __name__ == "__main__":
    main()
