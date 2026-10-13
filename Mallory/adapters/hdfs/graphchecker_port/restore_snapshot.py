#!/usr/bin/env python3
"""Restore the pinned HDFS protocol pilot's ephemeral exact-CP inputs.

The campaign checkpoint is durable on the project mount. This command only
restores missing byte-identical /dev/shm and /tmp inputs after a node restart;
it never replaces an existing, different input.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


def digest(path: Path) -> str:
    hash_value = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                hash_value.update(block)
    elif path.is_dir():
        for member in sorted(path.rglob("*")):
            if member.is_symlink():
                raise ValueError(f"symlink in pinned input: {member}")
            relative = member.relative_to(path).as_posix().encode()
            hash_value.update(relative + b"\0")
            if member.is_file():
                hash_value.update(bytes.fromhex(digest(member)))
    else:
        raise FileNotFoundError(path)
    return hash_value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path,
                        help="durable directory containing inputs/")
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    cp_file = snapshot / "inputs" / "mallory-hdfs32-protocol-cp-v1.txt"
    for name in cp_file.read_text(encoding="utf-8").strip().split(":"):
        if not (name.startswith("/dev/shm/") or name.startswith("/tmp/")):
            continue
        destination = Path(name)
        source = snapshot / "inputs" / destination.name
        if not source.exists():
            raise FileNotFoundError(f"pinned copy missing: {source}")
        expected = digest(source)
        if destination.exists():
            if digest(destination) != expected:
                raise ValueError(f"existing exact-CP input differs: {destination}")
            print(f"verified {destination}")
            continue
        temporary = destination.with_name(destination.name + ".restoring")
        if temporary.exists():
            raise FileExistsError(f"incomplete prior restore: {temporary}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, temporary)
        else:
            shutil.copy2(source, temporary)
        if digest(temporary) != expected:
            raise ValueError(f"restored bytes differ: {temporary}")
        temporary.rename(destination)
        print(f"restored {destination}")


if __name__ == "__main__":
    main()
