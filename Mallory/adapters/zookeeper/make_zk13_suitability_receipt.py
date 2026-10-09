#!/usr/bin/env python3
"""Preserve source-backed ZK13 workload observations without asserting a bug."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


TARGET_SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"
CONNECT_SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java"
TEST_SOURCE = "zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java"
TARGET_CLASS = "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.class"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, why: str) -> None:
    if not value:
        raise RuntimeError(why)


def one_line(lines: list[str], needle: str, after: int = 0, before: int = 0) -> int:
    found = [i for i, line in enumerate(lines, 1)
             if i > after and (not before or i < before) and needle in line]
    require(len(found) == 1, f"ambiguous source anchor {needle!r}: {found}")
    return found[0]


def anchors(source: Path) -> dict:
    target = (source / TARGET_SOURCE).read_text(encoding="utf-8").splitlines()
    connect = (source / CONNECT_SOURCE).read_text(encoding="utf-8").splitlines()
    test = (source / TEST_SOURCE).read_text(encoding="utf-8").splitlines()
    method = one_line(target, "protected void validateSession(ServerCnxn cnxn, long sessionId)")
    guard = one_line(target, "isGlobalSession(sessionId)", method)
    throw = one_line(target, "throw new ServerCnxn.CloseRequestException(msg,", guard)
    connect_method = one_line(connect, "void processConnectRequest(ServerCnxn cnxn, ByteBuffer incomingBuffer)")
    next_method = one_line(connect, "protected void validateSession(ServerCnxn cnxn, long sessionId)", connect_method)
    disable_recv = one_line(connect, "cnxn.disableRecv()", connect_method, next_method)
    zero = one_line(connect, "if (sessionId == 0)", disable_recv, next_method)
    create = one_line(connect, "long id = createSession(cnxn, passwd, sessionTimeout)", zero, next_method)
    validate = one_line(connect, "validateSession(cnxn, sessionId)", create, next_method)
    original = one_line(test, "public void testGlobalSessionInRO()")
    original_shutdown = one_line(test, "qu.shutdown(2)", original, original + 40)
    expected = one_line(test, "Should not be able to renew a global session", original_shutdown, original + 40)
    alternative_a = one_line(test, "public void testConnectionEvents()")
    a_shutdown = one_line(test, "qu.shutdown(2)", alternative_a, alternative_a + 45)
    a_new = one_line(test, "zk = new ZooKeeper(qu.getConnString()", a_shutdown, alternative_a + 45)
    alternative_b = one_line(test, "public void testReadOnlyClient()")
    b_shutdown = one_line(test, "qu.shutdown(2)", alternative_b, alternative_b + 50)
    b_close = one_line(test, "zk.close()", b_shutdown, b_shutdown + 5)
    b_new = one_line(test, "zk = new ZooKeeper(qu.getConnString()", b_close, b_close + 10)
    return {
        "target": {"path": TARGET_SOURCE, "method_line": method,
                   "guard_line": guard, "throw_line": throw},
        "connect_dispatch": {"path": CONNECT_SOURCE, "method_line": connect_method,
                             "disable_recv_line": disable_recv,
                             "zero_session_line": zero,
                             "create_session_line": create,
                             "nonzero_validate_line": validate},
        "original": {"path": TEST_SOURCE, "method_line": original,
                     "quorum_shutdown_line": original_shutdown,
                     "expected_refusal_line": expected},
        "connection_events": {"path": TEST_SOURCE, "method_line": alternative_a,
                              "quorum_shutdown_line": a_shutdown,
                              "new_client_line": a_new},
        "readonly_client": {"path": TEST_SOURCE, "method_line": alternative_b,
                            "quorum_shutdown_line": b_shutdown,
                            "close_old_client_line": b_close,
                            "new_client_line": b_new},
    }


def make(source: Path, receipt_path: Path, agent: Path,
         original: Path, connection_events: Path, readonly_client: Path,
         output: Path) -> dict:
    paths = {"original": original, "connection_events": connection_events,
             "readonly_client": readonly_client}
    attestations = {key: json.loads((directory / "workload-attestation.json").read_text())
                    for key, directory in paths.items()}
    selectors = {"original": "ReadOnlyModeTest#testGlobalSessionInRO",
                 "connection_events": "ReadOnlyModeTest#testConnectionEvents",
                 "readonly_client": "ReadOnlyModeTest#testReadOnlyClient"}
    for key, row in attestations.items():
        require(row["case_id"] == "ZOOKEEPER-13" and row["selector"] == selectors[key],
                f"incorrect selector for {key}")
        require(row["target_source_sha256"] == sha(source / TARGET_SOURCE) and
                row["test_source_sha256"] == sha(source / TEST_SOURCE) and
                row["overlay_receipt_sha256"] == sha(receipt_path) and
                row["agent_jar_sha256"] == sha(agent),
                f"source or agent hash changed for {key}")
    require(attestations["original"]["status"] == "original_expected_target_throw_observed",
            "original expected refusal was not observed")
    alternate_statuses = {key: attestations[key]["status"]
                          for key in ("connection_events", "readonly_client")}
    if any(value == "alternate_healthy_guard_reached" for value in alternate_statuses.values()):
        status = "alternate_healthy_target_reached"
    elif all(value in ("alternate_target_missed", "alternate_target_class_not_loaded")
             for value in alternate_statuses.values()):
        status = "tested_selectors_unsuitable"
    else:
        status = "alternate_workload_unresolved"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "source-class-agent.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for relative in (TARGET_SOURCE, CONNECT_SOURCE, TEST_SOURCE, TARGET_CLASS):
            tar.add(source / relative, arcname=relative)
        tar.add(receipt_path, arcname="source-overlay-receipt.json")
        tar.add(Path(json.loads(receipt_path.read_text())["patch_file"]),
                arcname="source-overlay.patch")
        tar.add(agent, arcname="mallory-agent.jar")
    evidence = {}
    for key, directory in paths.items():
        files = sorted(path for path in directory.iterdir() if path.is_file())
        evidence[key] = {path.name: sha(path) for path in files}
    row = {
        "schema_version": 1, "case_id": "ZOOKEEPER-13", "status": status,
        "scope": "Three actual 3-peer cluster JUnit workloads; no fault campaign or bug claim.",
        "source_anchors": anchors(source),
        "source_sha256": {relative: sha(source / relative) for relative in
                          (TARGET_SOURCE, CONNECT_SOURCE, TEST_SOURCE, TARGET_CLASS)},
        "source_archive_sha256": sha(archive),
        "overlay_receipt_sha256": sha(receipt_path), "agent_jar_sha256": sha(agent),
        "workloads": {key: {"selector": selectors[key],
                            "status": attestations[key]["status"],
                            "target_check_count": attestations[key]["target_check_count"],
                            "target_throw_count": attestations[key]["target_throw_count"],
                            "duration_seconds": attestations[key]["duration_seconds"],
                            "evidence_sha256": evidence[key]}
                      for key in paths},
        "interpretation": ("The original selector intentionally exercises the selected refusal. "
                           "The tested alternatives do not establish a nonthrowing target visit; "
                           "this does not rule out another cluster workload."
                           if status == "tested_selectors_unsuitable" else
                           "Review the observed alternate target path before deciding workload suitability."),
    }
    (output / "workload-suitability-receipt.json").write_text(
        json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("agent", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("connection_events", type=Path)
    parser.add_argument("readonly_client", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = make(*(path.resolve() for path in (
        args.source, args.receipt, args.agent, args.original,
        args.connection_events, args.readonly_client, args.output)))
    print(json.dumps({"status": result["status"], "case_id": result["case_id"]}))
