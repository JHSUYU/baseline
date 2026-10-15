"""Losslessly archive one accepted local native trial before freeing raw bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def members(root: Path, path: Path) -> dict[str, tuple]:
    found: dict[str, tuple] = {}
    for member in [path, *path.rglob("*")]:
        name = str(member.relative_to(root))
        if member.is_symlink():
            found[name] = ("symlink", os.readlink(member))
        elif member.is_file():
            found[name] = ("file", member.stat().st_size, sha(member))
        elif member.is_dir():
            found[name] = ("dir",)
        else:
            raise ValueError(f"unsupported local artifact: {member}")
    return found


def archive(output: Path, raw_root: Path, archive_root: Path,
            index: int) -> dict:
    if index < 0:
        raise ValueError("trial index must be nonnegative")
    result_dir = output / "trials" / f"r{index:04d}"
    checkpoint = json.loads((output / "checkpoint.json").read_text())
    result_file = result_dir / "result.json"
    result = json.loads(result_file.read_text())
    if index and (checkpoint["completed_fault_trials"] < index or
                  checkpoint.get("active") is not None or
                  result.get("strict_injection") is not True):
        raise ValueError("only a strict accepted fault may be archived")
    if not index and result.get("status") != "healthy_seed":
        raise ValueError("r0000 must be the accepted healthy seed")
    if subprocess.run(["pgrep", "-x", "java"], capture_output=True).stdout:
        raise RuntimeError("cannot archive while Java runs")
    manifest = json.loads((result_dir / "local-artifacts.json").read_text())
    raw_root = raw_root.resolve(strict=True)
    attempt = Path(manifest["local_attempt_dir"]).resolve(strict=True)
    if not attempt.is_relative_to(raw_root):
        raise ValueError("raw attempt escaped pinned root")
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"raw-r{index:04d}.tar.gz"
    receipt_path = archive_root / f"raw-r{index:04d}-receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("archive_sha256") != sha(target) or
                receipt.get("result_sha256") != sha(result_file) or
                receipt.get("verified_against_source") is not True):
            raise ValueError("archive receipt changed")
        return receipt
    if target.exists():
        raise ValueError("archive exists without receipt")
    expected = members(raw_root, attempt)
    partial = target.with_name(target.name + ".partial")
    if partial.exists():
        raise ValueError("partial archive exists; inspect before retry")
    with tarfile.open(partial, "w:gz", dereference=False) as bundle:
        bundle.add(attempt, arcname=str(attempt.relative_to(raw_root)),
                   recursive=True)
    actual: dict[str, tuple] = {}
    with tarfile.open(partial, "r:gz") as bundle:
        for entry in bundle:
            name = entry.name.rstrip("/")
            if entry.isfile():
                stream = bundle.extractfile(entry)
                if stream is None:
                    raise ValueError("unreadable archive file")
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
                actual[name] = ("file", entry.size, digest.hexdigest())
            elif entry.issym():
                actual[name] = ("symlink", entry.linkname)
            elif entry.isdir():
                actual[name] = ("dir",)
            else:
                raise ValueError(f"unsupported tar entry: {entry.name}")
    if expected != actual:
        raise ValueError("archive content differs from source; source retained")
    partial.rename(target)
    receipt = {"trial_index": index, "archive_sha256": sha(target),
               "archive_size_bytes": target.stat().st_size,
               "result_sha256": sha(result_file), "member_count": len(actual),
               "verified_against_source": True,
               "restore_command": f"tar -xzf {target} -C {raw_root}"}
    with receipt_path.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    shutil.rmtree(attempt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--index", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(archive(args.output, args.raw_root,
                             args.archive_root, args.index), sort_keys=True))


if __name__ == "__main__":
    main()
