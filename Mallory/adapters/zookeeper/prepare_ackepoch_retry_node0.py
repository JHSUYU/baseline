#!/usr/bin/env python3
"""Stage a source-only ACKEPOCH/FOLLOWING retry overlay in a fresh tree.

This never compiles or launches ZooKeeper.  A later compiled receipt and
healthy trace are required before a fault trial can use the overlay.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from install_following_retry import install as install_retry
from install_following_retry_v3 import install as install_retry_finally


HERE = Path(__file__).resolve().parent
BASE_RECEIPT = HERE / "zookeeper-3.8.7-ackepoch-lane2-overlay.json"
BASE_PATCH = HERE / "zookeeper-3.8.7-ackepoch-lane2.full.patch"
VERSION = "ackepoch-following-retry-node0-source-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(destination: Path, receipt_path: Path) -> None:
    if destination.exists() or receipt_path.exists():
        raise FileExistsError("source overlay and receipt must both be new")
    base = json.loads(BASE_RECEIPT.read_text(encoding="utf-8"))
    pristine = Path(base["base_root"])
    if not pristine.is_dir() or sha(BASE_PATCH) != base["patch_sha256"]:
        raise ValueError("pristine ZooKeeper root or ACKEPOCH patch digest changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(pristine, destination, symlinks=True)
    try:
        with BASE_PATCH.open("rb") as stream:
            subprocess.run(["patch", "--batch", "--forward", "-p1"],
                           cwd=destination, stdin=stream, check=True,
                           stdout=subprocess.DEVNULL)
        install_retry(destination)
        install_retry_finally(destination)
        peer = destination / ("zookeeper-server/src/main/java/org/apache/"
                              "zookeeper/server/quorum/QuorumPeer.java")
        hooks = destination / ("zookeeper-server/src/main/java/org/apache/"
                               "zookeeper/server/quorum/MalloryZkHooks.java")
        handler = destination / ("zookeeper-server/src/main/java/org/apache/"
                                 "zookeeper/server/quorum/LearnerHandler.java")
        if ("followingRetrySubmit(this)" not in peer.read_text(encoding="utf-8")
                or "quorumAckEpochScope" not in hooks.read_text(encoding="utf-8")
                or "quorumAckEpochScope" not in handler.read_text(encoding="utf-8")):
            raise ValueError("ACKEPOCH or FOLLOWING retry source hook is missing")
        paths = sorted(base["modified_files"])
        modified = {relative: sha(destination / relative) for relative in paths}
        receipt = {
            "schema_version": 1,
            "version": VERSION,
            "status": "source_only_pending_compilation_and_healthy_trace",
            "base_root": str(pristine),
            "patched_root": str(destination),
            "base_ackepoch_receipt": str(BASE_RECEIPT),
            "base_ackepoch_receipt_sha256": sha(BASE_RECEIPT),
            "base_ackepoch_patch": str(BASE_PATCH),
            "base_ackepoch_patch_sha256": sha(BASE_PATCH),
            "installers": [
                {"path": str(HERE / "install_following_retry.py"),
                 "sha256": sha(HERE / "install_following_retry.py")},
                {"path": str(HERE / "install_following_retry_v3.py"),
                 "sha256": sha(HERE / "install_following_retry_v3.py")},
            ],
            "modified_files": modified,
            "source_rule": (
                "A follower-side ACKEPOCH I/O failure may return from "
                "Follower.followLeader; only a later FOLLOWING attempt on the "
                "same QuorumPeer object, Java thread and lifecycle epoch may "
                "claim the retry token. A new physical ACKEPOCH packet must "
                "then be paired with the Leader.waitForEpochAck target."
            ),
            "evidence_limit": (
                "Source staging alone proves neither a retry nor target "
                "retention; require exact compiled hashes, passing existing "
                "cluster JUnit and event-time fault-to-target path."
            ),
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
    except BaseException:
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    stage(args.destination.resolve(), args.receipt.resolve())
