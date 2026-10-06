#!/usr/bin/env python3
"""Admit released Journal Paxos-file hooks without repeating completed trials."""

from __future__ import annotations

import hashlib
import json

import run_campaign as campaign


PRODUCTION_HASHES = {
    "org/apache/hadoop/hdfs/qjournal/server/Journal.class":
        "a158a48590832f932dfb3149344409c5ad73f4e61803b564f40be7d44ba56a7a",
    "org/apache/hadoop/hdfs/qjournal/server/JournalNodeRpcServer.class":
        "2752e8514e57b5d1bb4810e38b1d5d742a348111f3731e099b9cbd42a7f9652a",
    "org/apache/hadoop/ipc/Client.class":
        "52063f6955cf3c9cec126bbd136951ddcd3f9a7c25ff45d965688d0a5aaafbf9",
    "org/apache/hadoop/hdfs/util/PersistentLongFile.class":
        "391357ad4237c4cb4a4c3eda7b894adbd2722fdbd32d2c78349ee311b3a8b1d9",
    "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.class":
        "d691c1828100cbb9e21027a0814ffc21636f55eec7671beed13256eb2b90b4b7",
}


def main() -> None:
    if campaign.STAGE != "multiwriter":
        raise RuntimeError("use HDFS08_STAGE=multiwriter")
    state = json.loads(campaign.STATE.read_text())
    if state.get("instrumentation_version") == "paxos_hook_v2":
        print("already enabled after", state["instrumentation_epochs"][0][
            "last_trial_before_change"], "trials")
        return
    if state["current"] is not None:
        raise RuntimeError("complete the selected in-flight trial first")
    completed = len(state["completed"])
    if completed < 1:
        raise RuntimeError("migration requires an existing v1 trial record")
    classes = campaign.CASE / "system-test/probe-classes"
    actual_hashes = {}
    for name, expected in PRODUCTION_HASHES.items():
        actual = hashlib.sha256((classes / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"production override changed: {name}")
        actual_hashes[name] = actual
    old_coverage = campaign.coverage_ids(campaign.COVERAGE)
    new_coverage = campaign.coverage_ids(
        campaign.PAXOS_HEALTHY / "coverage.tsv")
    if not new_coverage or not new_coverage.issubset(old_coverage):
        raise RuntimeError("new healthy coverage cannot be compared to v1")
    manifest = json.loads((campaign.PAXOS_HEALTHY / "manifest.json").read_text())
    if manifest["exit"] != 0 or not manifest.get("paxos"):
        raise RuntimeError("new healthy original JUnit did not pass with hook")
    trace = campaign.events(
        campaign.PAXOS_HEALTHY / "trace/runtime_trace.jsonl")
    paxos = [row for row in trace if row.get("event") == "IO_OBSERVED" and
             row.get("marker") == "PAXOS_FILE_WRITE"]
    if (len(paxos) != 6 or {row["node"] for row in paxos} !=
            {"jn0", "jn1", "jn2"} or
            {row["api"] for row in paxos} !=
            {"persistPaxosData:before", "persistPaxosData:after"}):
        raise RuntimeError("Paxos file hook identities are not complete")
    guard = [row for row in trace if row.get("event") == "TARGET_GUARD"
             and row.get("site") == campaign.TARGET_SITE and
             row.get("node") == "jn2" and
             row.get("caller") == "finalizeLogSegment" and
             row.get("segmentStartTxId") == 1 and
             row.get("segmentEndTxId") == 3 and
             row.get("requestEpoch") == 2 and
             row.get("promisedEpoch") == 2 and row.get("allowed")]
    if len(guard) != 1 or not all(row["seq"] < guard[0]["seq"] for row in paxos):
        raise RuntimeError("new Paxos I/O does not precede the exact target")
    archive = campaign.CAMPAIGN / "checkpoint-before-paxos-hook.json"
    if archive.is_file():
        raise RuntimeError("migration archive already exists")
    campaign.atomic_json(archive, state)
    for row in state["completed"]:
        if "instrumentation_version" not in row:
            row["instrumentation_version"] = "source_probes_v1"
            campaign.atomic_json(campaign.CAMPAIGN / row["trial"] /
                                 "trial-result.json", row)
    state["instrumentation_version"] = "paxos_hook_v2"
    state["instrumentation_epochs"] = [{
        "version": "paxos_hook_v2",
        "last_trial_before_change": completed,
        "first_trial_after_change": completed + 1,
        "healthy_trace": "healthy/multiwriter-paxos-probe/trace/runtime_trace.jsonl",
        "production_override_hashes_unchanged": actual_hashes,
    }]
    state["healthy_io_points_by_version"] = {
        "source_probes_v1": 54,
        "paxos_hook_v2": len([row for row in trace if campaign.relevant(row)]),
    }
    state["healthy_io_points"] = state["healthy_io_points_by_version"][
        "paxos_hook_v2"]
    added_before = len(state["queue"])
    for row in paxos:
        target = campaign.next_target_context(trace, row["seq"])
        if target is None:
            raise RuntimeError("Paxos I/O has no following exact target")
        selector = {**campaign.point(row), "exception": "IOException"}
        campaign.enqueue(state, [selector],
                         f"new healthy Paxos file I/O seq {row['seq']}",
                         campaign.base_priority(row) + 3, target)
    new_seeds = len(state["queue"]) - added_before
    if new_seeds != 6:
        raise RuntimeError(f"expected six Paxos seeds, got {new_seeds}")
    campaign.atomic_json(campaign.STATE, state)
    evidence = {
        "case_id": "HDFS-08", "stage": "multiwriter",
        "last_completed_before_change": completed,
        "first_paxos_hook_trial": completed + 1,
        "completed_junits_replayed": 0,
        "new_paxos_io_points": new_seeds,
        "healthy_io_points_old": 54,
        "healthy_io_points_new": state["healthy_io_points"],
        "old_healthy_coverage_ids": len(old_coverage),
        "new_healthy_coverage_ids": len(new_coverage),
        "new_healthy_coverage_not_in_old": len(new_coverage - old_coverage),
        "production_override_hashes_unchanged": actual_hashes,
        "new_healthy_original_junit_exit": manifest["exit"],
        "exact_target_context": campaign.next_target_context(trace, paxos[-1]["seq"]),
        "paxos_nodes": sorted({row["node"] for row in paxos}),
        "paxos_apis": sorted({row["api"] for row in paxos}),
        "recorded_at_utc": campaign.now(),
    }
    campaign.atomic_json(campaign.CAMPAIGN / "recorder-migration.json", evidence)
    campaign.persist(state)
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
