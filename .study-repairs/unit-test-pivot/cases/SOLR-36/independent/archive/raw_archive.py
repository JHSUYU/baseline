#!/usr/bin/env python3
"""Stream and verify the two completed SOLR-36/37 raw trial trees.

No command in this program removes source files.  The sink refuses to consume
disk space below its free-space floor; verification streams every tar member.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


TREES = ("campaign/trials", "rpc-stage/campaign/trials")
EXPECTED_FILES = 34998
CHUNK = 4 * 1024 * 1024
MIN_FREE = int(10.5 * 1024 ** 3)


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for data in iter(lambda: source.read(CHUNK), b""):
            result.update(data)
    return result.hexdigest()


def check_free(path: Path) -> int:
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize
    if free < MIN_FREE:
        raise RuntimeError(f"free-space floor violated: {free} < {MIN_FREE}")
    return free


def manifest(base: Path, destination: Path) -> None:
    check_free(base)
    paths = sorted(path for tree in TREES for path in (base / tree).rglob("*"))
    temporary = destination.with_name(destination.name + ".part")
    count = 0
    with temporary.open("x", encoding="utf-8") as output:
        for path in paths:
            if path.is_symlink():
                raise RuntimeError(f"symlink in raw evidence: {path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise RuntimeError(f"unsupported raw evidence entry: {path}")
            before = path.stat()
            item = {"path": path.relative_to(base).as_posix(),
                    "size": before.st_size, "sha256": digest_file(path)}
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f"file changed during manifest: {path}")
            output.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
            if count % 1000 == 0:
                check_free(base)
        output.flush()
        os.fsync(output.fileno())
    if count != EXPECTED_FILES:
        raise RuntimeError(f"expected {EXPECTED_FILES} files, found {count}")
    temporary.replace(destination)
    print(json.dumps({"files": count, "manifest": str(destination),
                      "sha256": digest_file(destination)}), file=sys.stderr)


def source(base: Path) -> None:
    check_free(base)
    tar = subprocess.Popen(
        ["tar", "--sort=name", "--numeric-owner", "-C", str(base), "-cf", "-", *TREES],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert tar.stdout is not None
    compressor = subprocess.Popen(["zstd", "-T2", "-10", "-c"],
                                  stdin=tar.stdout, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
    tar.stdout.close()
    assert compressor.stdout is not None
    transferred = 0
    try:
        for data in iter(lambda: compressor.stdout.read(CHUNK), b""):
            check_free(base)
            sys.stdout.buffer.write(data)
            transferred += len(data)
        sys.stdout.buffer.flush()
        zcode = compressor.wait()
        tcode = tar.wait()
        if tcode or zcode:
            raise RuntimeError(f"tar={tcode}: {tar.stderr.read().decode(errors='replace')}; "
                               f"zstd={zcode}: {compressor.stderr.read().decode(errors='replace')}")
        print(json.dumps({"compressed_bytes_streamed": transferred,
                          "node2_free_bytes": check_free(base)}), file=sys.stderr)
    except BaseException:
        compressor.kill()
        tar.kill()
        compressor.wait()
        tar.wait()
        raise


def sink(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    check_free(destination.parent)
    written = 0
    with destination.open("xb") as output:
        for data in iter(lambda: sys.stdin.buffer.read(CHUNK), b""):
            if check_free(destination.parent) - len(data) < MIN_FREE:
                raise RuntimeError("archive would cross node1 free-space floor")
            output.write(data)
            written += len(data)
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({"archive_part": str(destination), "bytes": written,
                      "sha256": digest_file(destination),
                      "node1_free_bytes": check_free(destination.parent)}), file=sys.stderr)


def verify(archive: Path, manifest_path: Path) -> None:
    expected = {}
    with manifest_path.open(encoding="utf-8") as source_manifest:
        for line in source_manifest:
            item = json.loads(line)
            if item["path"] in expected:
                raise RuntimeError(f"duplicate manifest path {item['path']}")
            expected[item["path"]] = item
    if len(expected) != EXPECTED_FILES:
        raise RuntimeError(f"manifest has {len(expected)} files")
    decompressor = subprocess.Popen(["zstd", "-dc", "--", str(archive)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert decompressor.stdout is not None
    seen = set()
    with tarfile.open(fileobj=decompressor.stdout, mode="r|") as stream:
        for member in stream:
            if member.isdir():
                continue
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise RuntimeError(f"unexpected tar member {member.name}")
            item = expected[member.name]
            if member.size != item["size"]:
                raise RuntimeError(f"size differs: {member.name}")
            payload = stream.extractfile(member)
            if payload is None:
                raise RuntimeError(f"unreadable tar member {member.name}")
            digest = hashlib.sha256()
            for data in iter(lambda: payload.read(CHUNK), b""):
                digest.update(data)
            if digest.hexdigest() != item["sha256"]:
                raise RuntimeError(f"content differs: {member.name}")
            seen.add(member.name)
    for _ in iter(lambda: decompressor.stdout.read(CHUNK), b""):
        pass
    code = decompressor.wait()
    if code or seen != expected.keys():
        missing = sorted(expected.keys() - seen)[:5]
        raise RuntimeError(f"zstd exit={code}, verified={len(seen)}, missing={missing}; "
                           + decompressor.stderr.read().decode(errors="replace"))
    print(json.dumps({"archive": str(archive), "archive_sha256": digest_file(archive),
                      "manifest_sha256": digest_file(manifest_path),
                      "verified_files": len(seen),
                      "node1_free_bytes": check_free(archive.parent)}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, args in (("manifest", ("base", "output")),
                       ("source", ("base",)),
                       ("sink", ("output",)),
                       ("verify", ("archive", "manifest"))):
        command = sub.add_parser(name)
        for arg in args:
            command.add_argument(arg, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "manifest":
        manifest(arguments.base, arguments.output)
    elif arguments.command == "source":
        source(arguments.base)
    elif arguments.command == "sink":
        sink(arguments.output)
    else:
        verify(arguments.archive, arguments.manifest)


if __name__ == "__main__":
    main()
