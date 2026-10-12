#!/usr/bin/env python3
"""SOLR-10 role binding runner; verify exact release and source before JUnit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


HERE = Path(__file__).resolve().parent
SOLR_ADAPTER = HERE.parents[1]
sys.path.insert(0, str(SOLR_ADAPTER))
import solr_junit_runner_v8 as junit_runner  # noqa: E402


AGENT = HERE / "releases/v1/mallory-agent.jar"
ADAPTER = HERE / "releases/v1/mallory-solr-adapter.jar"
INVENTORY = SOLR_ADAPTER / "releases/v10/inventory.json"
HEALTHY_CONFIG = HERE / "config-role-v1-healthy-node2.json"
EXPECTED = {
    "source_head": "e27f44e3d78dfcec230c97e0a1240e3751daeff9",
    "overseer_source": "cae75fa3ae928f085b69dd5d39c4bac978b7d1160692b936b934f8a59838c14b",
    "target_source": "d9943be304693226243d34e7cc0ae47df26b621c8293b6e8aabe6941c0469db7",
    "test_source": "727cc38dd0fd0d42e641724b08d96b00e0e9d8ab492d23cbc572284824079d37",
    "solr_core_jar": "e83db498c6af8f3eca14483ab42fd9fe30bbf795ceacab3b4d5eaa66f2461536",
    "overseer_class": "98f21c0235c5e9dc7937d67e0a44dfeccd3726582feb2696d7fbe4420ca8a6c0",
    "target_class": "e49a19168470644792b32674984a3250e1860116ac873c92df494f60de455d28",
    "agent": "ef144323bc4bd2e7a231fc41ae35a7ec4255455146823ad177ebe3735f99ffb9",
    "adapter": "8dd63b244ea6073b7cabccf0d539076656a2197cf97dbf2778bef1dafbe3a7da",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(label: str, actual: str) -> str:
    expected = EXPECTED[label]
    if actual != expected:
        raise ValueError(f"{label}: SHA mismatch: expected {expected}, got {actual}")
    return actual


def preflight(source: Path, distribution: Path) -> dict[str, str]:
    source = source.resolve(strict=True)
    distribution = distribution.resolve(strict=True)
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    check("source_head", head)
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True)
    if dirty.strip():
        raise ValueError("source worktree is dirty; refusing role pilot")
    files = {
        "overseer_source": source / "solr/core/src/java/org/apache/solr/cloud/OverseerTaskProcessor.java",
        "target_source": source / "solr/core/src/java/org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd.java",
        "test_source": source / "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java",
        "solr_core_jar": distribution / "dist/solr-core-8.11.4.jar",
        "agent": AGENT,
        "adapter": ADAPTER,
    }
    actual = {name: check(name, digest(path.read_bytes())) for name, path in files.items()}
    with zipfile.ZipFile(files["solr_core_jar"]) as archive:
        actual["overseer_class"] = check("overseer_class", digest(archive.read(
            "org/apache/solr/cloud/OverseerTaskProcessor.class")))
        actual["target_class"] = check("target_class", digest(archive.read(
            "org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd.class")))
    if not INVENTORY.is_file():
        raise ValueError(f"missing inventory: {INVENTORY}")
    config = json.loads(HEALTHY_CONFIG.read_text())
    if config.get("revision") != "SOLR-10-overseer-role-v1-healthy-node2":
        raise ValueError("role-v1 healthy config revision differs")
    if config.get("agent_jar") != str(AGENT) or config.get("agent_properties", {}).get("adapter.jar") != str(ADAPTER):
        raise ValueError("role-v1 config uses different runtime jars")
    for artifact in config.get("runtime_artifacts", []):
        path = Path(artifact["path"])
        if digest(path.read_bytes()) != artifact["sha256"]:
            raise ValueError(f"runtime artifact SHA mismatch: {path}")
    actual["healthy_config_sha256"] = digest(HEALTHY_CONFIG.read_bytes())
    actual["source_head"] = head
    actual["source_path"] = str(source)
    actual["distribution_path"] = str(distribution)
    actual["agent_path"] = str(AGENT)
    actual["adapter_path"] = str(ADAPTER)
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=["SOLR-10"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        receipt = preflight(args.source, args.distribution)
    except (OSError, subprocess.CalledProcessError, ValueError, zipfile.BadZipFile) as failure:
        print(json.dumps({"preflight": "failed", "reason": str(failure)}, sort_keys=True))
        return 2
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", **receipt}, sort_keys=True))
        return 0
    junit_runner.AGENT = AGENT
    junit_runner.ADAPTER = ADAPTER
    junit_runner.INVENTORY = INVENTORY
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    result = junit_runner.run(args.case_id, args.source, args.distribution,
                              args.output, args.timeout, args.campaign, False)
    print(json.dumps({"preflight": receipt, "result": result}, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
