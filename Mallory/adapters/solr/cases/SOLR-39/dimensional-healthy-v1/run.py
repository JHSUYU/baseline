#!/usr/bin/env python3
"""One healthy run of the original SOLR-39 Dimensional cluster test."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SOLR_ADAPTERS = ROOT / "Mallory/adapters/solr"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4")
AGENT = (ROOT / "Mallory/instrumentation/releases/"
         "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
         "mallory-agent.jar")
ADAPTER = SOLR_ADAPTERS / "target/mallory-solr-adapter-v38.jar"
TEST = (SOURCE / "solr/core/src/test/org/apache/solr/update/processor/"
        "DimensionalRoutedAliasUpdateProcessorTest.java")
OUT = ROOT / "data/mallory/calibration_solr39_dimensional_healthy_v1_node1/SOLR-39"
PINS = {
    TEST: "e14a771d25256a5b6386a70c661efe89481f146c1cd124088f32a3fc492c3e1f",
    AGENT: "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9",
    ADAPTER: "86915aa43203d934431126f9cfbe6f534125dc8a198bf7e9a074a3695d8f5947",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise RuntimeError("this isolated healthy run is assigned to node1")
    for path, expected in PINS.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"source or runtime artifact differs: {path}")
    if OUT.exists():
        raise RuntimeError(f"healthy output already exists: {OUT}")
    if args.preflight_only:
        print(json.dumps({"case_id": "SOLR-39", "mode": "healthy",
                          "selector": "DimensionalRoutedAliasUpdateProcessorTest#testTimeCat",
                          "pins_verified": True, "output_absent": True}, sort_keys=True))
        return 0
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if OUT.exists():
            raise RuntimeError("output appeared after lock acquisition")
        sys.path.insert(0, str(SOLR_ADAPTERS))
        import solr_junit_runner_v14 as runner  # noqa: E402
        runner.INVENTORY = HERE / "inventory.json"
        runner.AGENT = AGENT
        runner.ADAPTER = ADAPTER
        os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
        os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
        os.environ["MALLORY_SOLR_AWAITSFIX"] = "1"
        os.environ["JAVA_TOOL_OPTIONS"] = "-Dsolr.disableConfigSetsCreateAuthChecks=true"
        result = runner.run("SOLR-39", SOURCE, DIST, OUT, 420, False, False)
        print(json.dumps({key: result.get(key) for key in (
            "status", "junit", "target_check_count", "target_throw_count",
            "target_nodes", "elapsed_seconds", "exit_code")}, sort_keys=True))
        return int(result.get("exit_code", 1))
    finally:
        for handle in reversed(locks):
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
