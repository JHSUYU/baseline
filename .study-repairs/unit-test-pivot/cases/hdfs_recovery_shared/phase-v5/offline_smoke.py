#!/usr/bin/env python3
"""Compile/verify V5 hooks and synthetic owner/queue rules without a cluster."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import run_original as runner
import v5_model as model
import campaign
import audit_v5

HERE = Path(__file__).resolve().parent
OUT = HERE / "offline-smoke.json"


def synthetic_rules() -> dict:
    owner = {"clusterEpisode": 1, "sourceKey": "dn1", "bpid": "BP-a",
             "blockId": 42, "recoveryId": 1002, "commandToken": "command:1",
             "occurrenceAddress": "dn1/block:42/attempt:1"}
    target = {**owner, "event": "TARGET_CHECK", "caseId": "HDFS-29",
              "siteId": model.SITES["HDFS-29"], "seq": 20}
    io = {**owner, "event": "FAULT_POINT_OBSERVED", "seq": 12,
          "marker": "FAULT:HADOOP_IPC:REQUEST", "siteId": "ipc",
          "occurrenceAddress": owner["occurrenceAddress"] + "/rpc:initReplicaRecovery",
          "hitOrdinal": 1, "requestApi": "initReplicaRecovery"}
    registration = {"event": "DN_REGISTER", "sourceKey": "dn1",
                    "clusterEpisode": 1, "seq": 1}
    begin = {**owner, "event": "RECOVERY_BEGIN", "seq": 2}
    trace = [registration, begin, io, target]
    assert model.identity_verified(trace, io)
    assert model.eligible_io(trace, io, ("HDFS-29",)) == ["HDFS-29"]
    assert not model.same_owner(io, {**target, "bpid": "BP-other"})
    assert not model.same_owner(io, {**target, "clusterEpisode": 2})
    assert not model.same_owner(io, {**target, "recoveryId": 1003})
    assert not model.same_owner(io, {**target, "sourceKey": "dn0"})
    assert not model.same_owner(io, {**target, "commandToken": "command:2"})
    assert not model.identity_verified([begin, io, target], io)
    assert not model.eligible_io(trace, {**io, "seq": 21}, ("HDFS-29",))
    old = dict(io, originSourceKey="dn1", faultType="IOException", filePhase="")
    assert model.legacy_parent_key(old) == model.legacy_parent_key(
        {**old, "filePhase": "initReplicaRecovery"})
    seq = [model.selector(io, "IOException")]
    good = {**io, "event": "FAULT_APPLIED", "faultType": "IOException", "planIndex": 0,
            "filePhase": ""}
    assert model.event_matches(good, seq[0], 0, 1)
    assert not model.event_matches({**good, "clusterEpisode": 2}, seq[0], 0, 1)
    state = {"v5_attempts": 0, "strict_ids": [], "completed_v5": [],
             "cases": {case: {"status": "active", "max_faults": 8} for case in model.CASES},
             "queue": [{"id": "explore", "sequence": seq, "lane": "exploration",
                        "pre_target_cases": [], "created": 1},
                       {"id": "owner", "sequence": seq * 2,
                        "lane": "same_owner_second_fault",
                        "pre_target_cases": ["HDFS-29"], "created": 2}]}
    assert model.select_index(state) == 1
    state["v5_attempts"] = 3
    assert model.select_index(state) == 0
    budget = {"status": "active", "attempts": 320, "effective": 40,
              "effective_goal": 80, "attempt_cap": 320, "max_faults": 8}
    model.update_case_budget(budget, [], "HDFS-29")
    assert budget["status"] == "budget_recheck_pending"
    budget = {"status": "active", "attempts": 319, "effective": 80,
              "effective_goal": 80, "attempt_cap": 320, "max_faults": 8}
    novelty = [{"coverage_gain": {"HDFS-29": {"branch_counts": 1}},
                "new_io_families": {"HDFS-29": []}} for _ in range(8)]
    model.update_case_budget(budget, novelty, "HDFS-29")
    assert budget["effective_goal"] == 128 and budget["attempt_cap"] == 512
    assert budget["max_faults"] == 10
    fake = HERE / "build" / "synthetic-trial"
    fake.mkdir(parents=True, exist_ok=True)
    gate = fake / "gate.json"
    gate.write_text(json.dumps({"overlay_digest": "synthetic"}))
    campaign.GATE = gate
    (fake / "manifest.json").write_text(json.dumps(
        {"overlay_digest": "synthetic", "returncode": 0, "elapsed_seconds": 1}))
    matched = {**good, "event": "FAULT_MATCHED", "seq": 12}
    applied = {**good, "event": "FAULT_APPLIED", "seq": 13}
    target = {**target, "seq": 14, "outcome": False}
    fake_trace = [registration, begin, matched, applied, target]
    (fake / "runtime_trace.jsonl").write_text("\n".join(map(json.dumps, fake_trace)) + "\n")
    fake_state = {"coverage_v5": {case: {kind: [] for kind in
                  ("probes", "methods", "branch_counts")} for case in model.CASES},
                  "io_families_v5": {case: [] for case in model.CASES}}
    item = {"id": model.sequence_id(seq), "sequence": seq, "expectedEpisode": 1,
            "lane": "same_owner_second_fault", "active_cases_at_selection": ["HDFS-29"]}
    trial = campaign.assess(fake, item, fake_state)
    independently = audit_v5.receipt_verdict(trial)
    assert trial["exact_order_applied"] and independently["strict"]
    assert trial["post_fault_target_checks"]["HDFS-29"] == 1
    assert independently["post"]["HDFS-29"] == 1
    fake_trace[-1] = {**target, "bpid": "BP-other"}
    (fake / "runtime_trace.jsonl").write_text("\n".join(map(json.dumps, fake_trace)) + "\n")
    trial_wrong = campaign.assess(fake, item, fake_state)
    assert trial_wrong["exact_order_applied"]
    assert trial_wrong["post_fault_target_checks"]["HDFS-29"] == 0
    assert audit_v5.receipt_verdict(trial_wrong)["post"]["HDFS-29"] == 0
    return {"owner_dimensions": 7, "phase_independent_legacy_prefix": True,
            "same_owner_second_fault_priority": True,
            "exploration_every_fourth_round": True,
            "base_cap": 320, "conditional_cap": 512}


def main() -> None:
    env = dict(os.environ, JAVA_HOME=str(runner.JDK.parent))
    cp = subprocess.check_output([str(runner.HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                 env=env, text=True).strip()
    overlay = runner.build_instrumentation(cp)
    classpath = os.pathsep.join((str(overlay), str(runner.BUILD), str(runner.TESTS),
                                 str(runner.COMMON_TESTS), cp))
    subprocess.run([str(runner.JDK / "javac"), "-cp", classpath,
                    "-d", str(runner.BUILD), str(HERE / "OfflineProbeSmoke.java")], check=True)
    trace = HERE / "build" / "offline-probe-trace.jsonl"
    trace.unlink(missing_ok=True)
    subprocess.run([str(runner.JDK / "java"), "-Xverify:all",
                    "-Dhdfs.recovery.trace=" + str(trace), "-cp", classpath,
                    "OfflineProbeSmoke"], check=True)
    parsed = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [row["event"] for row in parsed] == ["TARGET_CHECK", "BRANCH",
                                                    "TARGET_THROW", "FAULT_POINT_OBSERVED"]
    assert parsed[2]["runtimeType"] == "java.io.IOException"
    assert all(row["clusterEpisode"] == 1 and row["commandToken"].startswith("direct:")
               for row in parsed)
    raw = subprocess.check_output([str(runner.JDK / "javap"), "-p", "-c",
                                   "-classpath", str(overlay),
                                   "org.apache.hadoop.hdfs.server.datanode.BPOfferService"],
                                  text=True)
    assert raw.count("RecoveryProbe.ioRecoveryCommand") == 1
    result = {"schema": "hdfs-recovery-v5-offline-smoke-1", "passed": True,
              "overlay_digest": runner.overlay_digest(overlay),
              "probe_source_sha256": hashlib.sha256((HERE / "RecoveryProbe.java").read_bytes()).hexdigest(),
              "weaver_source_sha256": hashlib.sha256((HERE / "PatchRecovery.java").read_bytes()).hexdigest(),
              "producer_hook_bytecode_count": 1, "synthetic_target_throw_valid_json": True,
              "verification": "-Xverify:all Class.forName(BPOfferService), no cluster startup",
              "model": synthetic_rules()}
    OUT.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
