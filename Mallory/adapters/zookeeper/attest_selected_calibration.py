#!/usr/bin/env python3
"""Audit a pinned, unmodified ZooKeeper cluster-test healthy seed."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from Mallory.core.events import event_address, load_trace
from Mallory.core.graph import OccurrenceGraph


CASES = {
    "ZOOKEEPER-04": {
        "method": "org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V",
        "class": "org.apache.zookeeper.server.ZooKeeperServer",
        "test_class": "org.apache.zookeeper.server.ConnectionMetricsTest",
        "selector": "ConnectionMetricsTest#testRevalidateCount",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/server/ConnectionMetricsTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/ZooKeeperServer.class",
        "guard_line": 1434, "throw_line": 1444, "branch": "branch:7",
    },
    "ZOOKEEPER-05": {
        "method": "org.apache.zookeeper.server.quorum.Follower#followLeader()V",
        "class": "org.apache.zookeeper.server.quorum.Follower",
        "test_class": "org.apache.zookeeper.test.QuorumRestartTest",
        "selector": "QuorumRestartTest#testRollingRestart",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/Follower.class",
        "guard_line": 99, "throw_line": 104, "branch": "branch:2",
    },
    "ZOOKEEPER-06": {
        "method": "org.apache.zookeeper.server.quorum.Leader#waitForEpochAck(JLorg/apache/zookeeper/server/quorum/StateSummary;)V",
        "class": "org.apache.zookeeper.server.quorum.Leader",
        "test_class": "org.apache.zookeeper.test.QuorumRestartTest",
        "selector": "QuorumRestartTest#testRollingRestart",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/Leader.class",
        "guard_line": 1475, "throw_line": 1479, "branch": "branch:3",
    },
    "ZOOKEEPER-07": {
        "method": "org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J",
        "class": "org.apache.zookeeper.server.quorum.Learner",
        "test_class": "org.apache.zookeeper.test.QuorumRestartTest",
        "selector": "QuorumRestartTest#testRollingRestart",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumRestartTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/Learner.class",
        "guard_line": 518, "throw_line": 528, "branch": "branch:3",
    },
    "ZOOKEEPER-11": {
        "method": "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V",
        "class": "org.apache.zookeeper.server.quorum.QuorumPeer",
        "test_class": "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest",
        "selector": "CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/QuorumPeer.class",
        "guard_line": 1169, "throw_line": 1175, "branch": "branch:2",
    },
    "ZOOKEEPER-12": {
        "method": "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V",
        "class": "org.apache.zookeeper.server.quorum.QuorumPeer",
        "test_class": "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest",
        "selector": "CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile",
        "target_source": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java",
        "test_source": "zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.java",
        "compiled_class": "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/QuorumPeer.class",
        "guard_line": 1193, "throw_line": 1197, "branch": "branch:3",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def audit(evidence: Path) -> dict:
    command = json.loads((evidence / "command.json").read_text(encoding="utf-8"))
    pins = json.loads((evidence / "pins.json").read_text(encoding="utf-8"))
    exit_info = json.loads((evidence / "exit.json").read_text(encoding="utf-8"))
    case = command["case_id"]
    spec = CASES[case]
    guard_line, throw_line, branch = spec["guard_line"], spec["throw_line"], spec["branch"]
    source = Path(command["cwd"])
    assert command["selector"] == spec["selector"]
    assert command["guard_line"] == guard_line and command["throw_line"] == throw_line
    assert exit_info["exit_code"] == 0, "Maven/JUnit failed"
    assert sha(source / spec["target_source"]) == pins["target_source_sha256"]
    assert sha(source / spec["test_source"]) == pins["test_source_sha256"]
    assert sha(source / spec["compiled_class"]) == pins["loaded_class_expected_sha256"]
    assert sha(Path(pins["source_overlay_receipt"])) == pins["source_overlay_receipt_sha256"]
    agent = Path("/users/ZhenyuLi/baseline/data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar")
    assert sha(agent) == pins["agent_sha256"]
    assert any(f"-javaagent:{agent}=config=" in arg for arg in command["argv"])

    report_dir = source / "zookeeper-server/target/surefire-reports"
    report = report_dir / f"TEST-{spec['test_class']}-{command['report_suffix']}.xml"
    output = report_dir / f"{spec['test_class']}-{command['report_suffix']}-output.txt"
    assert report.is_file() and output.is_file() and report.stat().st_mtime >= exit_info["started_at"] - 2
    xml = ET.parse(report).getroot()
    assert all(int(xml.get(key, "-1")) == expected for key, expected in
               (("tests", 1), ("errors", 0), ("failures", 0), ("skipped", 0)))
    props = {row.get("name"): row.get("value") for row in xml.findall("./properties/property")}
    assert props.get("test.junit.threads") == "8"
    assert props.get("zookeeper.junit.threadid") == "8"
    assert props.get("build.test.dir") == command["test_data_dir"]
    text = output.read_text(encoding="utf-8")
    assert "Test process 8/8 using ports from 30072 - 32764" in text
    ports = [int(value) for value in re.findall(r"Assigned port (\d+) from range 30072 - 32764", text)]
    assert ports and all(30072 <= value <= 32764 for value in ports)

    events = load_trace(evidence / "events.jsonl").events
    catalog = rows(evidence / "catalog.jsonl")
    loaded = [row for row in catalog if row.get("class_name") == spec["class"]]
    assert loaded and {row.get("bytecode_sha256") for row in loaded} == {pins["loaded_class_expected_sha256"]}
    assert len({row.get("class_loader_id") for row in loaded}) == 1
    guard = f"{spec['method']}@{guard_line}:{branch}"
    throw = f"{spec['method']}@{throw_line}:throw:1"
    assert guard in {row.get("site") for row in loaded} and throw in {row.get("site") for row in loaded}
    checks = [row for row in events if row.get("type") == "TARGET_CHECK" and row.get("site") == guard]
    throws = [row for row in events if row.get("type") == "TARGET_THROW" and row.get("site") == throw]
    assert checks and not throws, "healthy target was missed or threw"
    assert all(event_address(row) and row.get("node", "").startswith("zk") for row in checks)

    observed_path_doors: set[str] = set()
    observed_edges: set[tuple[str, str, str]] = set()
    closure_sizes = []
    for check in checks:
        prefix = tuple(row for row in events if row.get("seq", 0) <= check["seq"])
        graph = OccurrenceGraph(prefix)
        target_address = event_address(check)
        # Walk only directly observed edges. Older pinned core releases expose
        # backward_closure without an observed-only switch.
        closure = {target_address}
        pending = [target_address]
        while pending:
            child = pending.pop()
            for edge in graph.edges:
                if edge.target == child and edge.source not in closure:
                    closure.add(edge.source)
                    pending.append(edge.source)
        closure_sizes.append(len(closure))
        for row in prefix:
            if (row.get("type") == "DOOR_OBSERVED" and row.get("seq", 0) < check["seq"]
                    and event_address(row) in closure and event_address(row) != target_address):
                observed_path_doors.add(row["id"])
        for edge in graph.edges:
            if edge.source in closure and edge.target in closure:
                observed_edges.add((edge.source, edge.target, edge.kind))
    status = "healthy_closure_proven" if observed_path_doors else "healthy_target_only_no_observed_path_door"
    result = {
        "schema_version": 1, "case_id": case, "status": status,
        "scope": "Existing three-peer cluster JUnit; healthy calibration only, no fault campaign",
        "selector": command["selector"], "duration_seconds": exit_info["duration_seconds"],
        "target_guard_site": guard, "target_throw_site": throw,
        "target_check_count": len(checks), "target_throw_count": len(throws),
        "target_nodes": sorted({row["node"] for row in checks}),
        "target_outcomes": dict(Counter(row.get("outcome") for row in checks)),
        "max_observed_closure_size": max(closure_sizes),
        "observed_path_door_count": len(observed_path_doors),
        "observed_path_door_ids": sorted(observed_path_doors),
        "observed_edge_count": len(observed_edges),
        "junit_assigned_ports": ports,
        "pins": pins,
        "raw_sha256": {name: sha(evidence / name) for name in
                       ("command.json", "pins.json", "agent.properties", "sites.json",
                        "exit.json", "events.jsonl", "catalog.jsonl", "maven.log")},
        "report_sha256": {report.name: sha(report), output.name: sha(output)},
    }
    (evidence / "attestation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.evidence), indent=2))
