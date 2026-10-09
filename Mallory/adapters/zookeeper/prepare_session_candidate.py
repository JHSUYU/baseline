#!/usr/bin/env python3
"""Prepare healthy 3-peer calibration for ZOOKEEPER-02, -03, or both."""

import argparse
import json
from pathlib import Path


TEST = "QuorumTest#testMultiToFollower"
CLASS = "org.apache.zookeeper.server.SessionTrackerImpl"
DESCRIPTORS = {"ZOOKEEPER-02": ("checkSession", "(JLjava/lang/Object;)V"),
               "ZOOKEEPER-03": ("setOwner", "(JLjava/lang/Object;)V")}
ANCHORS = {
    "ZOOKEEPER-02": ("} else if (session.owner != owner) {",
                      "throw new KeeperException.SessionMovedException();"),
    "ZOOKEEPER-03": ("if (session == null || session.isClosing()) {",
                      "throw new KeeperException.SessionExpiredException();"),
}


def one_line(lines: list[str], fragment: str, after: int = 0, before: int = 0) -> int:
    matches = [n for n, line in enumerate(lines, 1)
               if n > after and (not before or n < before) and fragment in line]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {fragment!r}, found {matches}")
    return matches[0]


def prepare(case: str, source: Path, agent: Path, output: Path,
            test_data_dir: Path | None = None,
            report_suffix: str | None = None) -> None:
    cases = sorted(DESCRIPTORS) if case == "ZOOKEEPER-02+03" else [case]
    java = source / "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
    lines = java.read_text(encoding="utf-8").splitlines()
    output.mkdir(parents=True, exist_ok=True)
    targets, regions, bindings, locations = [], [], [], {}
    for selected in cases:
        method, descriptor = DESCRIPTORS[selected]
        guard_text, throw_text = ANCHORS[selected]
        guard = one_line(lines, guard_text)
        throw = one_line(lines, throw_text, guard, guard + 3)
        if throw != guard + 1:
            raise RuntimeError(f"Unexpected target layout: guard {guard}, throw {throw}")
        site = {"class": CLASS, "method": method, "descriptor": descriptor}
        targets.extend([dict(site, line=guard), dict(site, line=throw)])
        regions.append(site)
        bindings.append(dict(site, field="malloryServerId", prefix="zk"))
        locations[selected] = {"target_guard_line": guard, "target_throw_line": throw}
    (output / "sites.json").write_text(json.dumps({
        "targets": targets, "regions": regions, "nodeBindings": bindings,
    }, indent=2) + "\n", encoding="utf-8")
    (output / "agent.properties").write_text(
        f"run.id={case}-alternate-healthy\n"
        f"events={output / 'events.jsonl'}\n"
        f"site.catalog={output / 'catalog.jsonl'}\n"
        f"site.file={output / 'sites.json'}\n"
        "include=org.apache.zookeeper.server.SessionTrackerImpl\n"
        "coverage.methods=true\ncoverage.branches=true\n"
        "auto.io.doors=false\nstate.fields=true\nstate.maps=true\n",
        encoding="utf-8",
    )
    command = ["mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={TEST}",
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
        "cwd": str(source), "argv": command, "case_id": case,
        "target_locations": locations,
        "candidate_selector": TEST, "calibration_only": True,
        "timeout_seconds": 180,
        "test_data_dir": str(test_data_dir.resolve()) if test_data_dir is not None else None,
        "report_suffix": report_suffix,
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(DESCRIPTORS) + ["ZOOKEEPER-02+03"])
    parser.add_argument("source", type=Path)
    parser.add_argument("agent", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--test-data-dir", type=Path)
    parser.add_argument("--report-suffix")
    args = parser.parse_args()
    prepare(args.case, args.source.resolve(), args.agent.resolve(), args.output.resolve(),
            args.test_data_dir, args.report_suffix)
