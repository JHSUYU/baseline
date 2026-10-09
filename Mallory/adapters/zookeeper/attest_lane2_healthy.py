#!/usr/bin/env python3
"""Audit and label one ZK02/ZK03 standalone three-peer healthy proof."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


TARGET = {
    "ZOOKEEPER-02": {
        "checks": ["org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@325:branch:4"],
        "throw": "org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@326:throw:1",
    },
    "ZOOKEEPER-03": {
        "checks": [
            "org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@333:branch:1",
            "org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@333:branch:2",
        ],
        "throw": "org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@334:throw:1",
    },
}
FILES = (
    "agent.properties", "catalog.jsonl", "command.json", "events.jsonl", "exit.json",
    "maven.log", "sites.json", "TEST-org.apache.zookeeper.test.QuorumTest.xml",
    "org.apache.zookeeper.test.QuorumTest-output.txt",
    "SessionTrackerImpl.ca545363.class", "source/SessionTrackerImpl.java",
    "source/QuorumTest.java", "source/pom.xml",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def attest(case: str, evidence: Path, receipt_path: Path, agent: Path) -> None:
    if case not in TARGET:
        raise ValueError(case)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    command = json.loads((evidence / "command.json").read_text(encoding="utf-8"))
    exit_receipt = json.loads((evidence / "exit.json").read_text(encoding="utf-8"))
    if command.get("candidate_selector") != "QuorumTest#testMultiToFollower" or exit_receipt["exit_code"] != 0:
        raise ValueError("Three-peer test did not complete successfully")
    if command.get("cwd") != receipt["patched_root"]:
        raise ValueError("Healthy test ran on another source root")
    xml = ET.parse(evidence / "TEST-org.apache.zookeeper.test.QuorumTest.xml").getroot()
    if any(int(xml.get(name, "-1")) != value for name, value in
           (("tests", 1), ("errors", 0), ("failures", 0), ("skipped", 0))):
        raise ValueError("Surefire report does not show one passing JUnit test")
    props = {item.get("name"): item.get("value") for item in xml.findall("./properties/property")}
    if props.get("test.junit.threads") != "8" or props.get("zookeeper.junit.threadid") != "8":
        raise ValueError("JVM did not use ZooKeeper PortAssignment partition 8/8")
    if props.get("build.test.dir") != command.get("test_data_dir"):
        raise ValueError("JVM did not use isolated test data")
    output = (evidence / "org.apache.zookeeper.test.QuorumTest-output.txt").read_text(encoding="utf-8")
    if "Test process 8/8 using ports from 30072 - 32764" not in output:
        raise ValueError("PortAssignment did not report lane2 range")
    ports = [int(match) for match in re.findall(r"Assigned port (\d+) from range 30072 - 32764", output)]
    if not ports or any(not 30072 <= port <= 32764 for port in ports):
        raise ValueError("Allocated peer port outside lane2 range")
    events = jsonl(evidence / "events.jsonl")
    catalog = jsonl(evidence / "catalog.jsonl")
    target = TARGET[case]
    checks = {site: [row for row in events if row.get("type") == "TARGET_CHECK" and row.get("site") == site]
              for site in target["checks"]}
    if any(not rows for rows in checks.values()):
        raise ValueError("Exact target check was not observed")
    if any(row.get("node") != "zk2" or not row.get("region") for rows in checks.values() for row in rows):
        raise ValueError("Target has no attested ZooKeeper actor/region")
    if any(row.get("type") == "TARGET_THROW" and row.get("site") == target["throw"] for row in events):
        raise ValueError("Healthy test reached the expected target exception")
    catalog_sites = {row.get("site") for row in catalog}
    if not set(target["checks"] + [target["throw"]]).issubset(catalog_sites):
        raise ValueError("Exact target check/throw not present in loaded site catalog")
    target_catalog = [row for row in catalog if row.get("class_name") ==
                      "org.apache.zookeeper.server.SessionTrackerImpl"]
    class_hash = sha(evidence / "SessionTrackerImpl.ca545363.class")
    if ({row.get("bytecode_sha256") for row in target_catalog} != {class_hash} or
            len({row.get("class_loader_id") for row in target_catalog}) != 1):
        raise ValueError("Loaded target class bytes or class loader are ambiguous")
    target_source = "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
    test_source = "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"
    if (sha(evidence / "source/SessionTrackerImpl.java") != receipt["modified_files"][target_source] or
            sha(evidence / "source/QuorumTest.java") != receipt["test_sources"][test_source] or
            sha(evidence / "source/pom.xml") != receipt["modified_files"]["zookeeper-server/pom.xml"]):
        raise ValueError("Archived source differs from lane2 overlay receipt")
    first_target = min(row["seq"] for rows in checks.values() for row in rows)
    before = [row for row in events if row.get("type") == "DOOR_OBSERVED" and row.get("seq", 0) < first_target]
    if not before or any("door_ordinal" not in row for row in before):
        raise ValueError("No ordinal-marked I/O fault door before target")
    counts = Counter(row.get("type") for row in events)
    summary = {
        "schema_version": 1,
        "case_id": case,
        "state": "standalone_healthy_proof_valid",
        "scope": "One shared 3-peer JUnit run; not a Mallory core fault campaign or completed fuzz result.",
        "selector": "org.apache.zookeeper.test.QuorumTest#testMultiToFollower",
        "junit_exit_code": 0,
        "duration_seconds": exit_receipt["duration_seconds"],
        "check_counts": {site: len(rows) for site, rows in checks.items()},
        "target_throw_count": 0,
        "target_nodes": ["zk2"],
        "target_regions_present": True,
        "observed_io_doors_before_first_target": len(before),
        "event_counts": dict(counts),
        "port_assignment": {"process": "8/8", "range": [30072, 32764],
                            "allocated_min": min(ports), "allocated_max": max(ports),
                            "allocated_count": len(ports)},
        "test_data_dir": command["test_data_dir"],
        "loaded_target_class_sha256": class_hash,
        "loaded_target_class_loader_ids": sorted({row["class_loader_id"] for row in target_catalog}),
        "overlay_receipt_sha256": sha(receipt_path),
        "agent_jar_sha256": sha(agent),
        "evidence_sha256": {name: sha(evidence / name) for name in FILES},
    }
    (evidence / "calibration.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(TARGET))
    parser.add_argument("evidence", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("agent", type=Path)
    args = parser.parse_args()
    attest(args.case, args.evidence.resolve(), args.receipt.resolve(), args.agent.resolve())
