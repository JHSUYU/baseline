#!/usr/bin/env python3
"""Replay the prior SOLR-09 witness with current Mallory causal feedback.

This is a directed regression experiment, not a graph-discovered fuzz result.
The original DeleteReplicaTest is run in a fresh embedded cluster each time.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))

from Mallory.core import campaign  # noqa: E402

BASE_CONFIG = ROOT / "Mallory/adapters/solr/cases/SOLR-09/full-role-node1-v1/config.json"
DEFAULT_OUT = ROOT / "data/mallory/solr09_targeted_replay_v1_node0/SOLR-09"
LOCKS = ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock")
UNLOAD = ("org.apache.solr.handler.component.ShardRequestor#call()"
          "Lorg/apache/solr/handler/component/ShardResponse;@130:door:core-admin-unload")
CHILDREN = ("org.apache.solr.common.cloud.ZkStateReader$StateWatcher#refreshAndWatchChildren"
            "()V@1405:door:state-watch-getChildren")
DATA = ("org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
        "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:state-watch-getData")
ALL_DATA = ("org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
            "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
            "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:state-getData")
PLAN = [
    {"fault_id": "f0", "fault_type": "EXCEPTION", "exception_class": "java.io.IOException",
     "point": {"site": UNLOAD}},
    {"fault_id": "f1", "fault_type": "EXCEPTION",
     "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
     "point": {"site": CHILDREN, "after_fault": 0, "same_node_as": 0, "relative_hit": 1}},
    {"fault_id": "f2", "fault_type": "EXCEPTION",
     "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
     "point": {"site": DATA, "after_fault": 1, "same_node_as": 0, "relative_hit": 2}},
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_config(out: Path, plan: list[dict], data_scope: str) -> dict:
    saved = out / "config.json"
    if saved.exists():
        config = json.loads(saved.read_text(encoding="utf-8"))
        if config.get("directed_plan", PLAN) != plan:
            raise RuntimeError("the requested plan differs from this output's pinned plan")
        for item in config["runtime_artifacts"]:
            if sha256(Path(item["path"])) != item["sha256"]:
                raise RuntimeError("runtime artifact changed: " + item["path"])
        return config
    config = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    releases = out / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    agent = releases / "mallory-agent.jar"
    adapter = releases / "mallory-solr-adapter.jar"
    shutil.copy2(ROOT / "Mallory/instrumentation/target/mallory-agent.jar", agent)
    shutil.copy2(ROOT / "Mallory/adapters/solr/target/mallory-solr-adapter.jar", adapter)
    config["agent_jar"] = str(agent)
    config["agent_properties"]["adapter.jar"] = str(adapter)
    config["agent_properties"]["auto.io.doors"] = False
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(agent)
    config["env"]["MALLORY_SOLR_ADAPTER_JAR"] = str(adapter)
    includes = set(config["agent_include"])
    includes.update((
        "org.apache.solr.common.cloud.ZkStateReader",
        "org.apache.solr.common.cloud.ZkStateReader$StateWatcher",
        "org.apache.solr.handler.component.ShardRequestor",
        "org.apache.solr.handler.component.HttpShardHandler",
        "org.apache.solr.common.util.ExecutorUtil$MDCAwareThreadPoolExecutor",
    ))
    config["agent_include"] = sorted(includes)
    config["budget"]["trial_timeout_seconds"] = 480
    config["budget"]["max_faults_per_trial"] = max(
        config["budget"]["max_faults_per_trial"], len(plan))
    config["allow_node_timeline_guidance"] = True
    config["reject_coarse_roots"] = True
    config["require_event_time_paths"] = False
    config["runtime_artifacts"] = [
        {"path": str(path), "sha256": sha256(path)} for path in (agent, adapter)]
    config["replay_kind"] = "prior-witness-seeded-directed-regression"
    config["directed_plan"] = plan
    config["data_scope"] = data_scope
    campaign.atomic_json(saved, config)
    return config


def summary(out: Path, number: int) -> dict:
    rows = []
    for trial_id in range(number + 1):
        result_path = out / "trials" / f"r{trial_id:04d}" / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        feedback = result["feedback"]
        rows.append({"trial": trial_id, "elapsed_seconds": result["elapsed_seconds"],
                     "junit_status": result["junit_validation"]["status"],
                     "status": feedback["status"],
                     "all_faults_applied": feedback["all_faults_applied"],
                     "all_faults_effective": feedback["all_faults_effective"],
                     "target_reached": feedback["target_reached"],
                     "target_threw": feedback["target_threw"],
                     "target_exception_candidate": feedback["target_exception_candidate"],
                     "relative_identity_valid": feedback["relative_identity_valid"],
                     "trace_sha256": result["events_sha256"]})
    report = {"case_id": "SOLR-09", "replay_kind": "prior-witness-seeded-directed-regression",
              "requested_fault_trials": number, "completed_fault_trials": sum(r["trial"] > 0 for r in rows),
              "target_exception_candidates": sum(r["trial"] > 0 and
                                                 r["target_exception_candidate"] for r in rows),
              "trials": rows}
    campaign.atomic_json(out / "summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=8)
    parser.add_argument("--data-scope", choices=("watch", "all"), default="watch")
    parser.add_argument("--data-hit", type=int, default=2)
    parser.add_argument("--post-data-hit", type=int, default=0,
                        help="optional further state read fault after f2")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if args.data_hit < 1:
        parser.error("--data-hit must be positive")
    if args.post_data_hit < 0:
        parser.error("--post-data-hit must be nonnegative")
    out = args.output.resolve()
    plan = json.loads(json.dumps(PLAN))
    if args.data_scope == "all":
        plan[2]["point"]["site"] = ALL_DATA
    plan[2]["point"]["relative_hit"] = args.data_hit
    if args.post_data_hit:
        plan.append({"fault_id": "f3", "fault_type": "EXCEPTION",
                     "exception_class":
                         "org.apache.zookeeper.KeeperException$ConnectionLossException",
                     "point": {"site": plan[2]["point"]["site"], "after_fault": 2,
                               "same_node_as": 0, "relative_hit": args.post_data_hit}})
    out.mkdir(parents=True, exist_ok=True)
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        config = make_config(out, plan, args.data_scope)
        running = out / "running-pid.json"
        if running.exists():
            previous = json.loads(running.read_text(encoding="utf-8"))
            try:
                os.kill(previous["pid"], 0)
            except ProcessLookupError:
                running.unlink()
            else:
                raise RuntimeError("previous trial process is still alive: " + repr(previous))
        for trial_id in range(args.trials + 1):
            result_path = out / "trials" / f"r{trial_id:04d}" / "result.json"
            if not result_path.exists():
                campaign._run_trial(config, out, trial_id, [] if trial_id == 0 else plan,
                                    lambda pid: campaign.atomic_json(
                                        running, {"pid": pid, "trial": trial_id}), None)
                running.unlink(missing_ok=True)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if trial_id == 0:
                seen = {door["site"] for door in result["feedback"]["doors"]}
                needed = {UNLOAD, CHILDREN, plan[2]["point"]["site"]}
                if result["junit_validation"]["status"] != "passed" or not needed <= seen:
                    raise RuntimeError("healthy trial did not pass and expose all three doors: "
                                       + repr(sorted(needed - seen)))
            report = summary(out, args.trials)
            print(json.dumps(report["trials"][-1], sort_keys=True), flush=True)
        return 0
    finally:
        for handle in reversed(handles):
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
