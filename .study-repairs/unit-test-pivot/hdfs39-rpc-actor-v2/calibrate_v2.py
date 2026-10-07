#!/usr/bin/env python3
"""Offline gate for two future fault-free HDFS-39 V2 JUnit traces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from build_offline import HERE

SITE = "FSDirAppendOp.appendFile:131"
PATH = "/testMultipleAppend/foo"
BLOCKS = re.compile(r"\[blockReceivedAndDeleted:blocks=\[([1-9][0-9]*(?:, [1-9][0-9]*)*)\]\]")


def inspect(name: str) -> dict:
    run = HERE / "evidence" / name
    manifest = json.loads((run / "manifest.json").read_text())
    if (manifest.get("exit") != 0 or manifest.get("plan") is not None or
            manifest.get("test") !=
            "org.apache.hadoop.hdfs.TestFileAppend#testMultipleAppends"):
        raise ValueError(f"{name}: not a passing original fault-free JUnit")
    events = [json.loads(line) for line in
              (run / "trace/runtime_trace.jsonl").read_text().splitlines() if line]
    coverage = (run / "coverage.tsv").read_text().splitlines()
    if not coverage or not any(line.startswith("BRANCH_UNIT\t") for line in coverage):
        raise ValueError(f"{name}: missing production JaCoCo branch feedback")
    fixture = [e for e in events if e.get("event") == "NN_ENDPOINT_REGISTER"]
    if len(fixture) != 1:
        raise ValueError(f"{name}: missing/ambiguous NameNode fixture")
    port, bp = fixture[0].get("peerPort"), fixture[0].get("blockPoolId")
    if not isinstance(port, int) or port < 1 or not bp:
        raise ValueError(f"{name}: invalid NameNode port/block pool")
    mappings = [e for e in events if e.get("event") == "DN_ROLE_MAP"]
    roles = {e.get("sourceUuid"): e.get("role") for e in mappings}
    if (len(mappings) != 4 or len(roles) != 4 or
            set(roles.values()) != {"dn0", "dn1", "dn2", "dn3"}):
        raise ValueError(f"{name}: invalid four-DN UUID/role map")
    guards = [e for e in events if e.get("event") == "TARGET_GUARD"
              and e.get("site") == SITE and e.get("path") == PATH]
    blocks = {e.get("blockId") for e in guards}
    if len(blocks) != 1 or not {"COMMITTED", "COMPLETE"}.issubset(
            {e.get("state") for e in guards}):
        raise ValueError(f"{name}: exact file/block recovery guard absent")
    block = next(iter(blocks))
    observed = []
    for event in events:
        if event.get("event") != "IO_OBSERVED":
            continue
        api, endpoint = event.get("api", ""), event.get("endpoint", "")
        if api.startswith("DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"):
            match = BLOCKS.search(api)
            if (event.get("peerPort") != port or
                    event.get("blockPoolId") != bp or
                    endpoint != "nn0<-" + str(roles.get(event.get("sourceUuid"))) or
                    not match):
                raise ValueError(f"{name}: unbound observed DN block report")
            if block in {int(value) for value in match.group(1).split(", ")}:
                observed.append(event)
    if not observed:
        raise ValueError(f"{name}: no same-block actor-bound report I/O")
    families = {(e["marker"], e["api"], e["endpoint"]) for e in observed}
    return {"run": name, "seconds": manifest["elapsed_seconds"],
            "target_path": PATH, "target_block_id": block,
            "nn_port": port, "block_pool_id": bp, "dn_roles": roles,
            "same_block_dn_io_count": len(observed),
            "same_block_dn_families": sorted("\t".join(value) for value in families),
            "production_coverage_ids": len(coverage),
            "target_guard_count": len(guards)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", default="healthy-a")
    parser.add_argument("--second", default="healthy-b")
    args = parser.parse_args()
    first, second = inspect(args.first), inspect(args.second)
    if first["target_block_id"] != second["target_block_id"]:
        raise ValueError("healthy seeds reached different target blocks")
    common = sorted(set(first["same_block_dn_families"]) &
                    set(second["same_block_dn_families"]))
    if not common:
        raise ValueError("no stable same-block actor-aware I/O family")
    receipt = {"pass": True, "case": "HDFS-39", "cluster_junit_seeds": 2,
               "healthy": [first, second], "common_same_block_dn_families": common,
               "new_effective_count": 0,
               "old_legacy_effective_count_imported": 0}
    output = HERE / "evidence/healthy-calibration.json"
    if output.exists():
        raise ValueError("calibration receipt exists; preserve it")
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
