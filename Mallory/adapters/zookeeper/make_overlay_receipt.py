#!/usr/bin/env python3
"""Describe a compiled, isolated ZooKeeper source overlay for dispatch."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
HELPER = Path("zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/MalloryZkHooks.java")
TEST_SOURCES = (
    "zookeeper-server/src/test/java/org/apache/zookeeper/server/ConnectionMetricsTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/SessionUpgradeQuorumTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/test/ObserverMasterTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java",
)
TARGET_CLASSES = (
    "org/apache/zookeeper/server/SessionTrackerImpl.class",
    "org/apache/zookeeper/server/ZooKeeperServer.class",
    "org/apache/zookeeper/server/quorum/Follower.class",
    "org/apache/zookeeper/server/quorum/Leader.class",
    "org/apache/zookeeper/server/quorum/Learner.class",
    "org/apache/zookeeper/server/quorum/ObserverMaster.class",
    "org/apache/zookeeper/server/quorum/QuorumPeer.class",
    "org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.class",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def generate(base: Path, patched: Path) -> Path:
    if git(base, "rev-parse", "HEAD") != git(patched, "rev-parse", "HEAD"):
        raise RuntimeError("Pristine and patched ZooKeeper commits differ")
    if not (patched / HELPER).is_file():
        raise RuntimeError("Install ZooKeeper hooks before making a receipt")
    tracked = git(patched, "diff", "--binary", "--")
    helper = subprocess.run(
        ["git", "diff", "--no-index", "--binary", "--", "/dev/null", str(HELPER)],
        cwd=patched, check=False, capture_output=True,
    )
    if helper.returncode != 1 or not helper.stdout:
        raise RuntimeError(f"Cannot render new helper patch: {helper.stderr.decode()}")
    patch = HERE / "zookeeper-3.8.7-mallory.patch"
    patch.write_bytes(tracked + helper.stdout)
    checked = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch)],
        cwd=patched, check=False, capture_output=True,
    )
    if checked.returncode:
        raise RuntimeError(f"Overlay patch does not reverse cleanly: {checked.stderr.decode()}")

    modified = [Path(p) for p in git(patched, "diff", "--name-only").decode().splitlines()]
    modified.append(HELPER)
    modified_files = {str(p): digest(patched / p) for p in sorted(modified)}
    compiled_artifacts = []
    compiled_seen = set()
    for source in modified:
        if source.suffix != ".java":
            continue
        binary = Path("zookeeper-server/target/classes") / source.relative_to(
            "zookeeper-server/src/main/java"
        ).with_suffix(".class")
        artifact = patched / binary
        if not artifact.is_file() or artifact.stat().st_mtime < (patched / source).stat().st_mtime:
            raise RuntimeError(f"Compile the overlay before issuing a receipt: {binary}")
        compiled_artifacts.append({"path": str(artifact), "sha256": digest(artifact)})
        compiled_seen.add(artifact)

    for binary_name in TARGET_CLASSES:
        artifact = patched / "zookeeper-server/target/classes" / binary_name
        if not artifact.is_file():
            raise RuntimeError(f"Missing compiled target class: {artifact}")
        if artifact not in compiled_seen:
            compiled_artifacts.append({"path": str(artifact), "sha256": digest(artifact)})
            compiled_seen.add(artifact)

    tests = {path: digest(patched / path) for path in TEST_SOURCES}
    for source_name in TEST_SOURCES:
        binary = Path("zookeeper-server/target/test-classes") / Path(source_name).relative_to(
            "zookeeper-server/src/test/java"
        ).with_suffix(".class")
        artifact = patched / binary
        if not artifact.is_file() or artifact.stat().st_mtime < (patched / source_name).stat().st_mtime:
            raise RuntimeError(f"Test-compile the overlay before issuing a receipt: {binary}")
        compiled_artifacts.append({"path": str(artifact), "sha256": digest(artifact)})
    receipt = {
        "schema_version": 1,
        "system": "zookeeper",
        "version": "3.8.7",
        "base_commit": git(base, "rev-parse", "HEAD").decode().strip(),
        "base_root": str(base),
        "patched_root": str(patched),
        "patch_file": str(patch),
        "patch_sha256": digest(patch),
        "modified_files": modified_files,
        "test_sources": tests,
        "compiled_artifacts": compiled_artifacts,
        "surefire_agent_property": "mallory.agent.arg",
        "generic_test_command": [
            "mvn", "-pl", "zookeeper-server", "-am", "-Dtest={JUnitClass}#{method}",
            "-Dsurefire.failIfNoSpecifiedTests=false",
            "-Dmallory.agent.arg=-javaagent:{agent_jar}=config={agent_properties}", "test",
        ],
        "hooks": [
            "logical QuorumPeer/SessionTrackerImpl node identity",
            "RequestThrottler and PrepRequestProcessor task handoffs",
            "quorum Jute packet send/receive correlation and IOException doors",
        ],
    }
    destination = HERE / "zookeeper-3.8.7-overlay.json"
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_root", type=Path)
    parser.add_argument("patched_root", type=Path)
    args = parser.parse_args()
    print(generate(args.base_root.resolve(), args.patched_root.resolve()))
