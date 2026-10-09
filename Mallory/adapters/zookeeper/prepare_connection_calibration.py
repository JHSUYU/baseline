#!/usr/bin/env python3
"""Prepare the existing ZK04 three-peer reconnect test as a healthy seed."""

import argparse
import hashlib
import json
from pathlib import Path


SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper-connectpath-lane2")
AGENT = Path("/users/ZhenyuLi/baseline/data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar")
RECEIPT = Path("/users/ZhenyuLi/baseline/Mallory/adapters/zookeeper/zookeeper-3.8.7-connectpath-lane2-overlay.json")
CLASS = "org.apache.zookeeper.server.ZooKeeperServer"
DESC = "(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V"
SELECTOR = "ConnectionMetricsTest#testRevalidateCount"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output: Path) -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    java = SOURCE / "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java"
    test = SOURCE / "zookeeper-server/src/test/java/org/apache/zookeeper/server/ConnectionMetricsTest.java"
    compiled = SOURCE / "zookeeper-server/target/classes/org/apache/zookeeper/server/ZooKeeperServer.class"
    assert str(SOURCE) == receipt["patched_root"]
    assert sha(java) == receipt["modified_files"][str(java.relative_to(SOURCE))]
    assert sha(test) == receipt["test_sources"][str(test.relative_to(SOURCE))]
    assert any(row["path"] == str(compiled) and row["sha256"] == sha(compiled)
               for row in receipt["compiled_artifacts"])
    assert sha(AGENT) == "bf8e6dbae07027dce750f15e3385c763f4894c2856056e2320bd85a54ed100c5"
    lines = java.read_text(encoding="utf-8").splitlines()
    guards = [n for n, text in enumerate(lines, 1)
              if "if (connReq.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid)" in text]
    throws = [n for n, text in enumerate(lines, 1)
              if "throw new CloseRequestException(msg, ServerCnxn.DisconnectReason.CLIENT_ZXID_AHEAD)" in text]
    assert len(guards) == len(throws) == 1 and 0 < throws[0] - guards[0] < 15
    guard, throw = guards[0], throws[0]
    output.mkdir(parents=True, exist_ok=False)
    site = {"class": CLASS, "method": "processConnectRequest", "descriptor": DESC}
    rules = {"targets": [dict(site, line=guard), dict(site, line=throw)],
             "regions": [site], "doors": [],
             "nodeBindings": [dict(site, getter="getServerId", prefix="zk")]}
    (output / "sites.json").write_text(json.dumps(rules, indent=2) + "\n", encoding="utf-8")
    props = {"run.id": "ZOOKEEPER-04-reconnect-healthy-v1", "events": str(output / "events.jsonl"),
             "site.catalog": str(output / "catalog.jsonl"), "site.file": str(output / "sites.json"),
             "include": CLASS, "coverage.methods": "true", "coverage.branches": "true",
             "auto.io.doors": "true", "state.fields": "false", "state.maps": "false"}
    (output / "agent.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in props.items()), encoding="utf-8")
    suffix = "mallory_zk04_reconnect_v1"
    command = {"case_id": "ZOOKEEPER-04", "cwd": str(SOURCE), "timeout_seconds": 300,
               "selector": SELECTOR, "guard_line": guard, "throw_line": throw,
               "report_suffix": suffix, "test_data_dir": str(output / "test-data"),
               "argv": ["mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={SELECTOR}",
                        "-Dsurefire.failIfNoSpecifiedTests=false",
                        f"-Dmallory.agent.arg=-javaagent:{AGENT}=config={output / 'agent.properties'}",
                        f"-Dmallory.test.dir={output / 'test-data'}",
                        f"-Dsurefire.reportNameSuffix={suffix}", "test"]}
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    pins = {"case_id": "ZOOKEEPER-04", "source_overlay_receipt": str(RECEIPT),
            "source_overlay_receipt_sha256": sha(RECEIPT),
            "target_source_sha256": sha(java), "test_source_sha256": sha(test),
            "loaded_class_expected_sha256": sha(compiled), "agent_sha256": sha(AGENT)}
    (output / "pins.json").write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.output)
