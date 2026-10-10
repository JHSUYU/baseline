#!/usr/bin/env python3
"""Dispatch-GO-gated, one-trial SOLR-39 Aliases identity observation on node1."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

import preflight

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "healthy-source-admission-v2"
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT = ROOT / "data/mallory/healthy_observations/SOLR-39-aliasref-node1-healthy-v1"
BUILD = HERE / "build"
DISK_FLOOR = 7_650_410_496
MEM_FLOOR_KIB = 8_388_608
PACKAGE = "edu/uva/liftlab/mallory/solr/aliasref"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_competing_jvm() -> None:
    processes = subprocess.check_output(["ps", "-u", str(os.getuid()), "-o", "comm="],
                                        text=True).splitlines()
    if any(name.strip() in {"java", "mvn", "javac"} for name in processes):
        raise ValueError("competing user JVM or Maven process")


def build_jar(adapter: Path, agent: Path) -> Path:
    classes = BUILD / "classes"
    if BUILD.exists():
        raise ValueError("case-local build already exists; preserve it for audit")
    classes.mkdir(parents=True)
    source = HERE / "src" / PACKAGE
    subprocess.run(["javac", "-source", "8", "-target", "8", "-cp",
                    os.pathsep.join((str(adapter), str(agent))), "-d", str(classes),
                    str(source / "AliasValueTrace.java"), str(source / "AliasValueTransformer.java")],
                   check=True)
    jar = BUILD / "alias-value-adapter.jar"
    with zipfile.ZipFile(jar, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for klass in sorted(classes.rglob("*.class")):
            archive.write(klass, klass.relative_to(classes))
    with zipfile.ZipFile(jar) as archive:
        names = set(archive.namelist())
    if not {PACKAGE + "/AliasValueTrace.class", PACKAGE + "/AliasValueTransformer.class"} <= names:
        raise ValueError("compiled diagnostic classes missing")
    return jar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight.main()
    if args.preflight_only:
        print(json.dumps(evidence, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("case-local dispatch GO receipt required before any JVM")
    grant = json.loads(args.admission_receipt.read_text(encoding="utf-8"))
    expected = {"go": True, "case_id": "SOLR-39", "host": "node1", "mode": "healthy",
                "pins_sha256": evidence["pins_sha256"],
                "base_config_sha256": evidence["base_config_sha256"],
                "runner_sha256": evidence["runner_sha256"],
                "intended_output": str(OUT)}
    if any(grant.get(key) != value for key, value in expected.items()):
        raise ValueError("dispatch GO receipt differs from isolated diagnostic package")
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("diagnostic must run on node1")
    if OUT.exists() or BUILD.exists():
        raise ValueError("diagnostic output or build must be fresh")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        no_competing_jvm()
        if shutil.disk_usage(ROOT).free < DISK_FLOOR:
            raise ValueError("insufficient free disk before JVM")
        mem_kib = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                       if row.startswith("MemAvailable:"))
        if mem_kib < MEM_FLOOR_KIB:
            raise ValueError("insufficient available memory before JVM")
        base = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        adapter = Path(base["agent_properties"]["adapter.jar"])
        agent = Path(base["agent_jar"])
        jar = build_jar(adapter, agent)
        config = dict(base)
        config["revision"] = "SOLR-39-exact-alias-reference-node1-v1-healthy-only"
        config["env"] = dict(base["env"], MALLORY_ALIAS_REF_TRACE="1")
        config["agent_properties"] = dict(base["agent_properties"])
        config["agent_properties"].pop("adapter.jar", None)
        config["agent_properties"].pop("adapter.transformer", None)
        config["agent_properties"]["adapter.jars"] = str(adapter) + "," + str(jar)
        config["agent_properties"]["adapter.transformers"] = (
            "edu.uva.liftlab.mallory.solr.SolrTransformer,"
            "edu.uva.liftlab.mallory.solr.aliasref.AliasValueTransformer")
        config["runtime_artifacts"] = list(base["runtime_artifacts"]) + [
            {"path": str(jar), "sha256": sha(jar)}]
        config["mapping"] = dict(base["mapping"],
                                  exact_alias_reference_diagnostic=True,
                                  exact_alias_reference_adapter_sha256=sha(jar))
        config_path = BUILD / "config.json"
        config_path.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign

        campaign.validate_config(config)
        state = campaign.run(config_path, OUT)
        print(json.dumps({"case_id": "SOLR-39", "status": state["status"],
                          "completed_trials": state["completed_trials"],
                          "alias_ref_adapter_sha256": sha(jar)}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
