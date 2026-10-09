#!/usr/bin/env python3
"""Archive the exact patched ZooKeeper source and compiled classes for a case."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(receipt_path: Path, config_path: Path, output: Path) -> str:
    if output.exists():
        raise FileExistsError(output)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(receipt["patched_root"])
    if config["source_overlay_receipt_sha256"] != sha(receipt_path):
        raise ValueError("config does not pin the source overlay receipt")
    entries = dict(receipt["modified_files"])
    for artifact in receipt["compiled_artifacts"]:
        relative = str(Path(artifact["path"]).relative_to(root))
        entries[relative] = artifact["sha256"]
    mapping = config["mapping"]
    entries[mapping["test_source_path"]] = mapping["test_source_sha256"]
    entries[config["target"]["source_path"]] = mapping["target_source_sha256"]
    if not entries or any(sha(root / path) != digest for path, digest in entries.items()):
        raise ValueError("overlay source/class hash differs from receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as packed:
            for relative in sorted(entries):
                packed.add(root / relative, arcname=relative, recursive=False)
        with tarfile.open(temporary, "r:gz") as packed:
            actual = {}
            for member in packed:
                if not member.isfile() or member.name not in entries:
                    raise ValueError(f"unexpected snapshot member: {member.name}")
                stream = packed.extractfile(member)
                if stream is None:
                    raise ValueError(f"unreadable snapshot member: {member.name}")
                actual[member.name] = hashlib.sha256(stream.read()).hexdigest()
            if actual != entries:
                raise ValueError("source/class archive differs from receipt")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return sha(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("receipt", "config", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(archive(*(getattr(args, name).resolve() for name in
                    ("receipt", "config", "output"))))
