#!/usr/bin/env python3
"""Verify an epoch-fixed ZooKeeper seed has a client-I/O/task path to T."""

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from Mallory.core.events import event_address, load_trace
from Mallory.core.graph import OccurrenceGraph


CLASS = "org.apache.zookeeper.server.SessionTrackerImpl"
TARGETS = {
    "ZOOKEEPER-02": ("checkSession", (4,)),
    "ZOOKEEPER-03": ("setOwner", (1, 2)),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def observed_path(graph: OccurrenceGraph, start: str, goal: str,
                  needed: set[str], request_rpc=None) -> list:
    successors = defaultdict(list)
    for edge in graph.edges:
        successors[edge.source].append(edge)
    pending = deque([(start, ())])
    visited = {(start, frozenset(), False)}
    while pending:
        node, path = pending.popleft()
        kinds = {edge.kind for edge in path}
        matched = bool(request_rpc(path)) if request_rpc else False
        if node == goal and needed.issubset(kinds) and (not request_rpc or matched):
            return list(path)
        for edge in successors[node]:
            next_path = (*path, edge)
            next_matched = bool(request_rpc(next_path)) if request_rpc else False
            state = (edge.target, frozenset(kinds | {edge.kind}), next_matched)
            if state not in visited:
                visited.add(state)
                pending.append((edge.target, next_path))
    return []


def attest(case: str, evidence: Path, source: Path, receipt_path: Path,
           agent: Path) -> dict:
    require(case in TARGETS, "This path proof covers ZOOKEEPER-02/03")
    command = json.loads((evidence / "command.json").read_text(encoding="utf-8"))
    result = json.loads((evidence / "exit.json").read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(command["cwd"] == receipt["patched_root"] == str(source), "source root mismatch")
    require(command["candidate_selector"] == "QuorumTest#testMultiToFollower", "workload drift")
    require(any(f"-javaagent:{agent}=config=" in part for part in command["argv"]),
            "healthy command did not use the attested agent jar")
    require(sha(Path(receipt["patch_file"])) == receipt["patch_sha256"],
            "overlay patch differs from receipt")
    require(result["exit_code"] == 0, "JUnit command failed")
    suffix = command.get("report_suffix")
    require(isinstance(suffix, str) and suffix, "strict unique JUnit report suffix missing")
    report_dir = source / "zookeeper-server/target/surefire-reports"
    reports = list(report_dir.glob(f"*TEST-org.apache.zookeeper.test.QuorumTest-{suffix}.xml"))
    require(len(reports) == 1, "selected JUnit has no unique fresh XML report")
    report = reports[0]
    require(report.stat().st_mtime >= result["started_at"] - 2,
            "JUnit XML predates this healthy run")
    xml = ET.parse(report).getroot()
    require(all(int(xml.get(key, "-1")) == expected for key, expected in
                (("tests", 1), ("errors", 0), ("failures", 0), ("skipped", 0))),
            "selected JUnit did not run and pass exactly once")
    properties = {row.get("name"): row.get("value") for row in xml.findall("./properties/property")}
    require(properties.get("test.junit.threads") == "8" and
            properties.get("zookeeper.junit.threadid") == "8" and
            properties.get("build.test.dir") == command.get("test_data_dir"),
            "ZooKeeper port or test data partition was not applied in the JVM")
    logs = list(report_dir.glob(f"*org.apache.zookeeper.test.QuorumTest-{suffix}-output.txt"))
    require(len(logs) == 1, "selected JUnit has no unique fresh output log")
    test_log = logs[0]
    output = test_log.read_text(encoding="utf-8")
    require("Test process 8/8 using ports from 30072 - 32764" in output,
            "PortAssignment did not use lane2 range")
    ports = [int(x) for x in re.findall(r"Assigned port (\d+) from range 30072 - 32764", output)]
    require(bool(ports) and all(30072 <= port <= 32764 for port in ports),
            "No attested quorum ports in the lane2 range")

    trace = load_trace(evidence / "events.jsonl")
    require(not trace.incomplete_last_line, "incomplete event trace")
    events = trace.events
    locations = command["target_locations"][case]
    method, branches = TARGETS[case]
    check_sites = [f"{CLASS}#{method}(JLjava/lang/Object;)V@{locations['target_guard_line']}:branch:{branch}"
                   for branch in branches]
    throw = f"{CLASS}#{method}(JLjava/lang/Object;)V@{locations['target_throw_line']}:throw:1"
    checks = [row for row in events if row.get("type") == "TARGET_CHECK" and row.get("site") in check_sites]
    throws = [row for row in events if row.get("type") == "TARGET_THROW" and row.get("site") == throw]
    require(all(any(row.get("site") == site for row in checks) for site in check_sites) and not throws,
            "healthy target branch absent or target exception expected")
    require(all(row.get("node") == "zk2" and row.get("region") and
                isinstance(row.get("epoch"), int) for row in checks),
            "target actor/region missing")
    all_enters = [row for row in events if row.get("type") == "REGION_ENTER"
                  and row.get("site") == checks[0]["region"]]
    require(all(any(event_address(enter) == event_address(check)
                    for enter in all_enters) for check in checks),
            "REGION_ENTER and TARGET_CHECK disagree on logical actor/epoch")
    first_target = min(row["seq"] for row in checks)
    before = tuple(row for row in events if row.get("seq", 0) <= first_target)
    graph = OccurrenceGraph(before)
    request_path_overlay = "request_path" in receipt
    needed_edges = {"task", "region_parent", "rpc"} if request_path_overlay else {
        "task", "region_parent"}
    target_addresses = {event_address(row) for row in checks if row["seq"] == first_target}
    enters = [row for row in before if row.get("type") == "REGION_ENTER"
              and event_address(row) in target_addresses]
    require(len(enters) == len(target_addresses), "target REGION_ENTER identity mismatch")
    require(all(any(edge.target == event_address(row) and edge.kind == "region_parent"
                    for edge in graph.edges) for row in enters),
            "a target region has no unique observed parent handoff")
    client_door = ("zookeeper.client.connect.read" if case == "ZOOKEEPER-03" and
                   "connect_path" in receipt else "zookeeper.client.request.read")
    context_prefix = "zk-connect:" if client_door.endswith("connect.read") else "zk-client:"
    client_reads = [row for row in before if row.get("type") == "RECV"
                    and row.get("site") == client_door
                    and row.get("correlation")]
    doors = [row for row in before if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == client_door
             and row.get("seq", 0) < first_target and event_address(row)
             and str(row.get("context", "")).startswith(context_prefix)
             and any(event_address(recv) == event_address(row)
                     and recv["seq"] < row["seq"] for recv in client_reads)]
    by_id = {row.get("id"): row for row in before if row.get("id")}
    target_actors = {(row["node"], row["epoch"]) for row in checks}

    def exact_request_rpc(path: list) -> tuple | None:
        for index, edge in enumerate(path[:-1]):
            if edge.kind != "rpc":
                continue
            sender, receiver = by_id.get(edge.producer_event), by_id.get(edge.consumer_event)
            parent = path[index + 1]
            if (sender and receiver and parent.kind == "region_parent" and
                    parent.producer_event == edge.consumer_event and
                    parent.source == edge.target and
                    sender.get("type") == "SEND" and receiver.get("type") == "RECV" and
                    sender.get("node") != receiver.get("node") and
                    (receiver.get("node"), receiver.get("epoch")) in target_actors and
                    sender.get("correlation") == receiver.get("correlation") and
                    re.fullmatch(r"REQUEST:[0-9a-f]{64}", str(sender.get("port", ""))) and
                    sender.get("port") == receiver.get("port")):
                return sender, receiver, parent
        return None

    paths = [(door, target, observed_path(
        graph, event_address(door), target, needed_edges,
        exact_request_rpc if request_path_overlay else None))
        for door in doors for target in target_addresses]
    witnesses = [(door, target, path, exact_request_rpc(path))
                 for door, target, path in paths if path]
    require(witnesses, "no observed client I/O + exact request RPC + task path to the target"
            if request_path_overlay else
            "no observed client I/O + task + parent path to the target")

    class_file = source / "zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class"
    class_sha = sha(class_file)
    require(any(row.get("path") == str(class_file) and row.get("sha256") == class_sha
                for row in receipt["compiled_artifacts"]), "compiled target absent from overlay receipt")
    catalog = [json.loads(line) for line in (evidence / "catalog.jsonl").read_text().splitlines() if line]
    selected = [row for row in catalog if row.get("class_name") == CLASS]
    require({row.get("bytecode_sha256") for row in selected} == {class_sha} and
            len({row.get("class_loader_id") for row in selected}) == 1,
            "loaded target bytecode or class loader ambiguous")
    require(set(check_sites + [throw]).issubset({row.get("site") for row in selected}),
            "exact check/throw IDs missing in target class catalog")
    target_source = "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
    require(sha(source / target_source) == receipt["modified_files"][target_source],
            "target source differs from epoch-fix overlay receipt")
    test_source = "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"
    require(sha(source / test_source) == receipt["test_sources"][test_source],
            "selected JUnit source differs from overlay receipt")
    witness = witnesses[0]
    summary = {
        "schema_version": 1, "case_id": case, "status": "healthy_causal_path_proven",
        "scope": "Standalone healthy proof; not a completed fault campaign.",
        "selector": command["candidate_selector"], "duration_seconds": result["duration_seconds"],
        "exact_check_site": check_sites[0], "exact_check_sites": check_sites,
        "exact_throw_site": throw,
        "target_check_count": len(checks), "target_throw_count": len(throws),
        "target_nodes": sorted({row["node"] for row in checks}),
        "target_epochs": sorted({row["epoch"] for row in checks}),
        "graph": graph.summary(),
        "pretarget_in_closure_doors": sum(any(event_address(door) in graph.backward_closure(target)
                                              for target in target_addresses) for door in doors),
        "observed_witness": {
            "door_event_id": witness[0].get("id"), "door_site": witness[0]["site"],
            "target_address": witness[1],
            "edges": [{"kind": edge.kind, "source": edge.source, "target": edge.target,
                       "producer_event": edge.producer_event,
                       "consumer_event": edge.consumer_event} for edge in witness[2]],
        },
        "exact_quorum_request_rpc": (
            {"send_event_id": witness[3][0]["id"],
             "recv_event_id": witness[3][1]["id"],
             "correlation": witness[3][0]["correlation"],
             "request_port": witness[3][0]["port"],
             "source_actor": [witness[3][0]["node"], witness[3][0]["epoch"]],
             "destination_actor": [witness[3][1]["node"], witness[3][1]["epoch"]]}
            if witness[3] else None),
        "event_counts": dict(Counter(row["type"] for row in events)),
        "port_assignment": {"range": [30072, 32764], "allocated_min": min(ports),
                            "allocated_max": max(ports), "allocated_count": len(ports)},
        "loaded_target_class_sha256": class_sha,
        "loaded_target_class_loader_ids": sorted({row["class_loader_id"] for row in selected}),
        "overlay_receipt_sha256": sha(receipt_path), "agent_jar_sha256": sha(agent),
        "evidence_sha256": {name: sha(evidence / name) for name in
                            ("agent.properties", "catalog.jsonl", "command.json", "events.jsonl",
                             "exit.json", "maven.log", "sites.json")},
        "junit_report_sha256": sha(report), "junit_output_sha256": sha(test_log),
    }
    (evidence / "causal-path-attestation.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case")
    parser.add_argument("evidence", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("agent", type=Path)
    args = parser.parse_args()
    summary = attest(args.case, args.evidence.resolve(), args.source.resolve(),
                     args.receipt.resolve(), args.agent.resolve())
    print(json.dumps({key: summary[key] for key in
                      ("status", "target_check_count", "pretarget_in_closure_doors", "duration_seconds")}))
