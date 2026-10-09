#!/usr/bin/env python3
"""Record the independently compiled ACKEPOCH source overlay and full patch."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make(base_receipt: Path, patched_root: Path, patch_file: Path,
         receipt_file: Path, delta_file: Path) -> None:
    parent = json.loads(base_receipt.read_text(encoding="utf-8"))
    pristine = Path(parent["base_root"])
    old_root = Path(parent["patched_root"])
    if patched_root == old_root or not patched_root.is_dir():
        raise ValueError("ACKEPOCH must use a separate built source root")
    modified = {}
    parts = []
    for name in sorted(parent["modified_files"]):
        relative = Path(name)
        before = pristine / relative
        after = patched_root / relative
        if not after.is_file():
            raise FileNotFoundError(after)
        previous = before.read_text(encoding="utf-8").splitlines(keepends=True) if before.is_file() else []
        current = after.read_text(encoding="utf-8").splitlines(keepends=True)
        if previous == current:
            raise ValueError(f"declared modified file matches pristine: {name}")
        parts.extend(difflib.unified_diff(
            previous, current,
            fromfile="a/" + name if before.is_file() else "/dev/null",
            tofile="b/" + name))
        modified[name] = sha(after)
    patch_file.write_text("".join(parts), encoding="utf-8")
    compiled = []
    for row in parent["compiled_artifacts"]:
        old = Path(row["path"])
        relative = old.relative_to(old_root)
        now = patched_root / relative
        if not now.is_file():
            raise FileNotFoundError(now)
        compiled.append({"path": str(now), "sha256": sha(now)})
    receipt = dict(parent)
    receipt.update(
        version="ackepoch-packet-context-lane2-v1",
        patched_root=str(patched_root), patch_file=str(patch_file),
        patch_sha256=sha(patch_file), modified_files=modified,
        compiled_artifacts=compiled,
        ackepoch_packet_handoff={
            "base_overlay_receipt": str(base_receipt),
            "base_overlay_receipt_sha256": sha(base_receipt),
            "delta_patch": str(delta_file),
            "delta_patch_sha256": sha(delta_file),
            "read_source": "LearnerHandler.run: ia.readRecord(ackEpochPacket)",
            "target_call": "LearnerHandler.run: learnerMaster.waitForEpochAck(this.getSid(), ss)",
            "identity_rule": "ACKEPOCH type and exact QuorumPacket object identity, then scoped receive correlation",
            "evidence_limit": "compiled source only; exact paired SEND/RECV and target closure require a fresh healthy trace",
        },
    )
    receipt_file.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_receipt", type=Path)
    parser.add_argument("patched_root", type=Path)
    parser.add_argument("patch_file", type=Path)
    parser.add_argument("receipt_file", type=Path)
    parser.add_argument("delta_file", type=Path)
    args = parser.parse_args()
    make(args.base_receipt.resolve(), args.patched_root.resolve(),
         args.patch_file.resolve(), args.receipt_file.resolve(),
         args.delta_file.resolve())
