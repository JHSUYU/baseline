#!/usr/bin/env python3
"""Resolve exact ASM target probes and generate candidate Mallory case configs.

The resolver reads production class bytes from the pinned distribution. It
never interprets a Soot/Jimple ordinal as an ASM branch ordinal. Unresolved
targets receive a mapping-gap record and are not dispatched.
"""

from __future__ import annotations

import hashlib
import difflib
import json
import math
import os
import re
import subprocess
import sys
import zipfile
from functools import lru_cache
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parents[1]
AGENT = BASELINE / "Mallory" / "instrumentation" / "target" / "mallory-agent.jar"
HBASE_RUNTIME = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/runtime")
HBASE_RECEIPT = BASELINE / "Mallory" / "adapters" / "hbase" / "overlay-receipt.json"
HBASE_LANE2_RECEIPT = BASELINE / "Mallory" / "adapters" / "hbase" / "lane2-receipt.json"
HBASE_RUNNER_SHA256 = "9b44bf693a8365dd01364cc1641208c0a481902116e316830260b3f71c8d4445"
HBASE01_SITES_SHA256 = "64c8def80af5a041df36638fb3c5d4fdfccbf1805bf34db7dd05ee9ea6a279ab"
BUILD = HERE / ".build"
CHECK_LINES = json.loads((BASELINE / "data" / "crashfuzz" / "check_locations.json").read_text())["check_start_lines"]
CALLTHROW = {row["case_id"]: row for row in json.loads(
    (HERE / "called_throw_gaps.json").read_text())["cases"]}
WORKLOAD_ORACLE_UNFIT = {"ZOOKEEPER-13"}
WORKLOAD_OVERLOAD_MISMATCH = {"HDFS-13"}
SOURCE_INFEASIBLE_HEALTHY_GUARD = {"SOLR-15", "SOLR-16", "SOLR-34"}
SOLR_AUDIT = {row["case_id"]: row for row in json.loads(
    (HERE / "solr_test_mapping_recommendations.json").read_text())["cases"]}
ISOLATED_ROOTS = {
    "hdfs": Path("/users/ZhenyuLi/.mallory-worktrees/hdfs"),
    "zookeeper": Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper"),
}
ZK_EXCEPTIONS = {
    "ZOOKEEPER-01": "org.apache.zookeeper.KeeperException$SessionExpiredException",
    "ZOOKEEPER-02": "org.apache.zookeeper.KeeperException$SessionMovedException",
    "ZOOKEEPER-03": "org.apache.zookeeper.KeeperException$SessionExpiredException",
    "ZOOKEEPER-04": "org.apache.zookeeper.server.ServerCnxn$CloseRequestException",
    "ZOOKEEPER-05": "java.io.IOException",
    "ZOOKEEPER-06": "java.io.IOException",
    "ZOOKEEPER-07": "java.io.IOException",
    "ZOOKEEPER-08": "org.apache.zookeeper.KeeperException$SessionExpiredException",
    "ZOOKEEPER-09": "org.apache.zookeeper.KeeperException$SessionExpiredException",
    "ZOOKEEPER-10": "java.lang.RuntimeException",
    "ZOOKEEPER-11": "java.io.IOException",
    "ZOOKEEPER-12": "java.io.IOException",
    "ZOOKEEPER-13": "org.apache.zookeeper.server.ServerCnxn$CloseRequestException",
}
GUARD_LINE_OVERRIDES = {
    # The legacy selection chose the throw line for these else/long-message
    # checks. These are source-inspected guard lines in the same method.
    "ZOOKEEPER-04": 1431,
    # SessionMovedException belongs to the nested changed-owner branch.
    "ZOOKEEPER-02": 322,
    "ZOOKEEPER-07": 515,
    # Exhausting the loop over live nodes leads to this later throw.
    "SOLR-01": 243,
    # SOLR-16 is the changed-owner inner check (B41), after the null check B40.
    "SOLR-16": 539,
}


def write_json(path: Path, value: dict) -> None:
    serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text() == serialized:
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(serialized)
    os.replace(temporary, path)
