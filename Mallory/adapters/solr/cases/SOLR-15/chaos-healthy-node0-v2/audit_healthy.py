#!/usr/bin/env python3
"""Audit the original chaos JUnit and the second leader-znode read handoff."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

SPLIT = ("org.apache.solr.cloud.api.collections.SplitShardCmd#split"
         "(Lorg/apache/solr/common/cloud/ClusterState;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;"
         "Lorg/apache/solr/common/util/NamedList;)Z")
FIRST = SPLIT + "@164:door:2"
SECOND = SPLIT + "@523:door:3"
CHECK = SPLIT + "@536:branch:40"
THROW = SPLIT + "@538:throw:1"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2"
          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
          "Lorg/apache/zookeeper/data/Stat;@301:door:1")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
ROLE = re.compile(r"MALLORY_SOLR_NODE logical=(control|shard-[1-9][0-9]*) "
                  r"physical=([^\s]+) epoch=([0-9]+)")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_split(first: dict, second: dict) -> bool:
    return all(first.get(k) == second.get(k) for k in
               ("node", "epoch", "occurrence", "thread", "context"))


def _same_thread(first: dict, second: dict) -> bool:
    return all(first.get(k) == second.get(k) for k in
               ("node", "epoch", "thread", "context"))


def attest(output: Path) -> dict:
    output = output.resolve()
    result = json.loads((output / "result.json").read_text())
    trial = json.loads((output / "trials/r0000/result.json").read_text())
    trial_dir = output / "trials/r0000"
    junit = result.get("healthy_junit_validation") or {}
    feedback = trial.get("feedback") or {}
    validation = trial.get("site_catalog_validation") or {}
    catalog = [json.loads(line) for line in
               (trial_dir / "sites.jsonl").read_text().splitlines() if line]
    rows = {row.get("site"): row for row in catalog}
    trace_path = trial_dir / "events.jsonl.gz"
    events = []
    with gzip.open(trace_path, "rt") as stream:
        for line in stream:
            event = json.loads(line)
            if (event.get("type") == "DOOR_OBSERVED"
                    or event.get("site") in (CHECK, THROW)):
                events.append(event)
    role_lines = ROLE.findall((trial_dir / "junit.log").read_text(errors="replace"))
    roles = {(logical, int(epoch)): physical for logical, physical, epoch in role_lines}
    reasons = []
    if result.get("status") != "calibration_complete" or result.get("fault_trials_completed") != 0:
        reasons.append("healthy_campaign_not_calibration_complete")
    if trial.get("plan") != [] or trial.get("return_code") != 0:
        reasons.append("healthy_trial_has_fault_or_failed")
    if not (junit.get("status") == "passed" and junit.get("tests") == 1
            and junit.get("failures") == 0 and junit.get("errors") == 0):
        reasons.append("original_cluster_junit_not_1_0_0")
    if not (result.get("bootstrap_seed_valid") is True
            and result.get("runtime_attestation", {}).get("valid") is True
            and feedback.get("status") == "healthy_target_missing"):
        reasons.append("healthy_target_absent_bootstrap_invalid")
    if not (validation.get("valid") is True and validation.get("class_hash_match") is True
            and {FIRST, SECOND, CHECK, THROW, NATIVE} <= rows.keys()):
        reasons.append("exact_loaded_sites_missing")
    if feedback.get("trace_truncated") is not False:
        reasons.append("trace_truncated")
    if any(e.get("type") in ("TARGET_CHECK", "TARGET_THROW") for e in events):
        reasons.append("selected_guard_executed_in_healthy_run")
    if any(rows.get(site, {}).get("exception_class") != EXCEPTION
           for site in (FIRST, SECOND, NATIVE)):
        reasons.append("typed_connection_loss_door_missing")
    if _sha(trace_path) != trial.get("events_evidence", {}).get("gzip_sha256"):
        reasons.append("trace_hash_mismatch")

    firsts = [e for e in events if e.get("type") == "DOOR_OBSERVED" and e.get("site") == FIRST]
    seconds = [e for e in events if e.get("type") == "DOOR_OBSERVED" and e.get("site") == SECOND]
    natives = [e for e in events if e.get("type") == "DOOR_OBSERVED" and e.get("site") == NATIVE]
    witness = None
    for second in seconds:
        actor = (second.get("node"), second.get("epoch"))
        if actor not in roles:
            continue
        first = next((e for e in firsts if _same_split(e, second)
                      and e["seq"] < second["seq"]), None)
        # Sequence numbers are global: an unrelated thread may interleave
        # between the caller and its native ZooKeeper operation.
        next_after_second = next((e for e in events if _same_thread(e, second)
                                  and e["seq"] > second["seq"]), None)
        next_after_first = next((e for e in events if first and _same_thread(e, first)
                                 and e["seq"] > first["seq"]), None)
        nested = next_after_second if next_after_second and next_after_second.get("site") == NATIVE else None
        first_native = next_after_first if next_after_first and next_after_first.get("site") == NATIVE else None
        if first and first_native and nested:
            witness = {"physical_actor": actor[0], "physical_address": roles[actor],
                       "epoch": actor[1], "split_occurrence": second.get("occurrence"),
                       "thread": second.get("thread"), "context": second.get("context"),
                       "first_caller_event_id": first["id"],
                       "first_native_event_id": first_native["id"],
                       "second_caller_event_id": second["id"],
                       "second_native_event_id": nested["id"]}
            break
    if witness is None:
        reasons.append("same_split_second_lookup_native_handoff_missing")
    return {"schema_version": 1, "case_id": "SOLR-15",
            "variant": "chaos-healthy-node0-v2", "status": "passed" if not reasons else "failed",
            "reasons": reasons, "junit": junit,
            "observed_first_caller_doors": len(firsts),
            "observed_second_caller_doors": len(seconds),
            "observed_native_exists_doors": len(natives),
            "same_split_handoff_witness": witness,
            "resource_path_attested": False, "full_campaign_admitted": False,
            "note": "Control is a registered physical Solr actor. The native door is adjacent to the second caller door on that actor, but its event has no ZooKeeper path."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, help="Write the receipt outside a sealed prior output")
    args = parser.parse_args()
    receipt = attest(args.output)
    report = args.report or args.output / "chaos-healthy-node0-v2-gate.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
