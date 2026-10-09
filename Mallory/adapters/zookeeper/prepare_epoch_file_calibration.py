#!/usr/bin/env python3
"""Prepare one pinned, existing ZooKeeper epoch-file cluster test healthy run."""

import argparse
import hashlib
import json
from pathlib import Path


SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper-connectpath-lane2")
AGENT = Path("/users/ZhenyuLi/baseline/data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar")
RECEIPT = Path("/users/ZhenyuLi/baseline/Mallory/adapters/zookeeper/zookeeper-3.8.7-connectpath-lane2-overlay.json")
METHOD = "org.apache.zookeeper.server.quorum.QuorumPeer"
TEST = "CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile"
LINES = {"ZOOKEEPER-11": (1169, 1175), "ZOOKEEPER-12": (1193, 1197)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(case: str, output: Path) -> None:
    guard, throw = LINES[case]
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    target = SOURCE / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java"
    test = SOURCE / "zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest.java"
    compiled = SOURCE / "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/QuorumPeer.class"
    assert str(SOURCE) == receipt["patched_root"]
    assert digest(target) == receipt["modified_files"][str(target.relative_to(SOURCE))]
    assert digest(test) == receipt["test_sources"][str(test.relative_to(SOURCE))]
    assert any(row["path"] == str(compiled) and row["sha256"] == digest(compiled)
               for row in receipt["compiled_artifacts"])
    assert digest(AGENT) == "bf8e6dbae07027dce750f15e3385c763f4894c2856056e2320bd85a54ed100c5"
    output.mkdir(parents=True, exist_ok=False)
    sites = {
        "targets": [{"class": METHOD, "method": "loadDataBase", "descriptor": "()V", "line": line}
                    for line in (guard, throw)],
        "regions": [{"class": METHOD, "method": "loadDataBase", "descriptor": "()V"}],
        "doors": [],
        "nodeBindings": [{"class": METHOD, "method": "loadDataBase", "descriptor": "()V",
                          "field": "myid", "prefix": "zk"}],
    }
    (output / "sites.json").write_text(json.dumps(sites, indent=2) + "\n", encoding="utf-8")
    props = {
        "run.id": f"{case}-epoch-file-healthy-v1", "events": str(output / "events.jsonl"),
        "site.catalog": str(output / "catalog.jsonl"), "site.file": str(output / "sites.json"),
        "include": METHOD, "coverage.methods": "true", "coverage.branches": "true",
        "auto.io.doors": "true", "state.fields": "false", "state.maps": "false",
    }
    (output / "agent.properties").write_text(
        "".join(f"{key}={value}\n" for key, value in props.items()), encoding="utf-8")
    suffix = f"mallory_{case.lower().replace('-', '')}_epochfile_v1"
    command = {
        "case_id": case, "cwd": str(SOURCE), "timeout_seconds": 300,
        "selector": TEST, "guard_line": guard, "throw_line": throw,
        "report_suffix": suffix, "test_data_dir": str(output / "test-data"),
        "argv": ["mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={TEST}",
                 "-Dsurefire.failIfNoSpecifiedTests=false",
                 f"-Dmallory.agent.arg=-javaagent:{AGENT}=config={output / 'agent.properties'}",
                 f"-Dmallory.test.dir={output / 'test-data'}",
                 f"-Dsurefire.reportNameSuffix={suffix}", "test"],
    }
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    pins = {"case_id": case, "source_overlay_receipt": str(RECEIPT),
            "source_overlay_receipt_sha256": digest(RECEIPT),
            "target_source_sha256": digest(target), "test_source_sha256": digest(test),
            "loaded_class_expected_sha256": digest(compiled), "agent_sha256": digest(AGENT)}
    (output / "pins.json").write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(LINES))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.case_id, args.output)