# Bindings are source/trace reviewed, not inferred from a class name. A
# missing binding leaves the healthy seed's logical node identity unverified.
NODE_BINDINGS = {
    "ZOOKEEPER-01": [{"class": "org.apache.zookeeper.server.SessionTrackerImpl",
                        "method": "checkSession", "descriptor": "(JLjava/lang/Object;)V",
                        "field": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-02": [{"class": "org.apache.zookeeper.server.SessionTrackerImpl",
                        "method": "checkSession", "descriptor": "(JLjava/lang/Object;)V",
                        "field": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-03": [{"class": "org.apache.zookeeper.server.SessionTrackerImpl",
                        "method": "setOwner", "descriptor": "(JLjava/lang/Object;)V",
                        "field": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-04": [{"class": "org.apache.zookeeper.server.ZooKeeperServer",
                        "method": "processConnectRequest", "getter": "getServerId", "prefix": "zk"}],
    "ZOOKEEPER-05": [{"class": "org.apache.zookeeper.server.quorum.Follower",
                        "method": "followLeader", "descriptor": "()V",
                        "getter": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-06": [{"class": "org.apache.zookeeper.server.quorum.Leader",
                        "method": "waitForEpochAck", "getter": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-07": [{"class": "org.apache.zookeeper.server.quorum.Learner",
                        "method": "registerWithLeader", "descriptor": "(I)J",
                        "getter": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-10": [{"class": "org.apache.zookeeper.server.quorum.ObserverMaster",
                        "method": "removeProposedPacket", "descriptor": "(J)Lorg/apache/zookeeper/server/quorum/QuorumPacket;",
                        "getter": "malloryServerId", "prefix": "zk"}],
    "ZOOKEEPER-11": [{"class": "org.apache.zookeeper.server.quorum.QuorumPeer",
                        "method": "loadDataBase", "descriptor": "()V",
                        "field": "myid", "prefix": "zk"}],
    "ZOOKEEPER-12": [{"class": "org.apache.zookeeper.server.quorum.QuorumPeer",
                        "method": "loadDataBase", "descriptor": "()V",
                        "field": "myid", "prefix": "zk"}],
    "ZOOKEEPER-13": [{"class": "org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer",
                        "method": "validateSession", "getter": "getServerId", "prefix": "zk"}],
}
VERIFIED_HEALTHY_PROBES = {
    "HDFS-43": {
        "source_commit": "9d50c6884666e794e45102260a4017bb31802e1b",
        "target_source_sha256": "63873afaae1325f55ba86598dd91fd889d9204800fd4d0e90c4a168bcd91af3d",
        "class_sha256": "12ebb7eacd1f792058aa62fbdb36d5ef85374a624ad4c63591577932518fc006",
        "test_class_sha256": "f7148c7f1c77b002753655c1f3257b73e8721f5b484c4e37cfb91c8ddf24309f",
        "check_sites": ["org.apache.hadoop.hdfs.server.namenode.FSDirTruncateOp#truncate(Lorg/apache/hadoop/hdfs/server/namenode/FSNamesystem;Ljava/lang/String;JLjava/lang/String;Ljava/lang/String;JLorg/apache/hadoop/hdfs/server/namenode/INode$BlocksMapUpdateInfo;Lorg/apache/hadoop/hdfs/server/namenode/FSPermissionChecker;)Lorg/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp$TruncateResult;@113:branch:10"],
        "throw_site": "org.apache.hadoop.hdfs.server.namenode.FSDirTruncateOp#truncate(Lorg/apache/hadoop/hdfs/server/namenode/FSNamesystem;Ljava/lang/String;JLjava/lang/String;Ljava/lang/String;JLorg/apache/hadoop/hdfs/server/namenode/INode$BlocksMapUpdateInfo;Lorg/apache/hadoop/hdfs/server/namenode/FSPermissionChecker;)Lorg/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp$TruncateResult;@117:throw:1",
        "evidence": "data/mallory/calibration_v2/HDFS-43/result.json",
        "evidence_sha256": "46c06be8b71e04da05d74cf8b3f350e4c6cb75f259bc5bdbd9923151d7f2aae4",
        "scope": "independent_healthy_calibration_only",
    },
    "HDFS-49": {
        "source_commit": "9d50c6884666e794e45102260a4017bb31802e1b",
        "target_source_sha256": "3391aca71a4b7350da952e9bae0a7d6d8e8568f6de1f419f8dce331e98fa60b7",
        "class_sha256": "33930de8f98942d102579e04f07f4fb4ddeaf5f3b98f1a53f1c8471c0bc105c3",
        "test_class_sha256": "9603b7f2ec9fff5e89772fdab727bb8246e4e4c4b573d024353a968a7fe63a3e",
        "check_sites": ["org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature#addSnapshot(Lorg/apache/hadoop/hdfs/server/namenode/INodeDirectory;Lorg/apache/hadoop/hdfs/server/namenode/snapshot/SnapshotManager;Ljava/lang/String;Lorg/apache/hadoop/hdfs/server/namenode/LeaseManager;J)Lorg/apache/hadoop/hdfs/server/namenode/snapshot/Snapshot;@188:branch:1"],
        "throw_site": "org.apache.hadoop.hdfs.server.namenode.snapshot.DirectorySnapshottableFeature#addSnapshot(Lorg/apache/hadoop/hdfs/server/namenode/INodeDirectory;Lorg/apache/hadoop/hdfs/server/namenode/snapshot/SnapshotManager;Ljava/lang/String;Lorg/apache/hadoop/hdfs/server/namenode/LeaseManager;J)Lorg/apache/hadoop/hdfs/server/namenode/snapshot/Snapshot;@189:throw:1",
        "evidence": "data/mallory/calibration_v2/HDFS-49/result.json",
        "evidence_sha256": "4c5497d8a097d3cfd5257fa143d682615631130b147a37d15e2b485a17c43950",
        "scope": "independent_healthy_calibration_only",
    },
    "ZOOKEEPER-02": {
        "source_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
        "target_source_sha256": "baffc60cd94b7b2c9edd3ea21602e02f782c26a32e82e80aac6d88cfe9fdc1bd",
        "class_sha256": "ca545363df047e5c0417554ac77a2f35eaf22e68c3fa775ccf25d5148ca171c4",
        "test_class_sha256": "b29ee15a70c943fd74e51f98b14f543d59383d3e5e37c956415e0c6b9ac84932",
        "check_sites": ["org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@325:branch:4"],
        "throw_site": "org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@326:throw:1",
        "evidence": "data/mallory/calibration/ZOOKEEPER-02-03-alternate/healthy/calibration.json",
        "evidence_sha256": "e969b911d7d8a90c22496e32b256e0ab12b2e680fa3d0c8eb62be4d804732eec",
        "scope": "independent_healthy_calibration_only",
    },
    "ZOOKEEPER-03": {
        "source_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
        "target_source_sha256": "baffc60cd94b7b2c9edd3ea21602e02f782c26a32e82e80aac6d88cfe9fdc1bd",
        "class_sha256": "ca545363df047e5c0417554ac77a2f35eaf22e68c3fa775ccf25d5148ca171c4",
        "test_class_sha256": "b29ee15a70c943fd74e51f98b14f543d59383d3e5e37c956415e0c6b9ac84932",
        "check_sites": ["org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@333:branch:1",
                        "org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@333:branch:2"],
        "throw_site": "org.apache.zookeeper.server.SessionTrackerImpl#setOwner(JLjava/lang/Object;)V@334:throw:1",
        "evidence": "data/mallory/calibration/ZOOKEEPER-02-03-alternate/healthy/calibration.json",
        "evidence_sha256": "e969b911d7d8a90c22496e32b256e0ab12b2e680fa3d0c8eb62be4d804732eec",
        "scope": "independent_healthy_calibration_only",
    },
    "ZOOKEEPER-11": {
        "source_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
        "target_source_sha256": "72606c8b4f2d887a94555de2d5fd6ec213b33496da8469df73064d5dfbe4d651",
        "class_sha256": "cdcb7a67d5905fef27a8e36824b5d504c8df2c907dfac1a3cb8af6e3abbb6052",
        "test_class_sha256": "05cb4b39fee9ae7c48313d9d0cef08ce6e1b929f57ba480cf98cbe2af7fa8f85",
        "check_sites": ["org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1169:branch:2"],
        "throw_site": "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1175:throw:1",
        "evidence": "Mallory/instrumentation/pilots/zookeeper11/attestation.json",
    },
}


