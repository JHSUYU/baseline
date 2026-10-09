#!/usr/bin/env python3
"""Attest an exact ZK13 original or alternate healthy cluster workload."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from Mallory.core.events import event_address
from Mallory.core.graph import OccurrenceGraph


TARGET_CLASS = "org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer"
METHOD = f"{TARGET_CLASS}#validateSession(Lorg/apache/zookeeper/server/ServerCnxn;J)V"
TARGET_SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"
TEST_SOURCE = "zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java"
COMPILED_CLASS = "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.class"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def attest(evidence: Path, source: Path, receipt_path: Path, agent: Path) -> dict:
    command = json.loads((evidence / "command.json").read_text(encoding="utf-8"))
    result = json.loads((evidence / "exit.json").read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(command["case_id"] == "ZOOKEEPER-13" and
            command["cwd"] == receipt["patched_root"] == str(source),
            "case or source root changed")
    require(sha(Path(receipt["patch_file"])) == receipt["patch_sha256"],
            "source patch differs from receipt")
    require(any(f"-javaagent:{agent}=config=" in part for part in command["argv"]),
            "healthy command used a different agent")
    require(result["exit_code"] == 0, "selected JUnit did not pass")
    suffix = command.get("report_suffix")
    require(isinstance(suffix, str) and suffix, "unique Surefire report suffix missing")
    report_dir = source / "zookeeper-server/target/surefire-reports"
    report = report_dir / f"TEST-org.apache.zookeeper.test.ReadOnlyModeTest-{suffix}.xml"
    output = report_dir / f"org.apache.zookeeper.test.ReadOnlyModeTest-{suffix}-output.txt"
    require(report.is_file() and output.is_file() and
            report.stat().st_mtime >= result["started_at"] - 2,
            "fresh selected JUnit reports missing")
    xml = ET.parse(report).getroot()
    require(all(int(xml.get(key, "-1")) == expected for key, expected in
                (("tests", 1), ("errors", 0), ("failures", 0), ("skipped", 0))),
            "selected JUnit did not pass exactly once")
    props = {row.get("name"): row.get("value") for row in xml.findall("./properties/property")}
    require(props.get("test.junit.threads") == "8" and
            props.get("zookeeper.junit.threadid") == "8" and
            props.get("build.test.dir") == command.get("test_data_dir"),
            "JVM port or test-data partition differs")
    log = output.read_text(encoding="utf-8")
    require("Test process 8/8 using ports from 30072 - 32764" in log,
            "ZooKeeper PortAssignment did not use lane2 range")
    ports = [int(port) for port in re.findall(
        r"Assigned port (\d+) from range 30072 - 32764", log)]
    require(bool(ports) and all(30072 <= port <= 32764 for port in ports),
            "quorum ports were not attested within lane2 range")

    target_source = source / TARGET_SOURCE
    test_source = source / TEST_SOURCE
    class_file = source / COMPILED_CLASS
    require(sha(target_source) == receipt["modified_files"][TARGET_SOURCE] and
            sha(test_source) == receipt["test_sources"][TEST_SOURCE] and
            any(row.get("path") == str(class_file) and row.get("sha256") == sha(class_file)
                for row in receipt["compiled_artifacts"]),
            "target source, test source, or class differs from overlay receipt")
    events = load_jsonl(evidence / "events.jsonl")
    catalog = load_jsonl(evidence / "catalog.jsonl")
    guard_prefix = f"{METHOD}@{command['target_guard_line']}:branch:"
    throw = f"{METHOD}@{command['target_throw_line']}:throw:1"
    loaded = [row for row in catalog if row.get("class_name") == TARGET_CLASS]
    guard_sites = sorted({row.get("site") for row in loaded
                          if str(row.get("site", "")).startswith(guard_prefix)})
    if loaded:
        require({row.get("bytecode_sha256") for row in loaded} == {sha(class_file)} and
                len({row.get("class_loader_id") for row in loaded}) == 1 and
                bool(guard_sites) and throw in {row.get("site") for row in loaded},
                "target class catalog or loaded bytecode is ambiguous")
    checks = [row for row in events if row.get("type") == "TARGET_CHECK" and
              row.get("site") in guard_sites]
    throws = [row for row in events if row.get("type") == "TARGET_THROW" and
              row.get("site") == throw]
    require(all(row.get("node") and isinstance(row.get("epoch"), int)
                for row in checks + throws),
            "observed target lacks named node or lifecycle epoch")
    original = command["candidate_selector"] == "ReadOnlyModeTest#testGlobalSessionInRO"
    if original:
        require(loaded and checks and throws,
                "original workload did not exercise expected target refusal")
        require(all(row.get("outcome") == "FALLTHROUGH" for row in checks),
                "original target outcome differs from expected refusal arm")
        status = "original_expected_target_throw_observed"
    elif not loaded:
        status = "alternate_target_class_not_loaded"
    elif not checks:
        require(not throws, "alternate emitted target throw without a check")
        status = "alternate_target_missed"
    elif throws:
        status = "alternate_target_throw_observed"
    else:
        require(all(row.get("outcome") == "TAKEN" for row in checks),
                "alternate guard did not take the healthy nonthrowing arm")
        status = "alternate_healthy_guard_reached"

    observed_path_doors = []
    observed_edges = []
    if checks:
        target = min(checks, key=lambda row: row["seq"])
        prefix = tuple(row for row in events if row.get("seq", 0) <= target["seq"])
        graph = OccurrenceGraph(prefix)
        target_address = event_address(target)
        closure = {target_address}
        pending = [target_address]
        while pending:
            child = pending.pop()
            for edge in graph.edges:
                if edge.target == child and edge.source not in closure:
                    closure.add(edge.source)
                    pending.append(edge.source)
        by_id = {row["id"]: row for row in prefix if row.get("id")}
        for door in prefix:
            if (door.get("type") != "DOOR_OBSERVED" or
                    door.get("site") != "zookeeper.client.connect.read" or
                    event_address(door) not in closure or not door.get("node")):
                continue
            door_address = event_address(door)
            for edge in graph.edges:
                producer = by_id.get(edge.producer_event)
                if (edge.kind == "region_parent" and edge.source == door_address and
                        edge.target == target_address and producer and
                        producer.get("type") == "RECV" and
                        producer.get("site") == door.get("site") and
                        producer.get("correlation") == door.get("context") and
                        producer.get("seq", 0) < door.get("seq", 0)):
                    observed_path_doors.append(door)
                    observed_edges.append(edge)
        if status == "alternate_healthy_guard_reached":
            require(observed_path_doors and observed_edges,
                    "alternate target lacks an exact observed connect door path")

    summary = {
        "schema_version": 1, "case_id": "ZOOKEEPER-13", "status": status,
        "scope": "Standalone cluster JUnit workload observation; no fault campaign.",
        "selector": command["candidate_selector"], "duration_seconds": result["duration_seconds"],
        "target_guard_sites": guard_sites, "target_throw_site": throw,
        "target_check_count": len(checks), "target_throw_count": len(throws),
        "target_branch_counts": dict(sorted(Counter(row["site"] for row in checks).items())),
        "target_outcome_counts": dict(sorted(Counter(row.get("outcome") for row in checks).items())),
        "observed_path_door_count": len(observed_path_doors),
        "observed_path_door_ids": [row["id"] for row in observed_path_doors],
        "observed_path_edges": [dict(source=edge.source, target=edge.target,
                                     kind=edge.kind, producer_event=edge.producer_event,
                                     consumer_event=edge.consumer_event)
                                for edge in observed_edges],
        "target_nodes": sorted({row.get("node") for row in checks if row.get("node")}),
        "target_epochs": sorted({row.get("epoch") for row in checks
                                 if isinstance(row.get("epoch"), int)}),
        "target_class_loaded": bool(loaded),
        "loaded_target_class_sha256": sha(class_file) if loaded else None,
        "loaded_target_class_loader_ids": sorted({row["class_loader_id"] for row in loaded}),
        "target_source_sha256": sha(target_source), "test_source_sha256": sha(test_source),
        "overlay_receipt_sha256": sha(receipt_path), "agent_jar_sha256": sha(agent),
        "event_counts": dict(Counter(row.get("type") for row in events)),
        "port_assignment": {"range": [30072, 32764], "allocated_count": len(ports),
                            "allocated_min": min(ports), "allocated_max": max(ports)},
        "evidence_sha256": {name: sha(evidence / name) for name in
                            ("agent.properties", "catalog.jsonl", "command.json",
                             "events.jsonl", "exit.json", "maven.log", "sites.json")},
        "junit_report_sha256": sha(report), "junit_output_sha256": sha(output),
    }
    shutil.copy2(report, evidence / report.name)
    shutil.copy2(output, evidence / output.name)
    (evidence / "workload-attestation.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("agent", type=Path)
    args = parser.parse_args()
    row = attest(args.evidence.resolve(), args.source.resolve(),
                 args.receipt.resolve(), args.agent.resolve())
    print(json.dumps({key: row[key] for key in
                      ("status", "selector", "target_check_count", "target_throw_count",
                       "duration_seconds")}))
