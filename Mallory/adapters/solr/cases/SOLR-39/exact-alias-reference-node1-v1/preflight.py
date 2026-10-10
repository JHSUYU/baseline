#!/usr/bin/env python3
"""Offline-only admission for the SOLR-39 exact Aliases-reference diagnostic."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "healthy-source-admission-v2"
SOURCE = ROOT.parent / ".graphchecker-sources/solr-8.11.4"
JAVA = HERE / "src/edu/uva/liftlab/mallory/solr/aliasref"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def main() -> dict:
    pins = load(HERE / "pins.json")
    for name, expected in pins["files"].items():
        path = Path(name) if name.startswith("/") else ROOT / name
        require(path.is_file() and sha(path) == expected, f"missing or changed pin: {path}")
    sealed = ROOT / "data/mallory/healthy_observations/SOLR-39-watcher-node1-healthy-v1"
    result_path = sealed / "result.json"
    audit_path = sealed / "offline-causal-audit.json"
    require(result_path.is_file() and sha(result_path) == pins["sealed_healthy_result_sha256"],
            "sealed healthy result changed")
    require(audit_path.is_file() and sha(audit_path) == pins["sealed_healthy_audit_sha256"],
            "sealed causal audit changed")

    spec = importlib.util.spec_from_file_location("solr39_base_preflight", BASE / "preflight.py")
    require(spec is not None and spec.loader is not None, "base preflight unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prior = module.main()
    require(prior["status"] == "offline_preflight_passed_healthy_only", "base healthy admission failed")

    reader = SOURCE / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    aliases = SOURCE / "solr/solrj/src/java/org/apache/solr/common/cloud/Aliases.java"
    target = SOURCE / "solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"
    for path, expected in ((reader, pins["solr_source"]["reader"]),
                           (aliases, pins["solr_source"]["aliases"]),
                           (target, pins["solr_source"]["target"])):
        require(path.is_file() and sha(path) == expected, f"Solr source changed: {path}")
    source = reader.read_text(encoding="utf-8").splitlines()
    for number, fragment in ((2220, "volatile Aliases aliases"), (2223, "return aliases"),
                             (2312, "zkClient.getData"), (2314, "setIfNewer"),
                             (2336, "boolean setIfNewer"), (2342, "aliases = newAliases")):
        require(fragment in source[number - 1], f"Solr read/write source changed at {reader}:{number}")

    transformer = (JAVA / "AliasValueTransformer.java").read_text(encoding="utf-8")
    trace = (JAVA / "AliasValueTrace.java").read_text(encoding="utf-8")
    for fragment in ("getAliases", "setIfNewer", "Opcodes.GETFIELD", "Opcodes.PUTFIELD",
                     "AliasValueTrace", "ClassWriter.COMPUTE_MAXS"):
        require(fragment in transformer, f"transformer probe missing: {fragment}")
    for fragment in ("IdentityHashMap<Object, Long>", "owner_ref", "aliases_ref", "zk_version"):
        require(fragment in trace, f"exact value probe missing: {fragment}")

    base_config = load(BASE / "config.json")
    adapter = Path(base_config["agent_properties"]["adapter.jar"])
    agent = Path(base_config["agent_jar"])
    require(adapter.is_file() and agent.is_file(), "pinned Java classpath unavailable")
    with zipfile.ZipFile(adapter) as archive:
        entries = set(archive.namelist())
    for name in ("edu/uva/liftlab/mallory/solr/shaded/asm/ClassReader.class",
                 "edu/uva/liftlab/mallory/solr/shaded/asm/ClassWriter.class",
                 "edu/uva/liftlab/mallory/solr/shaded/asm/MethodVisitor.class"):
        require(name in entries, f"pinned shaded ASM class missing: {name}")
    with zipfile.ZipFile(agent) as archive:
        require("edu/uva/liftlab/mallory/instrumentation/Probe.class" in archive.namelist(),
                "pinned Probe class missing")
    require(base_config["calibration_only"] is True and base_config["budget"]["trials"] == 1,
            "base run is no longer healthy only")
    return {"case_id": "SOLR-39", "status": "offline_preflight_passed_healthy_only",
            "pins_sha256": sha(HERE / "pins.json"),
            "base_config_sha256": sha(BASE / "config.json"),
            "runner_sha256": sha(HERE / "run_node1.py"),
            "host": "node1", "jvm_run": False,
            "candidate_state_edge": "watcher process -> setIfNewer aliases reference -> getAliases -> exact target",
            "full_campaign_go": False}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
