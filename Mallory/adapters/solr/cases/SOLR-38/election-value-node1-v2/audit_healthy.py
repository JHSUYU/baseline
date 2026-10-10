#!/usr/bin/env python3
"""Audit exact accessor values; never promote sampled state to an observed edge."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

import build_adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

DOOR = "org.apache.solr.cloud.ShardLeaderElectionContext#"
TARGET = ("org.apache.solr.update.processor.DistributedZkUpdateProcessor"
          "#doDefensiveChecks(Lorg/apache/solr/update/processor/"
          "DistributedUpdateProcessor$DistribPhase;)V@1021:branch:")
WRITE = "solr38:leader-value:write"
READ = "solr38:leader-value:read"
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def load_events(trial: Path) -> list[dict]:
    path = trial / "events.jsonl.gz"
    expected = json.loads((trial / "result.json").read_text(encoding="utf-8"))[
        "events_evidence"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected["gzip_sha256"]:
        raise ValueError("healthy trace gzip digest differs from result")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        lines = stream.readlines()
    if any(not line.endswith("\n") for line in lines):
        raise ValueError("incomplete healthy trace line")
    raw = "".join(lines).encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != expected["raw_sha256"]:
        raise ValueError("healthy trace raw digest differs from result")
    rows = [json.loads(line) for line in lines if line.strip()]
    if any(row.get("type") == "TRACE_TRUNCATED" for row in rows):
        raise ValueError("trace truncated")
    return rows


def same_actor(a: dict, b: dict) -> bool:
    return (a.get("node") == b.get("node")
            and a.get("node") not in (None, "", "unknown")
            and isinstance(a.get("epoch"), int)
            and a.get("epoch") == b.get("epoch"))


def inside_region(events: list[dict], start: dict, end: dict, prefix: str) -> bool:
    if not isinstance(start.get("thread_id"), int):
        return False
    entries = {(row.get("node"), row.get("epoch"), row.get("thread_id"),
                row.get("occurrence")): row for row in events
               if row.get("type") == "REGION_ENTER" and row.get("occurrence")}
    for exit_ in events:
        if exit_.get("type") != "REGION_EXIT":
            continue
        key = (exit_.get("node"), exit_.get("epoch"), exit_.get("thread_id"),
               exit_.get("occurrence"))
        entry = entries.get(key)
        if (entry and str(entry.get("region", "")).startswith(prefix)
                and same_actor(entry, start) and same_actor(entry, end)
                and entry.get("thread_id") == start.get("thread_id") == end.get("thread_id")
                and entry["seq"] < start["seq"] < end["seq"] < exit_["seq"]):
            return True
    return False


def value_witnesses(events: list[dict]) -> list[dict]:
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and str(row.get("site", "")).startswith(DOOR)
             and ("@396:door:" in row["site"] or "@450:door:" in row["site"])
             and row.get("fault_type") == "EXCEPTION"
             and row.get("exception_class") == EXCEPTION]
    writes = [row for row in events if row.get("type") == "STATE_WRITE"
              and row.get("site") == WRITE
              and row.get("key") == "solr38:isLeader=true"]
    all_writes = [row for row in events if row.get("type") == "STATE_WRITE"
                  and row.get("site") == WRITE]
    reads = [row for row in events if row.get("type") == "STATE_READ"
             and row.get("site") == READ
             and row.get("key") == "solr38:isLeader=true"]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK"
               and str(row.get("site", "")).startswith(TARGET)]
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    witnesses = []
    for door in doors:
        for write in writes:
            if (not same_actor(door, write)
                    or door.get("thread_id") != write.get("thread_id")
                    or door.get("seq", -1) >= write.get("seq", -1)
                    or not inside_region(events, door, write,
                                         "org.apache.solr.cloud.ShardLeaderElectionContext#runLeaderProcess")):
                continue
            for read in reads:
                if (not same_actor(write, read)
                        or write.get("object") != read.get("object")
                        or write.get("object") in (None, "", "static")
                        or write.get("seq", -1) >= read.get("seq", -1)
                        or any(same_actor(other, write)
                               and other.get("object") == write.get("object")
                               and write["seq"] < other["seq"] < read["seq"]
                               for other in all_writes)):
                    continue
                for target in targets:
                    if (not same_actor(read, target)
                            or read.get("thread_id") != target.get("thread_id")
                            or read.get("seq", -1) >= target.get("seq", -1)
                            or not inside_region(events, read, target,
                                                 "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks")):
                        continue
                    path = graph.backward_event_reachability(
                        target, include_candidates=False).witness(door, require_edge=True)
                    witnesses.append({"door": door.get("id"), "write": write.get("id"),
                                      "read": read.get("id"), "target": target.get("id"),
                                      "node": target.get("node"), "epoch": target.get("epoch"),
                                      "object": write.get("object"),
                                      "write_value": True, "read_value": True,
                                      "strict_graph_path": path is not None,
                                      "field_edge_certainty": "candidate"})
    return witnesses


def audit(out: Path) -> dict:
    trial = out / "trials/r0000"
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    junit = result.get("junit_validation", {})
    if (result.get("case_id") != "SOLR-38" or result.get("plan") != []
            or junit.get("status") != "passed" or junit.get("tests") != 1):
        raise ValueError("unchanged cluster JUnit did not pass")
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    adapter = str(build_adapter.OUT)
    adapter_sha = config.get("mapping", {}).get("value_diagnostic_adapter_sha256")
    pilot = json.loads((trial / "pilot-result.json").read_text(encoding="utf-8"))
    if (config.get("revision") != "SOLR-38-election-value-healthy-node1-v2"
            or config.get("agent_properties", {}).get("adapter.jar") != adapter
            or config.get("env", {}).get("MALLORY_SOLR_ADAPTER_JAR") != adapter
            or config.get("env", {}).get("MALLORY_SOLR_AGENT_JAR") != str(build_adapter.AGENT)
            or config.get("agent_jar") != str(build_adapter.AGENT)
            or not isinstance(adapter_sha, str)
            or not any(artifact.get("path") == adapter and
                       artifact.get("sha256") == adapter_sha
                       for artifact in config.get("runtime_artifacts", []))
            or pilot.get("adapter_sha256") != adapter_sha
            or pilot.get("agent_sha256") != build_adapter.sha(build_adapter.AGENT)
            or not result.get("runtime_attestation", {}).get("valid")):
        raise ValueError("value diagnostic adapter or runtime identity not attested")
    events = load_events(trial)
    witnesses = value_witnesses(events)
    return {"case_id": "SOLR-38", "schema_version": 1,
            "healthy_junit": "passed", "exact_target_checks": sum(
                row.get("type") == "TARGET_CHECK" and
                str(row.get("site", "")).startswith(TARGET) for row in events),
            "value_witnesses": witnesses[:20],
            "value_witness_count": len(witnesses),
            "strict_observed_paths": sum(row["strict_graph_path"] for row in witnesses),
            "full_promotion_authorized": False,
            "limitation": "Accessor values and object identity are observed after the volatile access; "
                          "no atomic read-from token or strict state edge is established."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("healthy_output", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = json.dumps(audit(args.healthy_output), sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
