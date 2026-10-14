#!/usr/bin/env python3
"""Apply or verify the general serialized-message scope on native Solr.

Run after the original GraphChecker transport overlay. The unchanged JUnit and
all automatically selected static I/O doors remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "solr-e27f44e-native-payload-replay.patch"
RECEIPT = HERE / "native-payload-replay-receipt.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(source: Path, verify_only: bool = False,
            source_attestation: Path | None = None) -> dict:
    receipt = json.loads(RECEIPT.read_text())
    base = json.loads((HERE / "source_receipt.json").read_text())
    target = source / receipt["path"]
    if source_attestation is None:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                         cwd=source, text=True).strip()
    else:
        attested = json.loads(source_attestation.read_text())
        expected = {"schema_version": 1, "source_root": str(source),
                    "source_commit": base["source_commit"],
                    "patch_sha256": base["patch_sha256"],
                    "patched_source_sha256": base["patched_source_sha256"],
                    "unchanged_junit_source_sha256":
                        base["unchanged_junit_source_sha256"]}
        if attested != expected:
            raise ValueError("native Solr source attestation changed")
        commit = attested["source_commit"]
    if (receipt.get("schema_version") != 1 or
            receipt["source_commit"] != base["source_commit"] or
            receipt["base_patch_sha256"] != base["patch_sha256"] or
            receipt["original_source_sha256"] !=
            base["patched_source_sha256"][receipt["path"]] or
            sha(PATCH) != receipt["overlay_patch_sha256"] or
            commit != receipt["source_commit"]):
        raise ValueError("native Solr message overlay source pin changed")
    for relative, expected in base["patched_source_sha256"].items():
        if relative != receipt["path"] and sha(source / relative) != expected:
            raise ValueError("base native Solr source changed: " + relative)
    for relative, expected in base["unchanged_junit_source_sha256"].items():
        if sha(source / relative) != expected:
            raise ValueError("original Solr JUnit source changed: " + relative)
    current = sha(target)
    if current == receipt["patched_source_sha256"]:
        return {"status": "verified", "source_sha256": current}
    if verify_only or current != receipt["original_source_sha256"]:
        raise ValueError("native Solr queue source differs from overlay pin")
    subprocess.run(["git", "apply", "--check", str(PATCH)],
                   cwd=source, check=True)
    subprocess.run(["git", "apply", str(PATCH)], cwd=source, check=True)
    if sha(target) != receipt["patched_source_sha256"]:
        raise ValueError("native Solr message overlay produced unexpected bytes")
    return {"status": "applied", "source_sha256": sha(target)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--source-attestation", type=Path)
    args = parser.parse_args()
    print(json.dumps(install(args.source.resolve(strict=True), args.verify_only,
                             args.source_attestation),
                     sort_keys=True))


if __name__ == "__main__":
    main()
