#!/usr/bin/env python3
"""Source-backed, same-thread unique-writer audit for SOLR-38 healthy traces."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

SOURCE_PINS = {
    "solr/core/src/java/org/apache/solr/cloud/CloudDescriptor.java":
        "0220381b0f195a0b78f60f8772b4ccb24fe605791ddae3a4b2295bf049f49859",
    "solr/core/src/java/org/apache/solr/cloud/ShardLeaderElectionContext.java":
        "85cea845e164047224e986675771fe08ad02c5447bbfb7457f7e90bd49b55b00",
    "solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java":
        "f443baaebc22f93c5bf138cd48e4021bf1b88580881b6c36e2e50d5b7d898674",
}
ADAPTER_PINS = {
    "SolrTransformer.java": "3a96f53db06f7c4f381edb6680d3d3ed8c8b013543ca2a1bc24176af18ff2b34",
    "SolrHooks.java": "879f92aca17adbf1b0014fcf214a775ceafa8750935ebbc7beeadc6f6bbfa602",
}
SEALED_ARCHIVE_SHA256 = "954568a43a7b07f48d4185bde044b19d9a1e371ebf042174ad87f2a151a34763"
SEALED_RESULT_SHA256 = "3eee929e27aa85857d62a64355c1f5ffc2484b51a1f875a3d4fbdb2e02aadea4"
SEALED_TRACE_SHA256 = "b634e06f709bc20c254c6377bc3b1c221ed51998a0086604c1cedbeea184c10d"
ADAPTER_SHA256 = "0e88f4d0a19dc9bb12ce8031e8d491045be364184a130fc1bf5220eb0104f333"
AGENT_SHA256 = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
FIELD = "org.apache.solr.cloud.CloudDescriptor#isLeader"
NATIVE_WRITE = "org.apache.solr.cloud.CloudDescriptor#setLeader(Z)V@101:field:"
CONSTRUCTOR_WRITE = "org.apache.solr.cloud.CloudDescriptor#<init>"
NATIVE_READ = "org.apache.solr.cloud.CloudDescriptor#isLeader()Z@97:field:"
VALUE_WRITE = "solr38:leader-value:write"
VALUE_READ = "solr38:leader-value:read"
ELECTION = "org.apache.solr.cloud.ShardLeaderElectionContext#runLeaderProcess(ZI)V"
DOOR = "org.apache.solr.cloud.ShardLeaderElectionContext#waitForReplicasToComeUp(I)Z@396:door:"
TARGET_REGION = "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks"
TARGET = (TARGET_REGION + "(Lorg/apache/solr/update/processor/"
          "DistributedUpdateProcessor$DistribPhase;)V@1021:branch:")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(source_root: Path) -> dict[str, str]:
    paths = {name: source_root / name for name in SOURCE_PINS}
    for name, path in paths.items():
        if not path.is_file() or sha(path) != SOURCE_PINS[name]:
            raise ValueError(f"pinned Solr source differs: {name}")
    descriptor = paths[next(name for name in paths if name.endswith("CloudDescriptor.java"))].read_text()
    election = paths[next(name for name in paths if name.endswith("ShardLeaderElectionContext.java"))].read_text()
    target = paths[next(name for name in paths if name.endswith("DistributedZkUpdateProcessor.java"))].read_text()
    if not all(fragment in descriptor for fragment in (
            "private volatile boolean isLeader = false;",
            "public boolean isLeader() {\n    return isLeader;",
            "public void setLeader(boolean isLeader) {\n    this.isLeader = isLeader;",
            "setLeader(reloadFrom.isLeader);")):
        raise ValueError("leader field source structure changed")
    if descriptor.count("this.isLeader =") != 1:
        raise ValueError("additional direct leader field writer in descriptor")
    if not all(fragment in election for fragment in (
            "zkClient.getChildren(shardsElectZkPath, null, true)",
            "getCloudDescriptor().setLeader(true)")):
        raise ValueError("election door/write source path changed")
    method = target.split("private void doDefensiveChecks(DistribPhase phase) {", 1)[1].split(
        "  @Override\n  protected void doClose()", 1)[0]
    if not all(fragment in method for fragment in (
            "boolean localIsLeader = cloudDesc.isLeader();",
            "localIsLeader = cloudDesc.isLeader();",
            "if ((isLeader && !localIsLeader) || (isSubShardLeader && !localIsLeader)) {")):
        raise ValueError("target's local leader value flow changed")
    if method.count("localIsLeader =") != 2:
        raise ValueError("additional local leader assignment before target")
    adapter_root = HERE.parent / "election-value-node1-v1/adapter/src/main/java/edu/uva/liftlab/mallory/solr"
    adapter_paths = {name: adapter_root / name for name in ADAPTER_PINS}
    for name, path in adapter_paths.items():
        if not path.is_file() or sha(path) != ADAPTER_PINS[name]:
            raise ValueError(f"pinned accessor adapter differs: {name}")
    transformer = adapter_paths["SolrTransformer.java"].read_text()
    hooks = adapter_paths["SolrHooks.java"].read_text()
    if not all(fragment in transformer for fragment in (
            'if (write && opcode == Opcodes.RETURN)',
            'super.visitVarInsn(Opcodes.ILOAD, 1);',
            'else if (!write && opcode == Opcodes.IRETURN)',
            'super.visitInsn(Opcodes.DUP);',
            'super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "leaderRead",')):
        raise ValueError("accessor value hook no longer duplicates setter argument/getter return")
    if not all(fragment in hooks for fragment in (
            'Probe.stateWrite(descriptor, "solr38:isLeader=" + value,',
            'Probe.stateRead(descriptor, "solr38:isLeader=" + value,')):
        raise ValueError("accessor value events no longer carry descriptor identity")
    return {**SOURCE_PINS, **{"adapter/" + name: digest for name, digest in ADAPTER_PINS.items()}}


def same_thread(*rows: dict) -> bool:
    first = rows[0]
    return (first.get("node") not in (None, "", "unknown")
            and isinstance(first.get("epoch"), int)
            and isinstance(first.get("thread_id"), int)
            and all(row.get("node") == first["node"] and
                    row.get("epoch") == first["epoch"] and
                    row.get("thread_id") == first["thread_id"] for row in rows))


def intervals(events: list[dict]) -> dict[tuple, tuple[dict, dict]]:
    entries = {(row.get("node"), row.get("epoch"), row.get("thread_id"),
                row.get("occurrence")): row for row in events
               if row.get("type") == "REGION_ENTER" and row.get("occurrence")}
    pairs = {}
    for row in events:
        if row.get("type") != "REGION_EXIT":
            continue
        key = (row.get("node"), row.get("epoch"), row.get("thread_id"),
               row.get("occurrence"))
        if key in entries:
            pairs[key] = (entries[key], row)
    return pairs


def region_contains(pairs: dict, start: dict, end: dict, prefix: str) -> bool:
    if not same_thread(start, end):
        return False
    return any(str(entry.get("region", "")).startswith(prefix)
               and same_thread(entry, start, end)
               and entry["seq"] < start["seq"] < end["seq"] < exit_["seq"]
               for entry, exit_ in pairs.values())


def witnesses(events: list[dict]) -> list[dict]:
    if any(row.get("type") == "TRACE_TRUNCATED" for row in events):
        raise ValueError("truncated trace cannot prove writer uniqueness")
    pairs = intervals(events)
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and str(row.get("site", "")).startswith(DOOR)
             and row.get("fault_type") == "EXCEPTION"
             and row.get("exception_class") == EXCEPTION]
    field_writes = defaultdict(list)
    value_writes = defaultdict(list)
    field_reads = defaultdict(list)
    value_reads = defaultdict(list)
    targets = []
    for row in events:
        obj = row.get("object")
        key = (row.get("node"), row.get("epoch"), obj)
        if row.get("type") == "STATE_WRITE" and row.get("key") == FIELD:
            field_writes[key].append(row)
        elif row.get("type") == "STATE_WRITE" and row.get("site") == VALUE_WRITE:
            value_writes[key].append(row)
        elif row.get("type") == "STATE_READ" and row.get("key") == FIELD:
            field_reads[key].append(row)
        elif row.get("type") == "STATE_READ" and row.get("site") == VALUE_READ:
            value_reads[key].append(row)
        elif row.get("type") == "TARGET_CHECK" and str(row.get("site", "")).startswith(TARGET):
            targets.append(row)
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    result = []
    for target in targets:
        # The pinned method assigns localIsLeader only from cloudDesc.isLeader().
        # Select the final accessor return in this exact target invocation.
        matching = [read for rows in value_reads.values() for read in rows
                    if read.get("occurrence") == target.get("occurrence")
                    and same_thread(read, target) and read.get("seq", -1) < target.get("seq", -1)
                    and read.get("key") == "solr38:isLeader=true"]
        if not matching:
            continue
        read = max(matching, key=lambda row: row["seq"])
        obj = read.get("object")
        if obj in (None, "", "static"):
            continue
        key = (read["node"], read["epoch"], obj)
        writes = field_writes[key]
        # Complete pinned source exposes constructor initialization and one
        # setter on this descriptor. Reject every other observed native write.
        constructors = [row for row in writes if str(row.get("site", "")).startswith(CONSTRUCTOR_WRITE)]
        setters = [row for row in writes if str(row.get("site", "")).startswith(NATIVE_WRITE)]
        if len(writes) != 2 or len(constructors) != 1 or len(setters) != 1:
            continue
        write = setters[0]
        prior_writes = [row for row in writes if row["seq"] < read["seq"]]
        last_writer = max(prior_writes, key=lambda row: row["seq"], default=None)
        intervening_writes = [row for row in writes if write["seq"] < row["seq"] < read["seq"]]
        if not (constructors[0]["seq"] < write["seq"] < read["seq"]
                and last_writer is write and not intervening_writes
                and len(value_writes[key]) == 1):
            continue
        value_write = value_writes[key][0]
        if (value_write.get("key") != "solr38:isLeader=true"
                or not same_thread(write, value_write, read, target)
                or not write["seq"] < value_write["seq"] < read["seq"]):
            continue
        accessors = [row for row in field_reads[key] if str(row.get("site", "")).startswith(NATIVE_READ)
                     and same_thread(row, read) and row["seq"] < read["seq"]]
        if not accessors:
            continue
        native_read = max(accessors, key=lambda row: row["seq"])
        if not (native_read["seq"] < read["seq"] < target["seq"]
                and region_contains(pairs, native_read, target, TARGET_REGION)
                and native_read.get("version") == write.get("version")):
            continue
        # Any same-object setter elsewhere in the complete trace is a competing
        # writer, even if its hook appears after this read due to interleaving.
        if len([row for row in value_writes[key] if row.get("site") == VALUE_WRITE]) != 1:
            continue
        for door in doors:
            if (not same_thread(door, write, value_write, native_read, read, target)
                    or not door["seq"] < write["seq"]
                    or not region_contains(pairs, door, value_write, ELECTION)):
                continue
            strict = graph.backward_event_reachability(
                target, include_candidates=False).witness(door, require_edge=True)
            result.append({"door": door.get("id"), "native_write": write.get("id"),
                           "constructor_write": constructors[0].get("id"),
                           "value_write": value_write.get("id"),
                           "native_read": native_read.get("id"), "value_read": read.get("id"),
                           "target": target.get("id"), "target_outcome": target.get("outcome"),
                           "node": target["node"],
                           "epoch": target["epoch"], "thread_id": target["thread_id"],
                           "descriptor_object": obj, "writer_version": write.get("version"),
                           "last_writer_before_read": last_writer.get("id"),
                           "intervening_native_writes": len(intervening_writes),
                           "complete_trace_native_writer_count": len(writes),
                           "source_backed_same_thread_unique_writer": True,
                           "core_graph_strict_path": strict is not None})
    return result


def load_trace(trial: Path) -> list[dict]:
    receipt = json.loads((trial / "result.json").read_text(encoding="utf-8"))["events_evidence"]
    compressed = trial / "events.jsonl.gz"
    if sha(compressed) != receipt["gzip_sha256"]:
        raise ValueError("trace gzip digest differs")
    with gzip.open(compressed, "rb") as stream:
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
        raise ValueError("trace raw digest differs")
    if len(raw) != receipt["raw_bytes"] or compressed.stat().st_size != receipt["gzip_bytes"]:
        raise ValueError("trace byte count differs")
    if raw and not raw.endswith(b"\n"):
        raise ValueError("incomplete final trace line")
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def audit(campaign: Path) -> dict:
    top = json.loads((campaign / "result.json").read_text(encoding="utf-8"))
    trial = campaign / "trials/r0000"
    trial_result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    config = json.loads((campaign / "config.json").read_text(encoding="utf-8"))
    pilot = json.loads((trial / "pilot-result.json").read_text(encoding="utf-8"))
    build = json.loads((campaign / "adapter/build-receipt.json").read_text(encoding="utf-8"))
    if (top.get("case_id") != "SOLR-38" or top.get("status") != "calibration_complete"
            or not top.get("runtime_attestation", {}).get("valid")
            or top.get("runtime_attestation", {}).get("expected_target_class_sha256") !=
               top.get("runtime_attestation", {}).get("observed_target_class_sha256")
            or top.get("healthy_junit_validation", {}).get("status") != "passed"
            or top.get("healthy_junit_validation", {}).get("tests") != 1
            or trial_result.get("junit_validation", {}).get("status") != "passed"
            or trial_result.get("plan") != []
            or config.get("revision") != "SOLR-38-election-value-healthy-node1-v2"
            or config.get("mapping", {}).get("cloud_descriptor_source_sha256") !=
               SOURCE_PINS["solr/core/src/java/org/apache/solr/cloud/CloudDescriptor.java"]
            or config.get("mapping", {}).get("value_diagnostic_adapter_sha256") != ADAPTER_SHA256
            or config.get("mapping", {}).get("agent_sha256") != AGENT_SHA256
            or pilot.get("adapter_sha256") != ADAPTER_SHA256
            or pilot.get("agent_sha256") != AGENT_SHA256
            or build.get("adapter_sha256") != ADAPTER_SHA256
            or build.get("agent_sha256") != AGENT_SHA256
            or sha(campaign / "adapter/mallory-solr-adapter-v2.jar") != ADAPTER_SHA256):
        raise ValueError("healthy cluster JUnit or pinned runtime identity failed")
    if (sha(campaign / "result.json") != SEALED_RESULT_SHA256
            or sha(trial / "events.jsonl.gz") != SEALED_TRACE_SHA256):
        raise ValueError("input differs from sealed SOLR-38 v2 healthy evidence")
    source_root = Path(config["mapping"]["source_root"])
    source_hashes = verify_source(source_root)
    events = load_trace(trial)
    rows = witnesses(events)
    return {"schema_version": 1, "case_id": "SOLR-38",
            "sealed_archive_sha256": SEALED_ARCHIVE_SHA256,
            "healthy_result_sha256": sha(campaign / "result.json"),
            "trace_sha256": sha(trial / "events.jsonl.gz"),
            "source_sha256": source_hashes,
            "adapter_sha256": ADAPTER_SHA256, "agent_sha256": AGENT_SHA256,
            "exact_target_checks": sum(row.get("type") == "TARGET_CHECK" and
                                       str(row.get("site", "")).startswith(TARGET)
                                       for row in events),
            "source_backed_witness_count": len(rows), "witnesses": rows[:24],
            "core_graph_strict_path_count": sum(row["core_graph_strict_path"] for row in rows),
            "bounded_exploratory_pilot_candidate": bool(rows),
            "full_campaign_authorized": False,
            "limitation": "Unique complete-trace writer and same-thread program order are "
                          "source-backed evidence for these exact objects; Mallory's native "
                          "state edge remains sampled and the controller has not ingested "
                          "this case-specific proof."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    payload = json.dumps(audit(args.campaign), sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
