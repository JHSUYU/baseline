#!/usr/bin/env python3
"""Compress completed case-local trial traces with raw and archive hashes."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHUNK = 1024 * 1024


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def compress(path):
    archive = path.with_suffix(path.suffix + ".gz")
    if archive.exists() and not path.exists():
        return None
    raw_hash, raw_size = hash_file(path)
    temporary = archive.with_suffix(archive.suffix + ".partial")
    with path.open("rb") as source, temporary.open("wb") as sink:
        with gzip.GzipFile(filename="", mode="wb", fileobj=sink,
                           compresslevel=1, mtime=0) as packed:
            while block := source.read(CHUNK):
                packed.write(block)
        sink.flush()
        os.fsync(sink.fileno())
    archive_hash, archive_size = hash_file(temporary)
    os.replace(temporary, archive)
    path.unlink()
    return {"raw_path": str(path.relative_to(HERE)),
            "raw_sha256": raw_hash, "raw_bytes": raw_size,
            "archive_path": str(archive.relative_to(HERE)),
            "archive_sha256": archive_hash, "archive_bytes": archive_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", choices=("fuzzer-r2", "fuzzer-v2-single"))
    args = parser.parse_args()
    manifest_path = HERE / (args.campaign + "-trace-manifest.json")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    root = HERE / args.campaign / "ZOOKEEPER-05" / "trials"
    for trial in sorted(root.glob("*")):
        if not (trial / "result.json").exists():
            continue
        trace = trial / "record/runtime/runtime_trace.jsonl"
        if not trace.exists():
            continue
        entry = compress(trace)
        if entry:
            manifest[trial.name] = entry
            temporary = manifest_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(manifest, indent=2,
                                             sort_keys=True) + "\n")
            os.replace(temporary, manifest_path)
            print(trial.name, entry["raw_bytes"], "->",
                  entry["archive_bytes"])


if __name__ == "__main__":
    main()