def source_override(row: dict) -> Path:
    name = row["provenance"]["source_root_env"]
    return Path(os.environ.get(name, row["provenance"]["source_root"]))


def dist_override(row: dict) -> Path:
    name = row["provenance"]["distribution_root_env"]
    return Path(os.environ.get(name, row["provenance"]["distribution_root"]))


def target_class(row: dict) -> str:
    site = row["target"]["site_id"]
    match = re.match(r"<([^:]+):", site or "")
    if match:
        return match.group(1)
    method = row["target"]["function"].split("(", 1)[0]
    return method.rsplit(".", 1)[0]


def target_method(row: dict) -> str:
    method = row["target"]["function"].split("(", 1)[0]
    return method.rsplit(".", 1)[1]


def jar_path(row: dict) -> Path:
    system, version = row["system"], row["system_version"]
    source_path = row["target"]["source_path"]
    module = source_path.split("/src/")[0].split("/")[-1]
    root = dist_override(row)
    if system == "hbase":
        return root / "lib" / f"{module}-{version}.jar"
    if system == "hdfs":
        return root / "share" / "hadoop" / "hdfs" / f"{module}-{version}.jar"
    if system == "solr":
        artifact = "solrj" if module == "solrj" else "core"
        return root / "dist" / f"solr-{artifact}-{version}.jar"
    if system == "zookeeper":
        return root / "lib" / f"zookeeper-{version}.jar"
    raise ValueError(system)


def runtime_source_root(row: dict) -> Path | None:
    root = ISOLATED_ROOTS.get(row["system"])
    if root is not None and row.get("build"):
        return Path(row["build"]["cwd"])
    return root


def compiled_source(row: dict, clazz: str) -> Path:
    root = runtime_source_root(row)
    if root is None:
        return jar_path(row)
    module = row["target"]["source_path"].split("/src/")[0]
    classes = root / module / "target" / "classes"
    return classes


def class_bytes(source: Path, clazz: str) -> bytes:
    name = clazz.replace(".", "/") + ".class"
    if source.is_dir():
        return (source / name).read_bytes()
    with zipfile.ZipFile(source) as archive:
        return archive.read(name)


@lru_cache(maxsize=None)
def source_line_map(pristine: str, runtime: str) -> dict[int, int]:
    old = Path(pristine).read_text(errors="replace").splitlines()
    new = Path(runtime).read_text(errors="replace").splitlines()
    if old == new:
        return {index: index for index in range(1, len(old) + 1)}
    matched = difflib.SequenceMatcher(None, old, new, autojunk=False)
    result = {}
    for block in matched.get_matching_blocks():
        for offset in range(block.size):
            result[block.a + offset + 1] = block.b + offset + 1
    return result


