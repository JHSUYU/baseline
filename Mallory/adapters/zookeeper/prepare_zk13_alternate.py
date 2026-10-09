#!/usr/bin/env python3
"""Prepare original and alternate ZOOKEEPER-13 read-only cluster tests."""

import argparse
import json
from pathlib import Path


TARGET = "org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer"
TESTS = ("ReadOnlyModeTest#testConnectionEvents",
         "ReadOnlyModeTest#testReadOnlyClient",
         "ReadOnlyModeTest#testGlobalSessionInRO")


def one_line(lines: list[str], fragment: str, after: int = 0, before: int = 0) -> int:
    matches = [n for n, line in enumerate(lines, 1)
               if n > after and (not before or n < before) and fragment in line]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {fragment!r}, found {matches}")
    return matches[0]


def prepare(source: Path, agent: Path, output: Path, test: str,
            test_data_dir: Path | None = None,
            report_suffix: str | None = None) -> None:
    if test not in TESTS:
        raise ValueError(f"Unsupported selector: {test}")
    java = source / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"
    lines = java.read_text(encoding="utf-8").splitlines()
    guard = one_line(lines, "if (((LearnerSessionTracker) sessionTracker).isGlobalSession(sessionId)) {")
    throw = one_line(lines, "throw new ServerCnxn.CloseRequestException(msg,", guard, guard + 5)
    output.mkdir(parents=True, exist_ok=True)
    site = {"class": TARGET, "method": "validateSession",
            "descriptor": "(Lorg/apache/zookeeper/server/ServerCnxn;J)V"}
    (output / "sites.json").write_text(json.dumps({
        "targets": [dict(site, line=guard), dict(site, line=throw)],
        "regions": [site],
        "nodeBindings": [dict(site, getter="getServerId", prefix="zk")],
    }, indent=2) + "\n", encoding="utf-8")
    (output / "agent.properties").write_text(
        f"run.id=ZOOKEEPER-13-{test.split('#')[1]}-healthy\n"
        f"events={output / 'events.jsonl'}\n"
        f"site.catalog={output / 'catalog.jsonl'}\n"
        f"site.file={output / 'sites.json'}\n"
        "include=org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer\n"
        "coverage.methods=true\ncoverage.branches=true\n"
        "auto.io.doors=false\nstate.fields=false\nstate.maps=false\n",
        encoding="utf-8",
    )
    command = ["mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={test}",
               "-Dsurefire.failIfNoSpecifiedTests=false",
               f"-Dmallory.agent.arg=-javaagent:{agent}=config={output / 'agent.properties'}"]
    if test_data_dir is not None:
        command.append(f"-Dmallory.test.dir={test_data_dir.resolve()}")
    if report_suffix is not None:
        if not report_suffix.replace("_", "").replace("-", "").isalnum():
            raise ValueError("report_suffix must contain only letters, digits, '_' or '-'")
        command.append(f"-Dsurefire.reportNameSuffix={report_suffix}")
    command.append("test")
    (output / "command.json").write_text(json.dumps({
        "cwd": str(source), "argv": command,
        "case_id": "ZOOKEEPER-13", "calibration_only": True,
        "target_guard_line": guard, "target_throw_line": throw,
        "candidate_selector": test,
        "timeout_seconds": 240,
        "test_data_dir": str(test_data_dir.resolve()) if test_data_dir is not None else None,
        "report_suffix": report_suffix,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("agent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--test", choices=TESTS, default=TESTS[0])
    parser.add_argument("--test-data-dir", type=Path)
    parser.add_argument("--report-suffix")
    args = parser.parse_args()
    prepare(args.source.resolve(), args.agent.resolve(), args.output.resolve(),
            args.test, args.test_data_dir, args.report_suffix)
