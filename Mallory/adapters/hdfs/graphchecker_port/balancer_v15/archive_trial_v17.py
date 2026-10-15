"""Losslessly archive a successor trial by its absolute result name.

An imported predecessor can start a new fault at r0017 while the successor's
completed_fault_trials is only one. Acceptance is established by the exact
checkpoint trial record, never by comparing the directory number to that
local count.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
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


def _campaign_java_running(output: Path, raw_root: Path,
                           proc_root: Path = Path("/proc")) -> bool:
    """Ignore unrelated Java while guarding this exact campaign's raw files.

    A completed checkpoint already proves the guarded runner returned after
    its JUnit process. This check catches a leaked JVM whose command, cwd or
    open file still names the output/raw tree; another campaign cannot block
    archiving this one.
    """
    roots = (output.resolve(), raw_root.resolve())

    def within(path: str) -> bool:
        if not path.startswith("/"):
            return False
        candidate = Path(path.removesuffix(" (deleted)")).resolve(strict=False)
        return any(candidate == root or candidate.is_relative_to(root)
                   for root in roots)

    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            if process.stat().st_uid != os.getuid() or (process / "comm").read_text().strip() != "java":
                continue
            arguments = (process / "cmdline").read_bytes().split(b"\0")
            if any((within(text) or any(str(root) in text for root in roots))
                   for value in arguments if value
                   for text in (value.decode("utf-8", "surrogateescape"),)):
                return True
            for link in (process / "cwd", *(process / "fd").iterdir()):
                try:
                    if within(os.readlink(link)):
                        return True
                except (FileNotFoundError, OSError):
                    continue
        except FileNotFoundError:
            continue  # Process ended during the scan.
    return False


def archive(output: Path, raw_root: Path, archive_root: Path,
            index: int) -> dict:
    if index < 0:
        raise ValueError("trial index must be nonnegative")
    result_dir = output / "trials" / f"r{index:04d}"
    checkpoint = json.loads((output / "checkpoint.json").read_text())
    result_file = result_dir / "result.json"
    result = json.loads(result_file.read_text())
    if checkpoint.get("active") is not None:
        raise ValueError("only an inactive checkpoint may be archived")
    if index:
        matches = [entry for entry in checkpoint.get("trials", [])
                   if entry.get("name") == f"r{index:04d}"]
        if (len(matches) != 1 or
                matches[0].get("result") != f"trials/r{index:04d}/result.json" or
                matches[0].get("strict_injection") is not True or
                result.get("strict_injection") is not True or
                result.get("case_id") != checkpoint.get("case_id")):
            raise ValueError("only an exact strict accepted trial may be archived")
    elif (result.get("status") != "healthy_seed" or
          result.get("case_id") != checkpoint.get("case_id") or
          checkpoint.get("healthy", {}).get("result") != "trials/r0000/result.json"):
        raise ValueError("r0000 must be the accepted healthy seed")
    if _campaign_java_running(output, raw_root):
        raise RuntimeError("cannot archive while this campaign Java runs")
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
    manifest = json.loads((result_dir / "local-artifacts.json").read_text())
    raw_root = raw_root.resolve(strict=True)
    attempt = Path(manifest["local_attempt_dir"]).resolve(strict=True)
    if not attempt.is_relative_to(raw_root):
        raise ValueError("raw attempt escaped pinned root")
    # Every resumed multi-anchor campaign verifies the healthy graph summary
    # through this symlink. Keep its verified source directory live; the tar is
    # a second, lossless copy, not a replacement for a required input.
    healthy_graph = result_dir / "original-graph"
    retain_source = bool(index == 0 and healthy_graph.is_symlink() and
                         healthy_graph.resolve(strict=True).is_relative_to(
                             attempt))
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
               "source_retained_for_resume": retain_source,
               "restore_command": f"tar -xzf {target} -C {raw_root}"}
    with receipt_path.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    if not retain_source:
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
