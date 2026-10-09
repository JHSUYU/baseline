#!/usr/bin/env python3
"""Record a compiled, content-pinned normal-exit FOLLOWING overlay."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch(before: Path, after: Path, names) -> str:
    lines = []
    for name in sorted(names):
        existed = (before / name).is_file()
        left = ((before / name).read_text(encoding="utf-8").splitlines(keepends=True)
                if existed else [])
        right = (after / name).read_text(encoding="utf-8").splitlines(keepends=True)
        if left != right:
            lines.extend(difflib.unified_diff(left, right,
                                               fromfile=f"a/{name}" if existed else "/dev/null",
                                               tofile=f"b/{name}"))
    if not lines:
        raise ValueError("no source change")
    return "".join(lines)


def make(base_path: Path, root: Path, full_patch: Path, delta_patch: Path,
         receipt_path: Path) -> None:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    previous = Path(base["patched_root"])
    pristine = Path(base["base_root"])
    if root == previous:
        raise ValueError("v3 requires a new isolated source tree")
    modified = {}
    for name in base["modified_files"]:
        source = root / name
        if not source.is_file():
            raise FileNotFoundError(source)
        modified[name] = sha(source)
        if name.endswith("/QuorumPeer.java"):
            if modified[name] == sha(previous / name):
                raise ValueError("FOLLOWING branch did not change")
        elif modified[name] != sha(previous / name):
            raise ValueError(f"unrelated hook changed: {name}")
    quorum_peer = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java"
    delta_patch.write_text(patch(previous, root, [quorum_peer]), encoding="utf-8")
    full_patch.write_text(patch(pristine, root, modified), encoding="utf-8")
    compiled = []
    for artifact in base["compiled_artifacts"]:
        relative = Path(artifact["path"]).relative_to(previous)
        current = root / relative
        if not current.is_file():
            raise FileNotFoundError(current)
        compiled.append({"path": str(current), "sha256": sha(current)})
    receipt = dict(base)
    receipt.update(
        version="following-retry-normal-exit-lane2-v3",
        patched_root=str(root), patch_file=str(full_patch),
        patch_sha256=sha(full_patch), modified_files=modified,
        compiled_artifacts=compiled,
        following_retry_handoff={
            "base_overlay_receipt": str(base_path),
            "base_overlay_receipt_sha256": sha(base_path),
            "delta_patch": str(delta_patch),
            "delta_patch_sha256": sha(delta_patch),
            "source_hook_installer": "Mallory/adapters/zookeeper/install_following_retry_v3.py",
            "source_rule": "every completed FOLLOWING attempt submits once from finally; only the next FOLLOWING on the identical QuorumPeer object, Java thread and lifecycle epoch claims it",
            "evidence_limit": "compiled source only; a unique submit/claim and ordered nested target require a fresh fault trace",
        },
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base_receipt", "patched_root", "full_patch", "delta_patch", "receipt_file"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    make(*(getattr(args, name).resolve() for name in
           ("base_receipt", "patched_root", "full_patch", "delta_patch", "receipt_file")))
