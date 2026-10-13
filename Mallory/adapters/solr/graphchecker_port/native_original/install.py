#!/usr/bin/env python3
"""Apply or verify the original GraphChecker Solr protocol patch at e27f44e."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
RECEIPT = HERE / "source_receipt.json"
PATCH = HERE / "solr-e27f44e-original-engine.patch"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=source, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--write-attestation", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    receipt = json.loads(RECEIPT.read_text())
    if git(source, "rev-parse", "HEAD") != receipt["source_commit"]:
        raise ValueError("Solr source revision differs from the pinned commit")
    if sha256(PATCH) != receipt["patch_sha256"]:
        raise ValueError("native Solr patch differs from the source receipt")
    if not args.verify_only:
        if git(source, "status", "--porcelain"):
            raise ValueError("native Solr patch requires a clean source checkout")
        subprocess.run(["git", "apply", "--check", str(PATCH)], cwd=source,
                       check=True)
        subprocess.run(["git", "apply", str(PATCH)], cwd=source, check=True)
    for relative, expected in receipt["patched_source_sha256"].items():
        path = source / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("patched Solr source mismatch: " + relative)
    for relative, expected in receipt["unchanged_junit_source_sha256"].items():
        path = source / relative
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("original JUnit source changed: " + relative)
    if args.write_attestation is not None:
        target = args.write_attestation.resolve()
        if target.exists():
            raise ValueError("refusing to overwrite source attestation: " + str(target))
        attestation = {
            "schema_version": 1,
            "source_root": str(source),
            "source_commit": receipt["source_commit"],
            "patch_sha256": receipt["patch_sha256"],
            "patched_source_sha256": receipt["patched_source_sha256"],
            "unchanged_junit_source_sha256": receipt["unchanged_junit_source_sha256"],
        }
        target.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    print("native Solr protocol source attested")


if __name__ == "__main__":
    main()
