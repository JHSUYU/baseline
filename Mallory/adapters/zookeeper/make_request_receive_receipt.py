#!/usr/bin/env python3
"""Attest a built request RECV context overlay against connect-path source."""

import argparse
import json
from pathlib import Path

from Mallory.adapters.zookeeper.make_following_retry_v3_receipt import patch, sha


HOOK = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java"
HOOK_CLASS = "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/MalloryZkHooks.class"


def make(base_path: Path, root: Path, full_patch: Path, delta_patch: Path,
         receipt_path: Path) -> None:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    previous, pristine = Path(base["patched_root"]), Path(base["base_root"])
    if root == previous or not root.is_dir():
        raise ValueError("request RECV context needs a separate built source root")
    modified = {}
    for name in base["modified_files"]:
        current = root / name
        if not current.is_file():
            raise FileNotFoundError(current)
        modified[name] = sha(current)
        if name == HOOK:
            if modified[name] == sha(previous / name):
                raise ValueError("REQUEST receive hook did not change")
        elif modified[name] != sha(previous / name):
            raise ValueError(f"unrelated source changed: {name}")
    compiled = []
    for artifact in base["compiled_artifacts"]:
        relative = Path(artifact["path"]).relative_to(previous)
        current = root / relative
        if not current.is_file():
            raise FileNotFoundError(current)
        digest = sha(current)
        if relative == Path(HOOK_CLASS) and digest == artifact["sha256"]:
            raise ValueError("REQUEST receive hook class was not recompiled")
        compiled.append({"path": str(current), "sha256": digest})
    delta_patch.write_text(patch(previous, root, [HOOK]), encoding="utf-8")
    full_patch.write_text(patch(pristine, root, modified), encoding="utf-8")
    receipt = dict(base)
    receipt.update(
        version="request-receive-context-lane2-v1",
        patched_root=str(root), patch_file=str(full_patch),
        patch_sha256=sha(full_patch), modified_files=modified,
        compiled_artifacts=compiled,
        request_receive_context={
            "base_overlay_receipt": str(base_path),
            "base_overlay_receipt_sha256": sha(base_path),
            "delta_patch": str(delta_patch),
            "delta_patch_sha256": sha(delta_patch),
            "source_hook_installer": "Mallory/adapters/zookeeper/install_request_receive_context.py",
            "source_rule": "scope only an actual leader REQUEST RECV to its physical QuorumPacket correlation, restore after emission, and retain the exact packet-object handoff into leader request region",
            "evidence_limit": "compiled source only; future thread-scoped agent, existing-test healthy trace, and time-respecting graph audit are required before fault trials",
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
