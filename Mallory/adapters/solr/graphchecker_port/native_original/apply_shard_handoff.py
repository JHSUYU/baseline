#!/usr/bin/env python3
"""Apply or verify the system-wide Solr shard-request scope handoff.

Run after ``install.py`` has installed the pinned GraphChecker transport
adapter. This overlay changes one production executor boundary; no test or
fault site is selected here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
PATCH = HERE / "solr-e27f44e-shard-request-handoff.patch"
RECEIPT = HERE / "shard-request-handoff-receipt.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(source: Path, verify_only: bool) -> dict:
    receipt = json.loads(RECEIPT.read_text())
    if (receipt.get("schema_version") != 1 or
            digest(PATCH) != receipt["overlay_patch_sha256"]):
        raise ValueError("Solr shard handoff overlay receipt changed")
    base = json.loads((HERE / "source_receipt.json").read_text())
    if base["source_commit"] != receipt["source_commit"]:
        raise ValueError("Solr base and shard handoff revisions differ")
    # Validate the already installed production transport adapter by its
    # source hashes. The base installer is responsible for its own patch pin.
    for relative, expected in base["patched_source_sha256"].items():
        if digest(source / relative) != expected:
            raise ValueError("Solr base transport source changed: " + relative)
    for relative, expected in base["unchanged_junit_source_sha256"].items():
        if digest(source / relative) != expected:
            raise ValueError("Solr original JUnit source changed: " + relative)
    if subprocess.check_output(["git", "rev-parse", "HEAD"],
                               cwd=source, text=True).strip() != receipt[
                                   "source_commit"]:
        raise ValueError("Solr source revision differs from overlay receipt")
    target = source / receipt["path"]
    current = digest(target)
    if current == receipt["patched_source_sha256"]:
        return {"status": "verified", "source_sha256": current}
    if verify_only or current != receipt["original_source_sha256"]:
        raise ValueError("Solr shard request source does not match overlay receipt")
    subprocess.run(["git", "apply", "--check", str(PATCH)],
                   cwd=source, check=True)
    subprocess.run(["git", "apply", str(PATCH)], cwd=source, check=True)
    if digest(target) != receipt["patched_source_sha256"]:
        raise ValueError("Solr shard request overlay produced unexpected source")
    return {"status": "applied", "source_sha256": digest(target)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(install(args.source.resolve(strict=True), args.verify_only),
                     sort_keys=True))


if __name__ == "__main__":
    main()
