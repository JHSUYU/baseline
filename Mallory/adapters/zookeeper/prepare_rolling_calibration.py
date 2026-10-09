#!/usr/bin/env python3
"""Prepare one existing rolling-restart quorum JUnit as a pinned healthy seed."""

import argparse
import hashlib
import json
from pathlib import Path


SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper-connectpath-lane2")
AGENT = Path("/users/ZhenyuLi/baseline/data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar")
RECEIPT = Path("/users/ZhenyuLi/baseline/Mallory/adapters/zookeeper/zookeeper-3.8.7-connectpath-lane2-overlay.json")
SELECTOR = "QuorumRestartTest#testRollingRestart"
CASES = {
    "ZOOKEEPER-05": ("Follower", "followLeader", "()V",
                       "if (newEpoch < self.getAcceptedEpoch())", "throw new IOException(\"Error: Epoch of leader is lower\")"),
    "ZOOKEEPER-06": ("Leader", "waitForEpochAck",
                       "(JLorg/apache/zookeeper/server/quorum/StateSummary;)V",
                       "if (ss.isMoreRecentThan(leaderStateSummary))",
                       "throw new IOException(\"Follower is ahead of the leader"),
    "ZOOKEEPER-07": ("Learner", "registerWithLeader", "(I)J",
                       "else if (newEpoch == self.getAcceptedEpoch())",
                       "throw new IOException(\"Leaders epoch, "),
}
THROW_BYTECODE_LINE = {"ZOOKEEPER-05": 104, "ZOOKEEPER-06": 1479,
                       "ZOOKEEPER-07": 528}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_line(lines: list[str], fragment: str) -> int:
    hits = [n for n, line in enumerate(lines, 1) if fragment in line]
    assert len(hits) == 1, (fragment, hits)
    return hits[0]


def prepare(case: str, output: Path, *, source: Path = SOURCE,
            receipt_path: Path = RECEIPT, variant: str = "rolling_v1") -> None:
    name, method, descriptor, guard_fragment, throw_fragment = CASES[case]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    java = source / f"zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/{name}.java"
    test = source / "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java"
    compiled = source / f"zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/{name}.class"
    assert str(source) == receipt["patched_root"]
    assert sha(java) == receipt["modified_files"][str(java.relative_to(source))]
    assert sha(test) == receipt["test_sources"][str(test.relative_to(source))]
    assert any(row["path"] == str(compiled) and row["sha256"] == sha(compiled)
               for row in receipt["compiled_artifacts"])
    assert sha(AGENT) == "bf8e6dbae07027dce750f15e3385c763f4894c2856056e2320bd85a54ed100c5"
    lines = java.read_text(encoding="utf-8").splitlines()
    guard = unique_line(lines, guard_fragment)
    throw_source = unique_line(lines, throw_fragment)
    throw = THROW_BYTECODE_LINE[case]
    assert 0 < throw_source - guard < 15 and throw_source <= throw < throw_source + 5
    output.mkdir(parents=True, exist_ok=False)
    clazz = "org.apache.zookeeper.server.quorum." + name
    site = {"class": clazz, "method": method, "descriptor": descriptor}
    rules = {"targets": [dict(site, line=guard), dict(site, line=throw)],
             "regions": [site], "doors": [],
             "nodeBindings": [dict(site, getter="malloryServerId", prefix="zk")]}
    (output / "sites.json").write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
    props = {"run.id": f"{case}-{output.name}", "events": str(output / "events.jsonl"),
             "site.catalog": str(output / "catalog.jsonl"), "site.file": str(output / "sites.json"),
             "include": clazz, "coverage.methods": "true", "coverage.branches": "true",
             "auto.io.doors": "true", "state.fields": "false", "state.maps": "false"}
    (output / "agent.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in props.items()), encoding="utf-8")
    suffix = f"mallory_{case.lower().replace('-', '')}_{variant}"
    command = {"case_id": case, "cwd": str(source), "timeout_seconds": 420,
               "selector": SELECTOR, "guard_line": guard, "throw_line": throw,
               "report_suffix": suffix, "test_data_dir": str(output / "test-data"),
               "argv": ["mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={SELECTOR}",
                        "-Dsurefire.failIfNoSpecifiedTests=false",
                        f"-Dmallory.agent.arg=-javaagent:{AGENT}=config={output / 'agent.properties'}",
                        f"-Dmallory.test.dir={output / 'test-data'}",
                        f"-Dsurefire.reportNameSuffix={suffix}", "test"]}
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    pins = {"case_id": case, "source_overlay_receipt": str(receipt_path),
            "source_overlay_receipt_sha256": sha(receipt_path),
            "target_source_sha256": sha(java), "test_source_sha256": sha(test),
            "loaded_class_expected_sha256": sha(compiled), "agent_sha256": sha(AGENT)}
    (output / "pins.json").write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(CASES))
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-root", type=Path, default=SOURCE)
    parser.add_argument("--receipt", type=Path, default=RECEIPT)
    parser.add_argument("--variant", default="rolling_v1")
    args = parser.parse_args()
    prepare(args.case_id, args.output, source=args.source_root.resolve(),
            receipt_path=args.receipt.resolve(), variant=args.variant)
