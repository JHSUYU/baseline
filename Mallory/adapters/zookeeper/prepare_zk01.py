#!/usr/bin/env python3
"""Prepare the exact ZOOKEEPER-01 healthy seed in an installed test tree."""

import argparse
import json
from pathlib import Path


TARGET = "org.apache.zookeeper.server.SessionTrackerImpl"
METHOD = "checkSession"
TEST = "SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLeader"


def unique_line(lines: list[str], fragment: str, after: int = 0, before: int = 0) -> int:
    matches = [i for i, line in enumerate(lines, 1)
               if i > after and (not before or i < before) and fragment in line]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {fragment!r} after {after}, found {matches}")
    return matches[0]


def prepare(source: Path, agent: Path, output: Path) -> None:
    java = source / "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
    lines = java.read_text(encoding="utf-8").splitlines()
    guard = unique_line(lines, "if (session.isClosing()) {")
    throw = unique_line(lines, "throw new KeeperException.SessionExpiredException();", guard, guard + 4)
    output.mkdir(parents=True, exist_ok=True)
    site = {"class": TARGET, "method": METHOD, "descriptor": "(JLjava/lang/Object;)V"}
    (output / "sites.json").write_text(json.dumps({
        "targets": [dict(site, line=guard), dict(site, line=throw)],
        "regions": [site],
        "nodeBindings": [dict(site, field="malloryServerId", prefix="zk")],
    }, indent=2) + "\n", encoding="utf-8")
    (output / "agent.properties").write_text(
        "run.id=ZOOKEEPER-01-healthy\n"
        f"events={output / 'events.jsonl'}\n"
        f"site.catalog={output / 'catalog.jsonl'}\n"
        f"site.file={output / 'sites.json'}\n"
        "include=org.apache.zookeeper.server.SessionTrackerImpl\n"
        "coverage.methods=true\ncoverage.branches=true\n"
        "auto.io.doors=false\nstate.fields=false\nstate.maps=true\n",
        encoding="utf-8",
    )
    command = [
        "mvn", "-pl", "zookeeper-server", "-am",
        f"-Dtest={TEST}", "-Dsurefire.failIfNoSpecifiedTests=false",
        f"-Dmallory.agent.arg=-javaagent:{agent}=config={output / 'agent.properties'}", "test",
    ]
    (output / "command.json").write_text(json.dumps({
        "cwd": str(source), "argv": command,
        "case_id": "ZOOKEEPER-01", "target_guard_line": guard,
        "target_throw_line": throw,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("agent", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.agent.resolve(), args.output.resolve())
