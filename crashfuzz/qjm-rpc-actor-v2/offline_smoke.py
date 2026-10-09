#!/usr/bin/env python3
"""Synthetic raw-trace smoke for all three QJM V2 controllers; no JVM."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import audit_campaign_v2
import calibrate_v2
import campaign_v2
from strict_receipt import RPC, SITES


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trace_text(values: list[dict]) -> str:
    return "".join(json.dumps(value) + "\n" for value in values)


def exercise(case: str, home: Path) -> None:
    root = home / "evidence" / f"HDFS-{case}"
    registrations = [{"event": "NODE_PORT_REGISTER", "seq": i + 1,
        "port": 21000 + i, "journalNode": f"journalnode-{i}",
        "storageRoot": f"/tmp/journalnode-{i}"} for i in range(3)]
    peer = {"event": "RPC_PEER_RESOLVED", "seq": 4, "threadId": 11,
            "port": 21002, "journalNode": "journalnode-2"}
    io = {"event": "FAULT_POINT_OBSERVED", "seq": 5, "threadId": 11,
          "marker": RPC, "siteId": "Client.getRpcResponse",
          "sourceKey": "journalnode-2", "hitOrdinal": 1}
    target = {"event": "TARGET_CHECK", "seq": 6, "threadId": 22,
              "siteId": SITES[case], "journalNode": "journalnode-2",
              "journalId": "test-journal", "allowed": True,
              "epochsEqual": True, "guardWouldFail": False}
    test = ("org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" +
            campaign_v2.METHOD[case])
    for seed in ("healthy-a", "healthy-b"):
        run = root / seed
        write(run / "runtime_trace.jsonl", trace_text(registrations + [peer, io, target]))
        write(run / "jacoco.exec", "synthetic-offline-jacoco-placeholder\n")
        for kind in ("probes", "methods", "branch_counts", "lines"):
            write(run / f"covered_{kind}.txt", f"old-{kind}\n")
        write(run / "manifest.json", json.dumps({"test": test, "returncode": 0,
            "plan": None, "elapsed_seconds": 1.25,
            "trace_sha256": sha(run / "runtime_trace.jsonl"),
            "jacoco_sha256": sha(run / "jacoco.exec"),
            "coverage_sha256": {kind: sha(run / f"covered_{kind}.txt") for kind in
                ("probes", "methods", "branch_counts", "lines")},
            "overlay_probe_sha256": "probe", "overlay_client_sha256": "client"}))
    calibrate_v2.HERE = home
    first = calibrate_v2.inspect(case, "healthy-a")
    second = calibrate_v2.inspect(case, "healthy-b")
    write(root / "healthy-calibration.json", json.dumps({"pass": True,
        "case": f"HDFS-{case}", "original_junit_seeds": 2,
        "new_effective_trials": 0, "seeds": [first, second]}))
    checkpoint = root / "campaign-v2/checkpoint.json"
    state = campaign_v2.initialize(case, root, checkpoint)
    assert state["legacy_trials_imported"] == 0 and state["queue"]
    item = campaign_v2.choose(state)
    state["current"] = item
    run = root / "trial-0001-attempt-01"
    plan = [str(item["sequence"][0][key]) for key in campaign_v2.FIELDS[:-1]] + [
        "pending", item["sequence"][0]["faultType"]]
    plan_path = root / "campaign-v2/plans" / (run.name + ".tsv")
    write(plan_path, "\t".join(plan) + "\n")
    matched = {**io, "event": "FAULT_MATCHED", "seq": 6,
               "faultIndex": 0, "faultType": plan[5]}
    applied = {**io, "event": "FAULT_APPLIED", "seq": 7,
               "faultIndex": 0, "faultType": plan[5]}
    post = {**target, "seq": 8}
    trace_path = run / "runtime_trace.jsonl"
    write(trace_path, trace_text(registrations + [peer, io, matched, applied, post]))
    for kind in ("probes", "methods", "branch_counts", "lines"):
        write(run / f"covered_{kind}.txt", f"old-{kind}\nnew-{kind}\n")
    write(run / "jacoco.exec", "synthetic-offline-jacoco-placeholder\n")
    coverage_hashes = {kind: sha(run / f"covered_{kind}.txt") for kind in
                       ("probes", "methods", "branch_counts", "lines")}
    write(run / "manifest.json", json.dumps({"case_id": f"HDFS-{case}",
        "test": test, "returncode": 0, "elapsed_seconds": 1.5,
        "plan_sha256": sha(plan_path), "trace_sha256": sha(trace_path),
        "jacoco_sha256": sha(run / "jacoco.exec"),
        "coverage_sha256": coverage_hashes,
        "overlay_probe_sha256": "probe", "overlay_client_sha256": "client"}))
    row = campaign_v2.finish(state, item, root, checkpoint, case, run.name)
    assert row["effective"] and row["new_coverage_method_branch"] == 2
    resumed = campaign_v2.initialize(case, root, checkpoint)
    assert len(resumed["completed"]) == 1
    assert resumed["completed"][0]["run"] == run.name
    assert resumed["legacy_trials_imported"] == 0
    audit_campaign_v2.HERE = home
    result = audit_campaign_v2.inspect(case)
    assert result["pass"], result["errors"]
    print(f"HDFS-{case} V2 synthetic checkpoint/raw audit PASS")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="qjm-v2-offline-smoke-") as temp:
        home = Path(temp)
        for case in ("07", "09", "10"):
            exercise(case, home)


if __name__ == "__main__":
    main()
