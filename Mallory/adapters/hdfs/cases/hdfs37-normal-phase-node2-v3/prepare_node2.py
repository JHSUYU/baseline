#!/usr/bin/env python3
"""Build one HDFS-37 test-local healthy seed in an isolated node2 tree."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import os

from preflight import (HERE, ORIGINAL, SOURCE, TARGET_CLASS, TEST_CLASS,
                       TEST_RELATIVE, V2, materialize_config, preflight,
                       require, sha)


SEED = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
LOCK = Path("/tmp/mallory-lanes/hdfs-identity-v8-node2.lock")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="copy source and compile one adapted test")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(preflight(False), sort_keys=True))
        return
    if socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-37 source build is scoped to node2")
    if os.environ.get("MALLORY_HDFS37_V3_NODE2_BUILD_GRANT") != "healthy-only":
        raise RuntimeError("dispatch healthy-only build grant required")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(False)
        pins = json.loads((HERE / "package-manifest.json").read_text())
        require(SEED / TARGET_CLASS, pins["target_class_sha256"])
        require(SEED / TEST_CLASS, pins["original_test_class_sha256"])
        if shutil.disk_usage(SOURCE.parent).free < 2_000_000_000:
            raise RuntimeError("node2 disk reserve below 2 GB")

        SOURCE.mkdir(parents=True, exist_ok=False)
        subprocess.run(["rsync", "-a", "--exclude=.git", "--exclude=target",
                        str(ORIGINAL) + "/", str(SOURCE) + "/"], check=True)
        sys.path.insert(0, str(V2))
        from prepare_overlay import render  # noqa: E402
        overlay = json.loads((V2 / "source-overlay-receipt.json").read_text())
        patched = render((SOURCE / TEST_RELATIVE).read_bytes(), overlay)
        (SOURCE / TEST_RELATIVE).write_bytes(patched)
        require(SOURCE / TEST_RELATIVE, pins["patched_test_source_sha256"])

        target = SOURCE / "hadoop-hdfs-project/hadoop-hdfs/target"
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-a", "--exclude=surefire-reports", "--exclude=log",
                        str(SEED / "hadoop-hdfs-project/hadoop-hdfs/target") + "/",
                        str(target) + "/"], check=True)
        require(SOURCE / TARGET_CLASS, pins["target_class_sha256"])
        require(SOURCE / TEST_CLASS, pins["original_test_class_sha256"])

        subprocess.run(["mvn", "-o", "-B", "-ntp", "-pl", "hadoop-hdfs-project/hadoop-hdfs",
                        "-DskipTests", "test-compile"], cwd=SOURCE, check=True)
        require(SOURCE / TARGET_CLASS, pins["target_class_sha256"])
        test_sha = sha(SOURCE / TEST_CLASS)
        if test_sha == pins["original_test_class_sha256"]:
            raise RuntimeError("adapted TestDFSRollback class did not change")

        template = json.loads((HERE / "HDFS-37-node2-healthy-BLOCKED.json").read_text())
        config = materialize_config(template, test_sha)
        config_path = SOURCE / "mallory-hdfs37-healthy-node2-v3.json"
        write_json(config_path, config)
        receipt = {
            "case_id": "HDFS-37",
            "schema_version": 1,
            "source_commit": pins["source_commit"],
            "patched_full_source_digest": pins["patched_full_source_digest"],
            "target_class_sha256": pins["target_class_sha256"],
            "compiled_test_class_sha256": test_sha,
            "runtime_config_sha256": sha(config_path),
            "status": "compiled_healthy_only_not_run",
            "jvm_test_started": False,
            "full_admitted": False,
        }
        write_json(SOURCE / "mallory-hdfs37-compiled-receipt.json", receipt)
        print(json.dumps(preflight(True), sort_keys=True))


if __name__ == "__main__":
    main()
