#!/usr/bin/env python3
"""Compile and verify the case-local gate without starting Solr or a JUnit cluster."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BUILD = HERE / "build/offline"
CONFIG = json.loads((HERE / "config.json").read_text())
AGENT = Path(CONFIG["agent_jar"])
SOLR_ADAPTER = Path(CONFIG["agent_properties"]["adapter.jars"].split(",")[0])
ALIAS_ADAPTER = Path(CONFIG["agent_properties"]["adapter.jars"].split(",")[1])
GATE = HERE / "preemptive-gate.jar"
SOLRJ = Path(CONFIG["mapping"]["compiled_solrj_jar"])


def command(argv: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, env=env)
    if result.returncode:
        raise ValueError(f"{argv[0]} failed ({result.returncode}): {result.stderr[-3000:]}")
    return result.stdout.strip()


def main() -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    stub = HERE / "offline/edu/uva/liftlab/mallory/instrumentation/Probe.java"
    control = HERE / "offline/VerifyWrongPath.java"
    command(["javac", "-source", "8", "-target", "8", "-cp", str(GATE),
             "-d", str(BUILD), str(stub), str(control)])
    env = dict(os.environ, MALLORY_SOLR39_SELECTED_DOORS="node2@0:1")
    gate_cp = os.pathsep.join((str(BUILD), str(GATE)))
    bad = command(["java", "-Xverify:all", "-cp", gate_cp, "VerifyWrongPath", "bad"], env=env)
    good = command(["java", "-Xverify:all", "-cp", gate_cp, "VerifyWrongPath", "good"], env=env)
    if bad != "WRONG_PATH_FAIL_CLOSED_OK" or good != "EXACT_PATH_GATE_OK":
        raise ValueError("actual-resource gate negative/positive control failed")
    sys.path.insert(0, str(ROOT / "Mallory/adapters/solr"))
    import solr_junit_runner_v14 as solr_runner  # noqa: E402
    classpath = solr_runner.classpath(Path(CONFIG["cwd"]),
                                      Path(CONFIG["mapping"]["distribution_root"]), BUILD)
    props = BUILD / "verify-agent.properties"
    props.write_text("\n".join((
        "events=" + str(BUILD / "unused-events.jsonl"),
        "include=org.apache.solr.common.cloud.ZkStateReader$AliasesManager",
        "site.file=" + CONFIG["site_file"],
        "auto.io.doors=true", "coverage.methods=true", "coverage.branches=true",
        "state.fields=true", "state.maps=false", "")))
    verifier = HERE / "offline/VerifyWovenClass.java"
    cp = os.pathsep.join((str(BUILD), str(AGENT), str(SOLR_ADAPTER),
                          str(ALIAS_ADAPTER), str(GATE), classpath))
    command(["javac", "-source", "8", "-target", "8", "-cp", cp,
             "-d", str(BUILD), str(verifier)])
    woven = command(["java", "-Xverify:all", "-Xmx1g", "-cp", cp,
                     "VerifyWovenClass", str(SOLRJ), str(props)])
    if not woven.startswith("WOVEN_CLASS_VERIFY_OK "):
        raise ValueError("woven class did not verify")
    receipt = {"schema_version": 1, "case_id": "SOLR-39",
               "kind": "offline_no_cluster_bytecode_verification",
               "actual_wrong_path_control": bad, "actual_exact_path_control": good,
               "pinned_woven_class": woven,
               "gate_jar_sha256": hashlib.sha256(GATE.read_bytes()).hexdigest(),
               "agent_sha256": hashlib.sha256(AGENT.read_bytes()).hexdigest(),
               "solr_adapter_sha256": hashlib.sha256(SOLR_ADAPTER.read_bytes()).hexdigest(),
               "alias_adapter_sha256": hashlib.sha256(ALIAS_ADAPTER.read_bytes()).hexdigest(),
               "solrj_sha256": hashlib.sha256(SOLRJ.read_bytes()).hexdigest(),
               "junit_or_cluster_started": False}
    (HERE / "offline-verification.json").write_text(json.dumps(receipt, indent=2,
                                                                  sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
