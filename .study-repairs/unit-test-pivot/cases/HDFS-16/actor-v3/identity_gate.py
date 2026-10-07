#!/usr/bin/env python3
"""Independent actor and target gate for original HDFS-16 MiniDFSCluster runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ("marker", "api", "actorKey", "peerClass", "poolClass", "ordinal")
TARGET = "BlockInfo.setGenerationStampAndVerifyReplicas:428"
CALLERS = ("BlockManager.updateLastBlock", "BlockManager.updateLastBlock",
           "BlockInfo.commitBlock")


def rows(run: Path) -> list[dict]:
    return [json.loads(line) for line in
            (run / "trace/runtime_trace.jsonl").read_text().splitlines()]


def selector(row: dict) -> tuple:
    return tuple(row.get(key) for key in KEYS)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temp, path)


def target_context(trace: list[dict]) -> dict:
    guards = [row for row in trace if row.get("event") == "TARGET_GUARD"]
    manual = [row for row in trace if row.get("event") == "IO_OBSERVED"
              and row.get("manualSelectedRegistration")]
    registrations = [row for row in trace if row.get("event") == "IO_OBSERVED"
                     and row.get("api") ==
                     "DatanodeProtocolClientSideTranslatorPB.registerDatanode"]
    assert len(guards) == 3 and len(manual) == 1
    assert [row["caller"] for row in guards] == list(CALLERS)
    assert all(row["site"] == TARGET and row["allowed"] for row in guards)
    assert all(row["blockId"] == guards[0]["blockId"] for row in guards)
    assert guards[0]["blockId"] > 0 and manual[0]["seq"] < guards[0]["seq"]
    actor, uuid, pool = (manual[0]["actorKey"],
                         manual[0]["rawDatanodeUuid"], manual[0]["poolClass"])
    assert actor.startswith("episode=1/dn=1/dirs=dfs/data/")
    assert uuid and pool == "BP0" and manual[0]["rawBlockPoolId"]
    assert manual[0]["peerClass"] == "NN0"
    assert all(row["selectedDatanodeActor"] == actor and
               row["selectedDatanodeUuid"] == uuid and
               row["selectedBlockPool"] == pool for row in guards)
    background = [row for row in registrations
                  if not row["manualSelectedRegistration"]]
    assert len(background) == 2
    assert len({row["actorKey"] for row in background}) == 2
    assert len({row["rawDatanodeUuid"] for row in background}) == 2
    assert sum(row["actorKey"] == actor and
               row["rawDatanodeUuid"] == uuid for row in background) == 1
    assert all(row["peerClass"] == "NN0" for row in background)
    return {"actor": actor, "uuid": uuid, "pool": pool,
            "raw_pool": manual[0]["rawBlockPoolId"],
            "block_id": guards[0]["blockId"],
            "manual_seq": manual[0]["seq"],
            "target_seqs": [row["seq"] for row in guards],
            "background_registration": [
                {"actor": row["actorKey"], "uuid": row["rawDatanodeUuid"],
                 "seq": row["seq"], "call_id": row["rpcCallId"]}
                for row in background]}


def calibration(root: Path) -> dict:
    observations = []
    for seed in ("a", "b"):
        run = root / "healthy" / seed
        manifest = json.loads((run / "manifest.json").read_text())
        trace = rows(run)
        assert manifest["test"].endswith("#testUpdatePipeLineAfterDNReg")
        assert manifest["exit"] == 0 and manifest["probe"] and manifest["coverage"]
        assert (run / "coverage.tsv").is_file()
        context = target_context(trace)
        observations.append((run, trace, context, manifest))
    (first, a, ca, ma), (second, b, cb, mb) = observations
    assert ca["actor"] == cb["actor"] and ca["pool"] == cb["pool"]
    assert ca["block_id"] == cb["block_id"]
    assert ca["uuid"] != cb["uuid"] and ca["raw_pool"] != cb["raw_pool"]
    def candidates(trace: list[dict], context: dict) -> set[tuple]:
        return {selector(row) for row in trace if row.get("event") == "IO_OBSERVED"
                and row["seq"] < context["target_seqs"][-1]
                and row["actorKey"] in (context["actor"], "CLIENT", "NN0")
                and row["peerClass"] in ("NN0", "LOCAL_NN0")
                and row["marker"] in ("RPC_RESPONSE", "FILE_FLUSH")}
    stable = sorted(candidates(a, ca) & candidates(b, cb))
    assert stable and any(row[1].endswith("registerDatanode") and
                          row[2] == ca["actor"] for row in stable)
    assert any("updatePipeline" in row[1] for row in stable)
    # Mutation of the observed join fields must be rejected by the same
    # invariant used on faulted traces. This is an offline negative control.
    def joined(manual: dict, target: dict) -> bool:
        return (manual["actorKey"] == target["selectedDatanodeActor"] and
                manual["rawDatanodeUuid"] == target["selectedDatanodeUuid"] and
                manual["poolClass"] == target["selectedBlockPool"] and
                manual["peerClass"] == "NN0")
    original = next(row for row in a if row.get("manualSelectedRegistration"))
    target = next(row for row in a if row.get("event") == "TARGET_GUARD")
    assert joined(original, target)
    negatives = {}
    for key, value in (("actorKey", "episode=1/dn=2/dirs=other"),
                       ("rawDatanodeUuid", "wrong-datanode-uuid"),
                       ("poolClass", "wrong-block-pool"),
                       ("peerClass", "UNBOUND")):
        mutated = dict(original, **{key: value})
        negatives[key] = not joined(mutated, target)
    assert all(negatives.values())
    receipt = {"schema": "hdfs16-v3-healthy-calibration-1", "pass": True,
               "test": ma["test"], "target_site": TARGET,
               "stable_actor": ca["actor"], "stable_pool": ca["pool"],
               "target_block_id": ca["block_id"],
               "seed_a": ca, "seed_b": cb,
               "elapsed_seconds": [ma["elapsed_seconds"], mb["elapsed_seconds"]],
               "stable_selectors": [dict(zip(KEYS, row)) for row in stable],
               "negative_controls": negatives,
               "source_shas": {name: sha(root / "system-test" / name)
                               for name in ("Probe.java", "Hdfs16ActorRegistry.java",
                                            "PatchHdfs16Actor.java", "build_probe.py")},
               "trace_shas": {seed: sha(root / "healthy" / seed /
                                        "trace/runtime_trace.jsonl")
                              for seed in ("a", "b")}}
    atomic(root / "healthy-receipt.json", receipt)
    return receipt


def evaluate(run: Path, plan: Path, healthy_receipt: Path) -> dict:
    trace = rows(run)
    manifest = json.loads((run / "manifest.json").read_text())
    healthy = json.loads(healthy_receipt.read_text())
    planned = [line.split("\t") for line in plan.read_text().splitlines() if line]
    assert planned and all(len(parts) == 7 for parts in planned)
    matches = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    def matches_plan(row: dict, index: int) -> bool:
        step = planned[index]
        return (tuple(str(row.get(key)) for key in KEYS) == tuple(step[:6])
                and row.get("exception") == step[6]
                and row.get("planIndex") == index
                and row.get("peerClass") in ("NN0", "LOCAL_NN0"))
    exact = (len(matches) == len(applied) == len(planned) and
             all(matches_plan(matches[i], i) and matches_plan(applied[i], i)
                 and matches[i]["seq"] < applied[i]["seq"]
                 for i in range(len(planned))) and
             all(applied[i]["seq"] < matches[i + 1]["seq"]
                 for i in range(len(planned) - 1)))
    target = [row for row in trace if row.get("event") == "TARGET_GUARD"
              and (not applied or row["seq"] > applied[-1]["seq"])
              and row.get("site") == TARGET
              and row.get("blockId") == healthy["target_block_id"]
              and row.get("selectedDatanodeActor") == healthy["stable_actor"]
              and row.get("selectedBlockPool") == healthy["stable_pool"]]
    manual = [row for row in trace if row.get("event") == "IO_OBSERVED"
              and row.get("manualSelectedRegistration")]
    selected_uuid = target[0].get("selectedDatanodeUuid") if target else None
    namenode_endpoint = (manual[0].get("rawRemoteEndpoint")
                         if len(manual) == 1 else None)
    actor_join = (len(manual) == 1 and bool(selected_uuid) and
                  manual[0].get("actorKey") == healthy["stable_actor"] and
                  manual[0].get("rawDatanodeUuid") == selected_uuid and
                  manual[0].get("poolClass") == healthy["stable_pool"] and
                  manual[0].get("peerClass") == "NN0" and
                  bool(namenode_endpoint) and "/127.0.0.1:" in
                  namenode_endpoint and
                  all(row.get("selectedDatanodeUuid") == selected_uuid
                      for row in target))
    fault_actor_join = bool(applied) and all(
        (row["actorKey"] == healthy["stable_actor"] and
         row.get("rawDatanodeUuid") in (None, "", selected_uuid) and
         row["peerClass"] == "NN0" and
         row.get("rawRemoteEndpoint") == namenode_endpoint)
        if row["actorKey"].startswith("episode=") else
        ((row["actorKey"] == "CLIENT" and row["peerClass"] == "NN0" and
          row.get("rawRemoteEndpoint") == namenode_endpoint) or
         (row["actorKey"] == "NN0" and row["peerClass"] == "LOCAL_NN0"))
        for row in applied)
    target_exceptions = [row for row in trace if row.get("event") == "TARGET_EXCEPTION"
                         and applied and row["seq"] > applied[-1]["seq"]
                         and row.get("site") == TARGET and
                         row.get("blockId") == healthy["target_block_id"]]
    valid = bool(exact and target and actor_join and fault_actor_join)
    candidate = bool(exact and target and actor_join and fault_actor_join and
                     target_exceptions)
    junit_log = (run / "logs/runtime.log").read_text(errors="replace")
    injected_exception_in_log = "HDFS-16 V3 injected at" in junit_log
    environment_failure_in_log = any(marker in junit_log for marker in
                                     ("BindException", "Address already in use",
                                      "OutOfMemoryError"))
    return {"schema": "hdfs16-v3-trial-gate-1", "exact_order_applied": exact,
            "requested_faults": len(planned), "matched_faults": len(matches),
            "applied_faults": len(applied), "postfault_target_count": len(target),
            "selected_datanode_uuid": selected_uuid,
            "manual_registration_join": actor_join,
            "fault_actor_join": fault_actor_join,
            "target_exception_count": len(target_exceptions),
            "target_exception_candidate": candidate,
            "valid_for_feedback": valid,
            "workload_failure": manifest["exit"] != 0,
            "injected_exception_in_junit_log": injected_exception_in_log,
            "environment_failure_in_junit_log": environment_failure_in_log,
            "junit_exit": manifest["exit"],
            "elapsed_seconds": manifest["elapsed_seconds"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", type=Path)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--healthy-receipt", type=Path)
    args = parser.parse_args()
    if args.calibrate:
        result = calibration(args.calibrate)
    else:
        if not args.run or not args.plan or not args.healthy_receipt:
            parser.error("--run, --plan, --healthy-receipt are required")
        result = evaluate(args.run, args.plan, args.healthy_receipt)
    print(json.dumps(result, sort_keys=True))
