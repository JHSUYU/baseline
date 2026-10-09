#!/usr/bin/env python3
"""Fail-closed two-seed calibration of original HDFS-16 embedded JUnit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_offline import HERE
from run_v2 import TEST

SITE = "BlockInfo.setGenerationStampAndVerifyReplicas:428"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def context(row: dict) -> dict:
    # Block IDs and generation stamps are allocated by a fresh MiniDFSCluster
    # and cannot be copied from one healthy seed into a later fault run.
    return {"caller": row["caller"], "block_role": "original_test_file_block"}


def family(row: dict) -> str:
    return "\t".join((row["marker"], row["api"], row["senderRole"]))


def inspect(name: str) -> dict:
    run = HERE / "evidence" / name
    manifest = json.loads((run / "manifest.json").read_text())
    if (manifest.get("case_id") != "HDFS-16" or manifest.get("test") != TEST or
            manifest.get("returncode") != 0 or manifest.get("plan") is not None):
        raise ValueError(f"{name}: original fault-free JUnit did not pass")
    for label, path in (("trace", run / "runtime_trace.jsonl"),
                        ("jacoco", run / "jacoco.exec"),
                        ("coverage", run / "coverage.tsv")):
        if (not path.is_file() or not path.stat().st_size or
                manifest.get(label + "_sha256") != sha(path)):
            raise ValueError(f"{name}: missing/changed raw {label}")
    trace = read_events(run / "runtime_trace.jsonl")
    roles: dict[str, str] = {}
    nn_ports: set[int] = set()
    bound: dict[int, tuple[str, str] | None] = {}
    observed = []
    guards = []
    main_dn0 = False
    for row in trace:
        event, thread = row.get("event"), row.get("threadId")
        if event == "DN_ROLE_CONFLICT":
            raise ValueError(f"{name}: conflicting DN list position")
        if event == "DN_ROLE_REGISTER":
            role, uuid = row.get("senderRole"), row.get("dnUuid")
            if (role not in ("dn0", "dn1") or not uuid or
                    role in roles and roles[role] != uuid or
                    uuid in roles.values() and roles.get(role) != uuid):
                raise ValueError(f"{name}: ambiguous DN role mapping")
            roles[role] = uuid
        elif event == "NN_ENDPOINT_REGISTER":
            port = row.get("peerPort")
            if not isinstance(port, int) or port <= 0:
                raise ValueError(f"{name}: invalid NN peer port")
            nn_ports.add(port)
        elif event == "DN_RPC_BIND":
            role, uuid, bp = (row.get("senderRole"), row.get("senderDnUuid"),
                              row.get("blockPoolId"))
            raw = row.get("senderActor")
            if not isinstance(thread, int):
                raise ValueError(f"{name}: DN RPC lacks numeric thread identity")
            if not role:
                bound[thread] = None  # startup RPC is recorded but uninjectible
                continue
            if (roles.get(role) != uuid or not bp or raw != f"dn:{uuid}|bp:{bp}"):
                raise ValueError(f"{name}: DN RPC lacks UUID/BP/role binding")
            bound[thread] = (raw, role)
            if (row.get("thread") == "main" and role == "dn0"):
                main_dn0 = True
        elif event == "DN_RPC_UNBIND":
            raw, role = row.get("senderActor"), row.get("senderRole")
            bound[thread] = (raw, role) if raw and role else None
        elif event == "IO_OBSERVED":
            if row.get("marker") == "RPC_RESPONSE":
                if (bound.get(thread) !=
                        (row.get("senderActor"), row.get("senderRole")) or
                        row.get("peerPort") not in nn_ports):
                    raise ValueError(f"{name}: observed DN RPC lacks actual sender/NN peer")
                observed.append(row)
            elif (row.get("marker") == "FILE_FLUSH" and
                  row.get("senderRole") == "nn-editlog" and
                  row.get("api", "").endswith(":durable")):
                observed.append(row)
        elif (event == "TARGET_GUARD" and row.get("site") == SITE and
              row.get("caller") in ("BlockManager.updateLastBlock",
                                    "BlockInfo.commitBlock")):
            if not row.get("allowed"):
                raise ValueError(f"{name}: healthy original target guard failed")
            guards.append(row)
    if set(roles) != {"dn0", "dn1"} or not nn_ports or not main_dn0 or not guards:
        raise ValueError(f"{name}: two DN roles, main DN0 registration, NN or target absent")
    related = [row for row in observed if any(guard["seq"] > row["seq"] for guard in guards)]
    if not related:
        raise ValueError(f"{name}: no actor-bound I/O before target")
    if len({row["blockId"] for row in guards}) != 1:
        raise ValueError(f"{name}: original single-file JUnit reached multiple target blocks")
    coverage = (run / "coverage.tsv").read_text().splitlines()
    counts = {kind: sum(line.startswith(kind + "\t") for line in coverage)
              for kind in ("PROBE", "METHOD", "BRANCH_UNIT")}
    if not all(counts.values()):
        raise ValueError(f"{name}: production coverage feedback missing")
    return {"run": name, "seconds": manifest["elapsed_seconds"],
            "test": TEST, "overlay_sha256": manifest["overlay_sha256"],
            "roles": roles, "nn_ports": sorted(nn_ports),
            "main_dn0_registration": main_dn0,
            "concrete_target_block_ids": sorted({row["blockId"] for row in guards}),
            "concrete_target_stamps": sorted({row["proposedGenerationStamp"] for row in guards}),
            "target_contexts": sorted({json.dumps(context(g), sort_keys=True) for g in guards}),
            "target_guards": len(guards),
            "io_families": sorted({family(row) for row in related}),
            "production_coverage": counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", default="healthy-a")
    parser.add_argument("--second", default="healthy-b")
    args = parser.parse_args()
    first, second = inspect(args.first), inspect(args.second)
    if first["overlay_sha256"] != second["overlay_sha256"]:
        raise ValueError("healthy seeds used different actor-V2 bytecode")
    shared_contexts = sorted(set(first["target_contexts"]) & set(second["target_contexts"]))
    shared_families = sorted(set(first["io_families"]) & set(second["io_families"]))
    if not shared_contexts or not shared_families:
        raise ValueError("no stable target context or role-bound I/O family")
    output = HERE / "evidence/healthy-calibration.json"
    if output.exists():
        raise ValueError("calibration receipt already exists")
    result = {"pass": True, "case": "HDFS-16", "original_junit_seeds": 2,
              "new_effective_trials": 0, "legacy_trials_imported": 0,
              "seeds": [first, second], "shared_target_contexts": shared_contexts,
              "shared_io_families": shared_families}
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
