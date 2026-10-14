#!/usr/bin/env python3
"""Compile the attested Solr protocol adapter against the pinned original engine."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
RECEIPT = HERE / "source_receipt.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    classes = sorted(root.rglob("*.class"))
    if not classes:
        raise ValueError("javac produced no classes")
    for path in classes:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--classpath-file", type=Path, required=True)
    parser.add_argument("--engine-jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-attestation", type=Path)
    parser.add_argument("--shard-handoff", action="store_true",
                        help="include the verified generic shard-request worker handoff")
    parser.add_argument("--javac", default="javac")
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    engine = args.engine_jar.resolve(strict=True)
    classpath_file = args.classpath_file.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("refusing to overwrite an existing class tree: " + str(output))
    receipt = json.loads(RECEIPT.read_text())
    if sha256(engine) != receipt["native_engine_jar_sha256_at_compile"]:
        raise ValueError("original GraphChecker engine does not match the pinned build")
    attestation_sha256 = ""
    if args.source_attestation is None:
        subprocess.run([sys.executable, str(HERE / "install.py"),
                        "--source", str(source), "--verify-only"], check=True)
    else:
        attestation_path = args.source_attestation.resolve(strict=True)
        attestation = json.loads(attestation_path.read_text())
        required = {
            "schema_version": 1,
            "source_root": str(source),
            "source_commit": receipt["source_commit"],
            "patch_sha256": receipt["patch_sha256"],
            "patched_source_sha256": receipt["patched_source_sha256"],
            "unchanged_junit_source_sha256": receipt["unchanged_junit_source_sha256"],
        }
        if attestation != required:
            raise ValueError("source attestation differs from pinned Solr source")
        if sha256(HERE / "solr-e27f44e-original-engine.patch") != receipt["patch_sha256"]:
            raise ValueError("native Solr patch differs from the source receipt")
        for relative, expected in {**receipt["patched_source_sha256"],
                                   **receipt["unchanged_junit_source_sha256"]}.items():
            if sha256(source / relative) != expected:
                raise ValueError("attested Solr source changed: " + relative)
        attestation_sha256 = sha256(attestation_path)
    classpath = classpath_file.read_text().strip()
    if not classpath:
        raise ValueError("empty Solr dependency classpath")
    for entry in classpath.split(os.pathsep):
        if not Path(entry).exists():
            raise ValueError("missing dependency: " + entry)
    sources = sorted(source / relative for relative in
                     receipt["patched_source_sha256"] if relative.endswith(".java"))
    shard_handoff = None
    if args.shard_handoff:
        from apply_shard_handoff import RECEIPT as SHARD_RECEIPT, install as verify_shard
        verify_shard(source, verify_only=True)
        shard_handoff = json.loads(SHARD_RECEIPT.read_text())
        sources.append(source / shard_handoff["path"])
    sources.append(HERE / "NativeSolrJUnitRunner.java")
    output.mkdir(parents=True)
    subprocess.run([args.javac, "-source", "8", "-target", "8",
                    "-implicit:none", "-d", str(output), "-cp",
                    str(engine) + os.pathsep + classpath,
                    *(str(path) for path in sources)], check=True)
    build = {
        "schema_version": 1,
        "source_commit": receipt["source_commit"],
        "source_patch_sha256": receipt["patch_sha256"],
        "engine_jar_sha256": sha256(engine),
        "dependency_classpath_sha256": hashlib.sha256(
            classpath.encode("utf-8")).hexdigest(),
        "runner_source_sha256": sha256(HERE / "NativeSolrJUnitRunner.java"),
        "source_attestation_sha256": attestation_sha256,
        "classes_sha256": tree_sha256(output),
    }
    if shard_handoff is not None:
        build["shard_handoff_patch_sha256"] = shard_handoff["overlay_patch_sha256"]
        build["shard_handoff_source_sha256"] = shard_handoff["patched_source_sha256"]
    output.with_name(output.name + "-receipt.json").write_text(
        json.dumps(build, indent=2, sort_keys=True) + "\n")
    print(json.dumps(build, sort_keys=True))


if __name__ == "__main__":
    main()
