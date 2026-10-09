#!/usr/bin/env python3
"""Pin an immutable ZooKeeper overlay clone with identical source/class bytes."""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clone(base_receipt: Path, new_root: Path, output: Path, version: str) -> None:
    if output.exists():
        raise FileExistsError(output)
    base = json.loads(base_receipt.read_text(encoding="utf-8"))
    old_root = Path(base["patched_root"])
    if new_root == old_root or not new_root.is_dir():
        raise ValueError("expected a distinct copied overlay source root")
    for relative, digest in base["modified_files"].items():
        if sha(new_root / relative) != digest:
            raise ValueError(f"cloned source differs: {relative}")
    compiled = []
    for artifact in base["compiled_artifacts"]:
        relative = Path(artifact["path"]).relative_to(old_root)
        current = new_root / relative
        if sha(current) != artifact["sha256"]:
            raise ValueError(f"cloned compiled artifact differs: {relative}")
        compiled.append({"path": str(current), "sha256": artifact["sha256"]})
    receipt = dict(base)
    receipt.update(version=version, patched_root=str(new_root),
                   compiled_artifacts=compiled,
                   immutable_clone={
                       "base_overlay_receipt": str(base_receipt),
                       "base_overlay_receipt_sha256": sha(base_receipt),
                       "byte_identity": "all modified source files and compiled artifacts match base receipt",
                       "new_healthy_seed_required": True,
                   })
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_receipt", type=Path)
    parser.add_argument("new_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    clone(args.base_receipt.resolve(), args.new_root.resolve(),
          args.output.resolve(), args.version)
