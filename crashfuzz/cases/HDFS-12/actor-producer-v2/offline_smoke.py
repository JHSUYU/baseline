#!/usr/bin/env python3
"""Compile, weave, verify, and reject bad selectors without running JUnit."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import run_original

HERE = Path(__file__).resolve().parent


def run_checked(argv: list[str], cp: str | None = None) -> str:
    command = argv if cp is None else [argv[0], "-Xverify:all", "-cp", cp, *argv[1:]]
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def main() -> None:
    run_original.build()
    env = dict(os.environ, JAVA_HOME=str(run_original.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(run_original.HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    cp = os.pathsep.join((str(run_original.OVERLAY), str(run_original.BUILD / "classes"),
                          str(run_original.TESTS), str(run_original.COMMON_TESTS),
                          hadoop_cp, *(str(p) for p in sorted(
                              (run_original.HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    verifier = run_checked([str(run_original.JDK / "java"), "Hdfs12OverlayVerifier"], cp)
    selector = run_checked([str(run_original.JDK / "java"), "Hdfs12ProducerSelectorSmoke"], cp)
    tests = run_checked([sys.executable, "-m", "unittest", "-v",
                         "test_identity_gate.py", "test_scheduler.py",
                         "test_producer_seed.py"])
    class_checks = {
        "BPServiceActor": ("HdfsKeyActorProbe.keyResponse", 1),
        "BPOfferService": ("HdfsKeyActorProbe.keyImportBefore", 2),
    }
    bytecode_checks = {}
    for name, (probe, count) in class_checks.items():
        disassembly = subprocess.check_output([
            str(run_original.JDK / "javap"), "-c", "-p", "-classpath",
            str(run_original.OVERLAY),
            "org.apache.hadoop.hdfs.server.datanode." + name,
        ], text=True)
        actual = disassembly.count(probe)
        if actual != count:
            raise AssertionError(f"{name} {probe}: {actual} != {count}")
        bytecode_checks[name] = {"probe": probe, "count": actual}
    receipt = {
        "schema": "hdfs12-producer-offline-smoke-1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "overlay_digest_sha256": run_original.digest(),
        "sources_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(HERE.glob("*.java"))
        },
        "released_artifacts_sha256": {
            "hadoop_hdfs_3_4_3": hashlib.sha256(run_original.HDFS.read_bytes()).hexdigest(),
            "hadoop_hdfs_tests_3_4_3": hashlib.sha256(run_original.TESTS.read_bytes()).hexdigest(),
        },
        "coverage_collector_sha256": hashlib.sha256(
            (HERE / "CoverageHdfs11.java").read_bytes()).hexdigest(),
        "weaved_class_verification": verifier.splitlines(),
        "fail_closed_selector": selector.strip(),
        "bytecode_hooks": bytecode_checks,
        "python_gate_tests": tests.splitlines()[-3:],
        "original_junit_executed": False,
    }
    receipt_path = HERE / "offline-smoke-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(receipt_path), "overlay_digest_sha256":
                      receipt["overlay_digest_sha256"], "verified_classes": len(verifier.splitlines()),
                      "selector": selector.strip()}, sort_keys=True))


if __name__ == "__main__":
    main()
