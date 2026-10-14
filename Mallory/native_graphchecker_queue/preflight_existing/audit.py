"""Read-only preflight for four already launched native campaigns.

Run from the repository root. This script never starts or resumes a campaign,
creates a queue receipt, or writes to a campaign directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from Mallory.native_graphchecker_campaign.campaign import _validate_config
from Mallory.native_graphchecker_dispatch.checklist import (
    _native_case_files, load_inventory, load_ownership,
)
from Mallory.native_graphchecker_queue.queue import (
    obj, sha, validate_isolation,
)


CASES = ("ZOOKEEPER-07", "HDFS-11", "SOLR-01", "HBASE-02")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA_ARG = {
    "ZOOKEEPER-07": "build.test.dir",
    "HDFS-11": "test.build.data",
    "SOLR-01": "solr.log.dir",
    "HBASE-02": "build.test.dir",
}


def audit() -> dict:
    inventory = ROOT / "Mallory/cases/inventory.json"
    cases, by_id = load_inventory(inventory)
    items = {item["case_id"]: item for item in cases}
    owners = load_ownership(HERE / "native-ownership.draft.json", set(by_id))
    profile = obj(HERE / "isolation.draft.json")
    results = []
    seen_state: set[str] = set()
    seen_workdir: set[str] = set()
    for case_id in CASES:
        item = items[case_id]
        config_path, state = _native_case_files(item, HERE / "bindings",
                                                 Path("/unused/draft-state"))
        config = obj(config_path)
        _validate_config(config)
        checkpoint = obj(state / "checkpoint.json")
        if (checkpoint.get("case_id") != config["case_id"] or
                checkpoint.get("config_sha256") != sha(config_path)):
            raise ValueError(f"checkpoint/config identity differs: {case_id}")
        if checkpoint.get("terminal") and not (state / "summary.json").is_file():
            raise ValueError(f"terminal checkpoint lacks native summary: {case_id}")
        if str(state) in seen_state:
            raise ValueError("two inventory cases share a native state root")
        seen_state.add(str(state))
        workdir = state / "trials/r0000/iteration-native/workdir"
        process_files = sorted((state / "trials").glob("r*/process.json"))
        if not process_files:
            raise ValueError(f"no original JUnit process receipts: {case_id}")
        for process_file in process_files:
            trial_workdir = process_file.parent / "iteration-native/workdir"
            if not trial_workdir.is_dir() or str(trial_workdir) in seen_workdir:
                raise ValueError(f"missing or shared JUnit workdir: {process_file}")
            seen_workdir.add(str(trial_workdir))
            argv = obj(process_file).get("argv", [])
            if (f"-Djava.io.tmpdir={trial_workdir}" not in argv or
                    f"-D{DATA_ARG[case_id]}={trial_workdir}" not in argv):
                raise ValueError(f"JUnit trial lacks isolated scratch: {process_file}")
        weave = obj(Path(config["native_weave_config"]))
        receipt = obj(Path(weave["output_classes"]) /
                      "native-original-weave-receipt.json")
        engine = Path(receipt["engine_jar"])
        if sha(engine) != receipt["engine_jar_sha256"]:
            raise ValueError(f"pinned engine jar changed: {case_id}")
        try:
            isolation = validate_isolation(profile, item["system"], case_id,
                                           config, owners, owners[case_id])
            isolation_status = isolation["mode"]
        except (OSError, ValueError, KeyError) as failure:
            isolation_status = f"gap: {type(failure).__name__}: {failure}"
        results.append({
            "case_id": case_id, "owner": owners[case_id],
            "native_case_id": config["case_id"],
            "config_path": str(config_path),
            "config_sha256": sha(config_path),
            "state_path": str(state),
            "checkpoint_sha256": sha(state / "checkpoint.json"),
            "checkpoint_status": checkpoint.get("status"),
            "checkpoint_terminal": checkpoint.get("terminal"),
            "completed_fault_trials": checkpoint.get("completed_fault_trials"),
            "summary_present": (state / "summary.json").is_file(),
            "first_trial_workdir": str(workdir),
            "isolated_junit_process_receipts": len(process_files),
            "engine_root": str(engine.parent.parent),
            "engine_jar_sha256": sha(engine),
            "port_policy": isolation_status,
            "adopt_now": False,
        })
    hdfs_proof = obj(Path(
        "/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs11-native-campaign-v2/"
        "node0-isolation-proof.json"))
    zk = profile["systems"]["zookeeper"]["ports"]["cases"]["ZOOKEEPER-07"]
    lower, upper = zk["start"], zk["start"] + zk["count"] - 1
    observed = {port for trial in hdfs_proof[
        "hdfs_completed_trial_port_observations"]
        for port in trial["observed_bound_ports"]}
    if any(lower <= port <= upper for port in observed):
        raise ValueError("HDFS observed a port in ZK07 assigned range")
    if hdfs_proof["host_ephemeral_port_range"][0] <= upper:
        raise ValueError("ZK07 assigned range intersects host ephemeral range")
    hdfs_review_path = Path(
        "/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs11-native-campaign-v2/"
        "terminal-review.json")
    hdfs_review = obj(hdfs_review_path)
    if (hdfs_review.get("status") != "budget_terminal_not_high_quality_complete" or
            hdfs_review.get("fault_trials") != 24 or
            hdfs_review.get("checked_strict_target_retained") != 15 or
            hdfs_review.get("target_exception_triggered") != 0 or
            hdfs_review.get("new_closure_edge_families_sum") != 0 or
            hdfs_review.get("checkpoint_sha256") != sha(Path(
                "/proj/silentfailure-PG0/ZhenyuLi/"
                "mallory-hdfs11-native-campaign-v2/campaign/checkpoint.json"))):
        raise ValueError("HDFS-11 terminal review changed or lost its limitation")
    return {"schema_version": 1, "mode": "read_only_native_binding_preflight",
            "inventory_sha256": sha(inventory),
            "ownership_sha256": sha(HERE / "native-ownership.draft.json"),
            "case_count": len(results), "cases": results,
            "hdfs_terminal_review": {
                "path": str(hdfs_review_path),
                "sha256": sha(hdfs_review_path),
                "status": hdfs_review["status"],
                "strict_target_retained_trials": 15,
                "target_exception_triggered": 0,
                "new_closure_edge_families_sum": 0,
            },
            "node0_port_check": {
                "zookeeper_reserved_range": [lower, upper],
                "host_ephemeral_range": hdfs_proof["host_ephemeral_port_range"],
                "hdfs_observed_ports": len(observed),
                "observed_overlap": sorted(
                    port for port in observed if lower <= port <= upper),
                "source_proof_sha256": sha(Path(
                    "/proj/silentfailure-PG0/ZhenyuLi/"
                    "mallory-hdfs11-native-campaign-v2/node0-isolation-proof.json")),
            }}


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True, indent=2))
