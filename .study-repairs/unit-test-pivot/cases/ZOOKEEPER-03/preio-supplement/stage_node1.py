#!/usr/bin/env python3
"""Copy fixed ZK03 assets to node1 and verify SHA; never start a JVM."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
BASE = CASE.parents[3]
SOURCE = Path("/users/ZhenyuLi/zk03-independent-unit")
DEST = "/users/ZhenyuLi/zk03-supplement-assets"
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
RSYNC_SSH = "ssh -i " + str(Path.home() / ".ssh/id_ed25519_nodes") + \
            " -o IdentitiesOnly=yes -o BatchMode=yes"
REVISION = "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def static_files():
    return {
        "agent/zk03-actor-v2-agent.jar": Path(
            "/users/ZhenyuLi/zk03-actor-v2-build/zk03-actor-v2-agent.jar"),
        "agent/build-receipt.json": Path(
            "/users/ZhenyuLi/zk03-actor-v2-build/build-receipt.json"),
        "runner/independent-runner.jar": CASE /
            "evidence/independent/runner/independent-runner.jar",
        "runner/OriginalJUnitRunner.java": CASE /
            "evidence/independent/runner/src/independent/OriginalJUnitRunner.java",
        "classpath/QuorumRestartTest.xml": Path(
            "/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml"),
        "legacy/raw-runs.tar.gz": BASE /
            ".study-repairs/unit-test-pivot/zk-actor-v2/cases/ZOOKEEPER-03/evidence/raw-runs.tar.gz",
        "plan-manifest.json": HERE / "plan-manifest.json",
        "campaign.py": HERE / "campaign.py",
        "audit.py": HERE / "audit.py",
        "receipt_validator.py": HERE / "receipt_validator.py",
        "source-revision.json": HERE / "source-revision.json",
    }


def prepare_manifest():
    if not socket.gethostname().startswith("node0"):
        raise RuntimeError("staging uses node0's pinned original source/assets")
    revision = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise RuntimeError("original source commit changed")
    (HERE / "source-revision.json").write_text(
        json.dumps({"commit": revision, "source": str(SOURCE)}, sort_keys=True,
                   indent=2) + "\n")
    result = {}
    for path in SOURCE.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            result[str(Path("source") / path.relative_to(SOURCE))] = sha(path)
    for rel, path in static_files().items():
        if not path.is_file():
            raise FileNotFoundError(path)
        result[rel] = sha(path)
    (HERE / "asset-file-sha256.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def stage(files):
    subprocess.run(SSH + [REMOTE, "mkdir -p " + DEST + "/source"], check=True)
    subprocess.run(["rsync", "-a", "--exclude=.git", "-e", RSYNC_SSH,
                    str(SOURCE) + "/", REMOTE + ":" + DEST + "/source/"], check=True)
    with tempfile.TemporaryDirectory(prefix="zk03-static-assets-") as scratch:
        root = Path(scratch)
        for rel, original in static_files().items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
        shutil.copy2(HERE / "asset-file-sha256.json", root / "asset-file-sha256.json")
        subprocess.run(["rsync", "-a", "-e", RSYNC_SSH,
                        str(root) + "/", REMOTE + ":" + DEST + "/"], check=True)
    probe = subprocess.run(SSH + [REMOTE,
        "python3 " + DEST + "/campaign.py"], capture_output=True, text=True)
    print(probe.stdout.strip())
    if probe.returncode:
        print(probe.stderr.strip())
    print(json.dumps({"status": "copied_no_jvm", "file_hashes": len(files),
                      "remote_prepare_exit": probe.returncode}, sort_keys=True))
    raise SystemExit(probe.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", action="store_true")
    args = parser.parse_args()
    files = prepare_manifest()
    if not args.copy:
        print(json.dumps({"status": "manifest_only_no_jvm",
                          "file_hashes": len(files)}, sort_keys=True))
        return
    stage(files)


if __name__ == "__main__":
    main()
