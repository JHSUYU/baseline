#!/usr/bin/env python3
"""Mirror the node2 checkpoint summary into the node0 102-case checklist."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
REMOTE = "/users/ZhenyuLi/zk03-case/summarize_result.py"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=5", "ZhenyuLi@node2", "python3", REMOTE]


def sync() -> bool:
    remote = subprocess.run(SSH, capture_output=True, text=True, timeout=15)
    if remote.returncode != 0:
        return False
    data = json.loads(remote.stdout)
    if data.get("case_id") != "ZOOKEEPER-03":
        raise RuntimeError("Unexpected case in remote result")
    data["methodology"] = "coverage_io_no_graph"
    data["source_inventory_only"] = False
    data["original_mapped_test"] = (
        "org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest"
        "#testCloseSessionWhileUpgradeOnLearner")
    data["mapping_note"] = (
        "The mapped learner test passed five healthy executions but skipped "
        "its session-upgrade operation. The unchanged original QuorumTest "
        "testSessionMoved reached the selected setOwner check 11 times in a "
        "healthy embedded-cluster run.")
    data["evidence"] = ".study-repairs/unit-test-pivot/cases/ZOOKEEPER-03/README.md"
    temporary = HERE / "result.json.tmp"
    with temporary.open("w") as output:
        json.dump(data, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(HERE / "result.json")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            if sync():
                print("synced ZOOKEEPER-03", flush=True)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            print(str(error), flush=True)
        if args.once:
            break
        time.sleep(5)
