#!/usr/bin/env python3
"""Materialize exact HBase test classes in this trial's writable classpath."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
HELPER = "org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.class"
ANCHOR = "org/apache/hadoop/hbase/security/token/SecureTestCluster.class"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(trial: Path, pins: dict) -> Path:
    if not trial.is_dir() or not trial.name.startswith("r"):
        raise ValueError("expected existing Mallory trial directory")
    result = trial / "hbase34-testclasses"
    result.mkdir(mode=0o700, exist_ok=True)
    for source, member, expected in (
        (Path(pins["helper_jar"]["path"]), HELPER, pins["helper_jar"]["class_sha256"]),
        (Path(pins["anchor_tests_jar"]["path"]), ANCHOR,
         pins["anchor_tests_jar"]["class_sha256"]),
    ):
        if sha(source.read_bytes()) != pins[
            "helper_jar" if member == HELPER else "anchor_tests_jar"]["sha256"]:
            raise ValueError(f"pinned source jar changed: {source}")
        with zipfile.ZipFile(source) as archive:
            bytecode = archive.read(member)
        if sha(bytecode) != expected:
            raise ValueError(f"pinned class changed: {member}")
        dest = result / member
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(dest.suffix + ".tmp")
        temporary.write_bytes(bytecode)
        temporary.replace(dest)
    return result


def main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit("usage: run_case.py TRIAL_DIR JAVA ARGS...")
    pins = json.loads((HERE / "manifest.json").read_text())
    trial = Path(sys.argv[1]).resolve()
    directory = prepare(trial, pins)
    command = sys.argv[2:]
    if command[0] != "/usr/lib/jvm/java-8-openjdk-amd64/bin/java" or \
            command.count("-cp") != 1:
        raise ValueError("unrecognized pinned HBASE-34 Java command")
    cp = command[command.index("-cp") + 1].split(":")
    if str(directory) not in cp or cp.index(str(directory)) >= cp.index(
            "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/*"):
        raise ValueError("trial class directory must precede test jar wildcard")
    os.execv(command[0], command)
    raise AssertionError("execv returned")


if __name__ == "__main__":
    raise SystemExit(main())