def map_line(row: dict, source_line: int | None) -> int | None:
    if source_line is None:
        return None
    root = runtime_source_root(row)
    if root is None:
        return source_line
    relative = row["target"]["source_path"]
    pristine = source_override(row) / relative
    runtime = root / relative
    if not pristine.is_file() or not runtime.is_file():
        return None
    return source_line_map(str(pristine), str(runtime)).get(source_line)


def compile_helper() -> None:
    if not AGENT.is_file():
        raise FileNotFoundError("build Mallory/instrumentation/target/mallory-agent.jar first")
    class_file = BUILD / "BytecodeSites.class"
    source = HERE / "BytecodeSites.java"
    if class_file.is_file() and class_file.stat().st_mtime >= source.stat().st_mtime:
        return
    BUILD.mkdir(exist_ok=True)
    subprocess.run(["javac", "-cp", str(AGENT), "-d", str(BUILD), str(source)], check=True)


def instruction_sites(jar: Path, clazz: str, method: str) -> list[dict]:
    if not jar.is_file() and not jar.is_dir():
        raise FileNotFoundError(jar)
    class_bytes(jar, clazz)
    result = subprocess.run(["java", "-cp", os.pathsep.join([str(BUILD), str(AGENT)]),
                             "BytecodeSites", str(jar), clazz, method],
                            capture_output=True, text=True, check=True)
    groups = []
    current = None
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if fields[0] == "M":
            current = {"method": fields[1], "descriptor": fields[2], "instructions": []}
            groups.append(current)
        elif current is not None and fields[0] == "B":
            current["instructions"].append({"kind": "branch", "sequence": int(fields[1]),
                                             "line": int(fields[2]), "index": int(fields[3]),
                                             "opcode": int(fields[4])})
        elif current is not None and fields[0] == "T":
            current["instructions"].append({"kind": "throw", "sequence": int(fields[1]),
                                             "line": int(fields[2])})
        elif current is not None and fields[0] == "C":
            current["instructions"].append({"kind": "call", "sequence": int(fields[1]),
                                             "line": int(fields[2]), "index": int(fields[3]),
                                             "callee_internal": fields[4]})
    return groups


