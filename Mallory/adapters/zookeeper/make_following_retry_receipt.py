#!/usr/bin/env python3
"""Record the independently compiled ZooKeeper FOLLOWING retry overlay."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path


CHANGED = {
    "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java",
    "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java",
    "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java",
    "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Observer.java",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diff(before_root: Path, after_root: Path, names: set[str]) -> str:
    parts = []
    for name in sorted(names):
        before, after = before_root / name, after_root / name
        previous = before.read_text(encoding="utf-8").splitlines(keepends=True) if before.is_file() else []
        current = after.read_text(encoding="utf-8").splitlines(keepends=True)
        if previous == current:
            raise ValueError(f"source hook was not applied: {name}")
        parts.extend(difflib.unified_diff(
            previous, current,
            fromfile="a/" + name if before.is_file() else "/dev/null",
            tofile="b/" + name))
    return "".join(parts)


def make(base_receipt: Path, patched_root: Path, full_patch: Path,
         delta_patch: Path, receipt_file: Path) -> None:
    base = json.loads(base_receipt.read_text(encoding="utf-8"))
    old_root = Path(base["patched_root"])
    pristine = Path(base["base_root"])
    if patched_root == old_root or not patched_root.is_dir():
        raise ValueError("retry overlay requires a distinct built source root")
    for name in base["modified_files"]:
        if name not in CHANGED and sha(old_root / name) != sha(patched_root / name):
            raise ValueError(f"unrelated source changed: {name}")
    delta_patch.write_text(diff(old_root, patched_root, CHANGED), encoding="utf-8")
    full_patch.write_text(diff(pristine, patched_root, set(base["modified_files"])), encoding="utf-8")
    modified = {name: sha(patched_root / name) for name in base["modified_files"]}
    compiled = []
    for row in base["compiled_artifacts"]:
        relative = Path(row["path"]).relative_to(old_root)
        current = patched_root / relative
        if not current.is_file():
            raise FileNotFoundError(current)
        compiled.append({"path": str(current), "sha256": sha(current)})
    retry_class = (patched_root / "zookeeper-server/target/classes/org/apache/zookeeper/"
                   "server/quorum/MalloryZkHooks$FollowingRetry.class")
    if not retry_class.is_file():
        raise FileNotFoundError(retry_class)
    compiled.append({"path": str(retry_class), "sha256": sha(retry_class)})
    receipt = dict(base)
    receipt.update(
        version="following-retry-peer-identity-lane2-v2",
        patched_root=str(patched_root),
        patch_file=str(full_patch), patch_sha256=sha(full_patch),
        modified_files=modified, compiled_artifacts=compiled,
        following_retry_handoff={
            "base_overlay_receipt": str(base_receipt),
            "base_overlay_receipt_sha256": sha(base_receipt),
            "delta_patch": str(delta_patch),
            "delta_patch_sha256": sha(delta_patch),
            "source_hook_installer": "Mallory/adapters/zookeeper/install_following_retry.py",
            "source_rule": "caught FOLLOWING exception submits a unique token inside its bounded region; a later FOLLOWING region claims only on the same QuorumPeer object, Java Thread object, and registered peer lifecycle epoch",
            "receiver_rule": "Follower and Observer receivers are registered against their exact QuorumPeer lifecycle epoch before generic REGION_ENTER",
            "evidence_limit": "compiled source only; exact TASK_SUBMIT/TASK_CLAIM pair and target path require fresh cluster trace",
        },
    )
    receipt_file.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_receipt", type=Path)
    parser.add_argument("patched_root", type=Path)
    parser.add_argument("full_patch", type=Path)
    parser.add_argument("delta_patch", type=Path)
    parser.add_argument("receipt_file", type=Path)
    args = parser.parse_args()
    make(*(path.resolve() for path in (
        args.base_receipt, args.patched_root, args.full_patch,
        args.delta_patch, args.receipt_file)))