def resolve(row: dict) -> dict:
    clazz, method = target_class(row), target_method(row)
    jar = jar_path(row)
    artifact = compiled_source(row, clazz)
    runtime_root = runtime_source_root(row) or source_override(row)
    runtime_target = runtime_root / row["target"]["source_path"]
    result = {"class": clazz, "method": method, "jar": str(jar),
              "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest() if jar.is_file() else None,
              "class_sha256": None,
              "compiled_artifact": str(artifact),
              "runtime_target_source_sha256": (hashlib.sha256(runtime_target.read_bytes()).hexdigest()
                                               if runtime_target.is_file() else None),
              "source_check_start_line": map_line(row, CHECK_LINES.get(row["case_id"])),
              "source_selected_line": map_line(row, row["target"]["source_line"]),
              "original_check_start_line": CHECK_LINES.get(row["case_id"]),
              "original_selected_line": row["target"]["source_line"],
              "selection_guard_id": row["target"]["target_guard"],
              "selection_throw_id": row["target"]["target_throw"],
              "mapping_status": "unresolved", "gaps": []}
    try:
        groups = instruction_sites(artifact, clazz, method)
        result["class_sha256"] = hashlib.sha256(class_bytes(artifact, clazz)).hexdigest()
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        result["gaps"].append("compiled_class_unavailable:" + str(exc))
        return result
    descriptor_hint = None
    hint = row["target"]["target_throw"]
    if hint:
        match = re.search(r"#" + re.escape(method) + r"(\([^#]+\)[^#]+)#L\d+$", hint)
        if match:
            descriptor_hint = match.group(1)
    if descriptor_hint:
        groups = [group for group in groups if group["descriptor"] == descriptor_hint]
    if row["case_id"] in CALLTHROW:
        mapped = CALLTHROW[row["case_id"]]
        invocation = mapped["target_call"]
        matches = [(group, call) for group in groups if group["descriptor"] == mapped["descriptor"]
                   for call in group["instructions"] if call["kind"] == "call"
                   and call["line"] == invocation["source_line"]
                   and call["index"] == invocation["invocation_ordinal"]
                   and call["callee_internal"] == invocation["callee"]]
        if (len(matches) != 1 or result["jar_sha256"] != mapped["distribution_jar_sha256"]
                or row["target"]["source_sha256"] != mapped["target_source_sha256"]):
            result["gaps"].append("callthrow_mapping_or_artifact_mismatch")
            return result
        group, call = matches[0]
        base = clazz + "#" + method + group["descriptor"]
        branches = [ins for ins in group["instructions"] if ins["kind"] == "branch"
                    and base + f"@{ins['line']}:branch:{ins['index']}" in mapped["guard_sites"]]
        if (len(branches) != len(mapped["guard_sites"])
                or base + f"@{call['line']}:callthrow:{call['index']}"
                != mapped["proposed_callthrow_site"]):
            result["gaps"].append("callthrow_guard_or_ordinal_mismatch")
            return result
        owner, descriptor = call["callee_internal"].split("#", 1)
        call["callee"] = owner.replace("/", ".") + "#" + descriptor
        result.update({"descriptor": group["descriptor"],
                       "check_sites": mapped["guard_sites"],
                       "throw_site": mapped["proposed_callthrow_site"],
                       "branch_instructions": branches, "throw_instruction": call,
                       "mapping_status": "unique_compiled_callthrow_site"})
        return result
    override = GUARD_LINE_OVERRIDES.get(row["case_id"])
    check_line = map_line(row, override) if override is not None else result["source_check_start_line"]
    if check_line != result["source_check_start_line"]:
        result["source_inspected_guard_line_override"] = check_line
    selected_line = result["source_selected_line"]
    viable = []
    for group in groups:
        instructions = group["instructions"]
        throws = [ins for ins in instructions if ins["kind"] == "throw"
                  and ins["line"] == selected_line]
        if not throws and check_line is not None:
            throws = [ins for ins in instructions if ins["kind"] == "throw"
                      and check_line <= ins["line"] <= selected_line + 3]
        if len(throws) != 1:
            continue
        branches = [ins for ins in instructions if ins["kind"] == "branch"
                    and check_line is not None and ins["line"] == check_line]
        if not branches and check_line is not None:
            branches = [ins for ins in instructions if ins["kind"] == "branch"
                        and check_line <= ins["line"] <= selected_line]
        # A condition with multiple bytecode jumps on one source line can
        # legitimately have multiple probes, all explicitly retained.
        if not branches:
            continue
        viable.append((group, branches, throws[0]))
    if len(viable) != 1:
        result["gaps"].append(f"bytecode_target_ambiguous:method_candidates={len(groups)},valid_candidates={len(viable)}")
        result["candidate_methods"] = [{"descriptor": g["descriptor"],
                                         "branches": [x for x in g["instructions"] if x["kind"] == "branch"
                                                      and check_line is not None and check_line - 2 <= x["line"] <= selected_line + 2],
                                         "throws": [x for x in g["instructions"] if x["kind"] == "throw"
                                                    and check_line is not None and check_line - 2 <= x["line"] <= selected_line + 4]}
                                        for g in groups]
        return result
    group, branches, throw = viable[0]
    base = clazz + "#" + method + group["descriptor"]
    matched_lines = {x["line"] for x in branches} | {throw["line"]}
    target_throws_before = [x for x in group["instructions"] if x["kind"] == "throw"
                            and x["line"] in matched_lines and x["sequence"] <= throw["sequence"]]
    same_line_throws = [x for x in group["instructions"] if x["kind"] == "throw"
                        and x["line"] == throw["line"]]
    if len(same_line_throws) != 1:
        result["gaps"].append("multiple_athrow_on_selected_line")
        return result
    result.update({"descriptor": group["descriptor"],
                   "check_sites": [base + f"@{b['line']}:branch:{b['index']}" for b in branches],
                   "throw_site": base + f"@{throw['line']}:throw:{len(target_throws_before)}",
                   "branch_instructions": branches, "throw_instruction": throw,
                   "mapping_status": "unique_compiled_site"})
    return result


def build_case(row: dict, site: dict) -> dict:
    test = row["workload"]
    source_root, dist_root = source_override(row), dist_override(row)
    build = row["build"]
    assert build is not None
    cwd = (Path(build["cwd"]) if row["system"] in ISOLATED_ROOTS
           or row["system"] in ("solr", "hbase") else source_root / build["cwd_relative_to_source_root"])
    include = [site["class"]]
    if row["system"] == "hdfs":
        include += ["org.apache.hadoop.ipc.Server$RpcCall",
                    "org.apache.hadoop.hdfs.server.namenode.NameNodeRpcServer",
                    "org.apache.hadoop.hdfs.server.datanode.DataXceiver"]
    check_rules = [{"clazz": site["class"], "method": site["method"],
                    "descriptor": site["descriptor"], "line": b["line"]}
                   for b in site["branch_instructions"]]
    throw_rule = {"clazz": site["class"], "method": site["method"],
                  "descriptor": site["descriptor"], "line": site["throw_instruction"]["line"]}
    if site["throw_instruction"]["kind"] == "call":
        throw_rule["callee"] = site["throw_instruction"]["callee"]
        throw_rule["exception_class"] = row["target"]["target_exception"]
    targets = list({(r["clazz"], r["method"], r["descriptor"], r["line"], r.get("callee")): r
                    for r in check_rules + [throw_rule]}.values())
    generated_site_file = HERE / f"{row['case_id']}.sites.json"
    write_json(generated_site_file, {"targets": targets,
                           "regions": [{"clazz": site["class"], "method": site["method"],
                                        "descriptor": site["descriptor"]}],
                           "doors": ([{"clazz": "org.apache.hadoop.hbase.ipc.RpcServer",
                                       "method": "call", "line": 447,
                                       "callee": "org.apache.hbase.thirdparty.com.google.protobuf.BlockingService#callBlockingMethod(Lorg/apache/hbase/thirdparty/com/google/protobuf/Descriptors$MethodDescriptor;Lorg/apache/hbase/thirdparty/com/google/protobuf/RpcController;Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;)Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;",
                                       "exception_class": "java.io.IOException"}]
                                     if row["system"] == "hbase" else []),
                           "nodeBindings": NODE_BINDINGS.get(row["case_id"], [])})
    legacy = row["provenance"]
    # Historical seed time is advisory; the ceiling remains an explicit hard
    # limit so a new instrumentation overhead can still be recognized.
    prior_seed = row["provenance"].get("historical_seed_seconds")
    timeout = min(1200, max(180, math.ceil(3 * prior_seed + 60))) if prior_seed else (
        900 if row["system"] in ("hbase", "solr") else 600)
    if row["case_id"] in ("HDFS-11", "HDFS-12", "HDFS-14"):
        timeout = max(timeout, 1200)  # Class-level Parameterized calibration runs every variant.
    command = [arg.replace("{case_id}", row["case_id"]) for arg in build["argv"]]
    if row["system"] == "solr":
        command += ["--timeout", str(max(30, timeout - 30))]
    site_file = ((BASELINE / "Mallory" / "adapters" / row["system"] / "cases"
                  / row["case_id"] / "sites.json")
                 if row["system"] in ("solr", "hdfs")
                 and row["case_id"] not in SOURCE_INFEASIBLE_HEALTHY_GUARD
                 else generated_site_file)
    if not site_file.is_file():
        site_file = generated_site_file
    if row["system"] == "hbase":
        include.append("org.apache.hadoop.hbase.ipc.RpcServer")
        command = [arg.replace("{trial_dir}", "{trial_dir}") for arg in command]
    exception = (row["target"]["target_exception"] or ZK_EXCEPTIONS.get(row["case_id"])
                 or CALLTHROW.get(row["case_id"], {}).get("exception_class"))
    assert exception
    attestation = VERIFIED_HEALTHY_PROBES.get(row["case_id"])
    if attestation:
        if (row["provenance"]["source_commit"] != attestation["source_commit"]
                or row["target"]["source_sha256"] != attestation["target_source_sha256"]):
            raise ValueError(row["case_id"] + " pilot source differs from original inventory")
        if (site["class_sha256"] != attestation["class_sha256"]
                or site["check_sites"] != attestation["check_sites"]
                or site["throw_site"] != attestation["throw_site"]):
            attestation = None  # A patched class supersedes the independent pristine pilot.
    config = {
        "schema_version": 1, "case_id": row["case_id"], "system": row["system"],
        "calibration_only": True,
        "cluster_test": test["selected_selector"], "cwd": str(cwd),
        "command": command, "agent_jar": str(Path(build["runtime_root"]) / "agent.jar"
                                           if row["system"] == "hbase" else AGENT),
        "agent_transport": "surefire_argline" if build["tool"] == "maven" else "java_tool_options",
        **({"agent_arg_property": build["agent_arg_property"]}
           if build.get("agent_arg_property") else {}),
        "site_file": str(site_file), "agent_include": include,
        "agent_properties": ({"adapter.jar": str(BASELINE / "Mallory" / "adapters" / "solr"
                                                   / "target" / "mallory-solr-adapter.jar"),
                              "adapter.transformer": "edu.uva.liftlab.mallory.solr.SolrTransformer",
                              "auto.io.doors": row["case_id"] != "SOLR-05",
                              "coverage.methods": True, "coverage.branches": True,
                              "state.fields": False, "state.maps": False}
                             if row["system"] == "solr" else
                             {"adapter.jar": str(BASELINE / "Mallory" / "adapters" / "hdfs"
                                                   / "target" / "mallory-hdfs-adapter.jar"),
                              "adapter.transformer": "edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer",
                              "auto.io.doors": row["case_id"] != "HDFS-01",
                              "coverage.methods": True, "coverage.branches": True,
                              "state.fields": False, "state.maps": False}
                             if row["system"] == "hdfs" else
                             {"auto.io.doors": False, "coverage.methods": True,
                              "coverage.branches": True, "state.fields": False,
                              "state.maps": True}
                             if row["system"] == "zookeeper" else
                             {"adapter.jar": str(Path(build["runtime_root"]) / "adapter.jar"),
                              "adapter.transformer": "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer",
                              "auto.io.doors": row["case_id"] != "HBASE-01",
                              "coverage.methods": True, "coverage.branches": True,
                              "state.fields": False, "state.maps": False}),
        "target": {"check_sites": site["check_sites"], "throw_site": site["throw_site"],
                   "exception_class": exception,
                   "site_id": row["target"]["site_id"],
                   "source_path": row["target"]["source_path"],
                   "source_line": site["source_selected_line"],
                   "original_source_line": row["target"]["source_line"],
                   "function": row["target"]["function"],
                   "check_code": row["target"]["check_code"]},
        "budget": {"trials": 80, "seconds": 3600,
                   "max_faults_per_trial": 6, "trial_timeout_seconds": timeout,
                   "trial_timeout_basis": "3x_historical_seed_plus_60s_capped_180_to_1200"
                   if prior_seed else "system_default_pending_mallory_seed"},
        "mapping": {"status": "preliminary_compiled_distribution_site", "compiled_jar": site["jar"],
                    "agent_build": {"cwd": str(BASELINE / "Mallory" / "instrumentation"),
                                    "command": ["mvn", "test", "package"],
                                    "artifact": str(AGENT)},
                    "agent_sha256": hashlib.sha256(AGENT.read_bytes()).hexdigest(),
                    "target_throw_kind": ("invocation_exception" if site["throw_instruction"]["kind"] == "call"
                                          else "athrow"),
                    "compiled_jar_sha256": site["jar_sha256"],
                    "compiled_class_sha256": site["class_sha256"],
                    "compiled_artifact": site["compiled_artifact"],
                    "node_identity_binding_configured": row["case_id"] in NODE_BINDINGS,
                    "node_identity_binding_verified": False,
                    "verified_healthy_probe": attestation,
                    "source_root": str(cwd if row["system"] in ISOLATED_ROOTS else source_root),
                    "inventory_source_root": str(source_root),
                    "distribution_root": str(dist_root),
                    "source_root_env": legacy["source_root_env"],
                    "distribution_root_env": legacy["distribution_root_env"],
                    "test_source_sha256": hashlib.sha256((cwd / test["test_source_path"]).read_bytes()).hexdigest()
                    if row["system"] in ISOLATED_ROOTS else next((c["source_sha256"] for c in test["candidates"]
                                                if c.get("selector") == test["selected_selector"]), None),
                    "target_source_sha256": site["runtime_target_source_sha256"],
                    "healthy_seed_verified": False},
    }
    if row["system"] in ISOLATED_ROOTS or row["system"] == "hbase":
        config["expected_target_class_sha256"] = site["class_sha256"]
    if row["system"] == "hdfs":
        config["source_equivalent_root"] = str(cwd)
        config["mapping"]["system_receipt"] = str(BASELINE / "Mallory" / "adapters"
                                                 / "hdfs" / "overlay-receipt.json")
        config["mapping"]["system_receipt_sha256"] = hashlib.sha256((BASELINE / "Mallory" / "adapters"
                                            / "hdfs" / "overlay-receipt.json").read_bytes()).hexdigest()
    if row["system"] == "zookeeper":
        receipt = BASELINE / "Mallory" / "adapters" / "zookeeper" / "zookeeper-3.8.7-overlay.json"
        config["source_overlay_receipt"] = str(receipt)
        config["source_overlay_receipt_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    if row["system"] == "solr":
        config["source_equivalent_root"] = str(cwd)
        config["mapping"]["runner_status"] = "direct_junit_runner_pending_per_case_healthy_calibration"
        config["mapping"]["door_status"] = ("explicit_adapter_door_pending_healthy_calibration"
                                             if row["case_id"] == "SOLR-05" else
                                             "auto_io_doors_pending_healthy_calibration")
    if row["system"] == "hbase":
        receipt_path = Path(build["receipt"])
        receipt = json.loads(receipt_path.read_text())
        pinned = (receipt["compiled_artifacts"] if row["case_id"] == "HBASE-01"
                  else receipt["artifacts"])
        runtime_root = Path(build["runtime_root"])
        config["env"] = receipt.get("env", {"HBASE_HOME": str(dist_root)})
        if row["case_id"] == "HBASE-01":
            site_file = runtime_root / "cases" / "HBASE-01" / "sites.json"
            config["site_file"] = str(site_file)
            site_sha = HBASE01_SITES_SHA256
        else:
            site_sha = hashlib.sha256(generated_site_file.read_bytes()).hexdigest()
        config["runtime_artifacts"] = [
            {"path": str(runtime_root / "agent.jar"), "sha256": pinned["agent_jar_sha256"]},
            {"path": str(runtime_root / "adapter.jar"), "sha256": pinned["adapter_jar_sha256"]},
            {"path": str(runtime_root / "classes" / "edu/uva/liftlab/mallory/hbase/pilot/SelectedJUnit.class"),
             "sha256": HBASE_RUNNER_SHA256},
            {"path": str(runtime_root / "junit-platform-launcher.jar"),
             "sha256": pinned["junit_platform_launcher_jar_sha256"]},
            {"path": str(dist_root / "lib" / "hbase-server-2.6.6-tests.jar"),
             "sha256": pinned["hbase_server_tests_jar_sha256"]},
            {"path": str(config["site_file"]), "sha256": site_sha},
        ]
        config["mapping"]["system_receipt"] = str(receipt_path)
        config["mapping"]["system_receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        config["mapping"]["runner_status"] = "direct_junit_runner_pending_per_case_healthy_calibration"
        if row["case_id"] != "HBASE-01":
            config["source_equivalent_root"] = str(cwd)
    elif row["system"] in ("hdfs", "solr"):
        artifact_paths = [Path(config["agent_jar"]), Path(config["site_file"]),
                          Path(config["agent_properties"]["adapter.jar"])]
        config["runtime_artifacts"] = [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in artifact_paths if path.is_file()]
    else:
        artifact_paths = [Path(config["agent_jar"]), Path(config["site_file"])]
        config["runtime_artifacts"] = [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in artifact_paths if path.is_file()]
    return config


def main() -> None:
    compile_helper()
    inventory = json.loads((HERE / "inventory.json").read_text())
    summary = {"schema_version": 1, "original_count": 102, "mapped_config_count": 0,
               "ready_for_seed_count": 0, "build_tool_unavailable_count": 0,
               "workload_oracle_unfit_count": 0,
               "workload_target_overload_mismatch_count": 0,
               "source_infeasible_healthy_guard_count": 0,
               "unready_count": 0, "cases": []}
    for row in inventory["cases"]:
        site = resolve(row)
        row["target"]["target_exception"] = (row["target"]["target_exception"]
                                             or ZK_EXCEPTIONS.get(row["case_id"])
                                             or CALLTHROW.get(row["case_id"], {}).get("exception_class"))
        row["target"]["runtime_mapping"] = (
            {"check_sites": site["check_sites"], "throw_site": site["throw_site"],
             "compiled_artifact": site["compiled_artifact"],
             "compiled_class_sha256": site["class_sha256"],
             "selected_source_line": site["source_selected_line"],
             "exception_class": row["target"]["target_exception"]}
            if site["mapping_status"] in ("unique_compiled_site", "unique_compiled_callthrow_site")
            else None)
        if row["case_id"] in SOLR_AUDIT:
            audit = SOLR_AUDIT[row["case_id"]]
            row["workload"]["source_reachability_audit"] = {
                key: audit[key] for key in ("healthy_guard_reachability", "source_evidence", "reason", "caveat")}
        eligible = row["eligibility"]["may_attempt_seed"]
        if eligible and site["mapping_status"] in ("unique_compiled_site", "unique_compiled_callthrow_site"):
            config = build_case(row, site)
            write_json(HERE / f"{row['case_id']}.json", config)
            summary["mapped_config_count"] += 1
            if row["case_id"] in WORKLOAD_ORACLE_UNFIT:
                status = "workload_oracle_unfit"
                summary["workload_oracle_unfit_count"] += 1
                site["gaps"].append("selected_cluster_test_intentionally_exercises_target_rejection")
            elif row["case_id"] in WORKLOAD_OVERLOAD_MISMATCH:
                status = "workload_target_overload_mismatch"
                summary["workload_target_overload_mismatch_count"] += 1
                site["gaps"].append("selected_cluster_test_executes_six_argument_token_overload_not_four_argument_target")
            elif row["case_id"] in SOURCE_INFEASIBLE_HEALTHY_GUARD:
                status = "source_infeasible_healthy_guard"
                summary["source_infeasible_healthy_guard_count"] += 1
                site["gaps"].append("selected_inner_guard_requires_enclosing_throw_path")
            elif not (row["build"].get("tool_available_on_inventory_host", False)
                    or row["build"].get("runner_ready_on_designated_host", False)):
                status = "build_tool_unavailable"
                summary["build_tool_unavailable_count"] += 1
                site["gaps"].append("build_tool_unavailable_on_inventory_host:" + row["build"]["tool"])
            else:
                status = "ready_for_healthy_seed"
                summary["ready_for_seed_count"] += 1
        else:
            status = "unready"
            summary["unready_count"] += 1
            site["gaps"].append("no_source_mapped_cluster_test" if not eligible else "bytecode_mapping_unresolved")
            (HERE / f"{row['case_id']}.json").unlink(missing_ok=True)
            (HERE / f"{row['case_id']}.sites.json").unlink(missing_ok=True)
        row["eligibility"]["state"] = status if eligible else "no_mapped_cluster_test"
        row["eligibility"]["bytecode_mapping_status"] = site["mapping_status"]
        row["eligibility"]["may_dispatch_healthy_seed"] = status == "ready_for_healthy_seed"
        row["eligibility"]["mapping_gaps"] = site["gaps"]
        summary["cases"].append({"case_id": row["case_id"], "status": status,
                                 "site_mapping": site})
    write_json(HERE / "mapping_audit.json", summary)
    inventory["eligibility_counts"] = {
        state: sum(row["eligibility"]["state"] == state for row in inventory["cases"])
        for state in sorted({row["eligibility"]["state"] for row in inventory["cases"]})}
    write_json(HERE / "inventory.json", inventory)
    print(f"{summary['mapped_config_count']} bytecode mapped; "
          f"{summary['ready_for_seed_count']} have a local build tool; "
          f"{summary['build_tool_unavailable_count']} lack one; "
          f"{summary['unready_count']} unmapped")


if __name__ == "__main__":
    main()
