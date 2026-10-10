#!/usr/bin/env python3
"""Inspect a completed healthy trace; sampled field versions never prove a path."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

FIELD = "org.apache.solr.cloud.CloudDescriptor#isLeader"
DOOR_PREFIX = "org.apache.solr.cloud.ShardLeaderElectionContext#"
WRITE_PREFIX = "org.apache.solr.cloud.CloudDescriptor#setLeader(Z)V@101:field:"
READ_PREFIX = "org.apache.solr.cloud.CloudDescriptor#isLeader()Z@97:field:"
ELECTION_PREFIX = "org.apache.solr.cloud.ShardLeaderElectionContext#runLeaderProcess(ZI)V"
TARGET_PREFIX = ("org.apache.solr.update.processor.DistributedZkUpdateProcessor"
                 "#doDefensiveChecks(Lorg/apache/solr/update/processor/"
                 "DistributedUpdateProcessor$DistribPhase;)V@1021:branch:")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(trial: Path) -> tuple[dict, ...]:
    raw = trial / "events.jsonl"
    compressed = trial / "events.jsonl.gz"
    if raw.is_file():
        stream = raw.open("rt", encoding="utf-8")
    elif compressed.is_file():
        stream = gzip.open(compressed, "rt", encoding="utf-8")
    else:
        raise ValueError("healthy trace absent")
    rows = []
    with stream:
        for index, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise ValueError("incomplete trace line")
            if line.strip():
                event = json.loads(line)
                if not isinstance(event.get("seq"), int):
                    event["seq"] = index
                rows.append(event)
    if any(event.get("type") == "TRACE_TRUNCATED" for event in rows):
        raise ValueError("healthy trace truncated")
    return tuple(rows)


def same_actor(left: dict, right: dict) -> bool:
    return (left.get("node") == right.get("node")
            and left.get("node") not in (None, "", "unknown")
            and left.get("epoch") == right.get("epoch"))


def same_thread(left: dict, right: dict) -> bool:
    return (isinstance(left.get("thread_id"), int)
            and left.get("thread_id") == right.get("thread_id"))


def region_intervals(events: tuple[dict, ...]) -> list[tuple[dict, dict]]:
    def key(row: dict) -> tuple:
        return (row.get("node"), row.get("epoch"), row.get("thread_id"),
                row.get("occurrence"))
    entries = {key(row): row for row in events
               if row.get("type") == "REGION_ENTER" and row.get("occurrence")}
    return [(entries[key(row)], row) for row in events
            if row.get("type") == "REGION_EXIT" and key(row) in entries]


def inside_region(intervals: list[tuple[dict, dict]], start: dict, end: dict,
                  region_prefix: str) -> bool:
    return any(str(entry.get("region", "")).startswith(region_prefix)
               and same_actor(entry, start) and same_actor(entry, end)
               and same_thread(entry, start) and same_thread(entry, end)
               and entry["seq"] < start["seq"] < end["seq"] < exit_["seq"]
               for entry, exit_ in intervals)


def audit(out: Path) -> dict:
    config_path = HERE / "config-healthy-node2.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if sha(out / "config.json") != sha(config_path):
        raise ValueError("healthy run used a different config")
    trial = out / "trials/r0000"
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    junit = result.get("junit_validation", {})
    if (result.get("case_id") != "SOLR-38" or result.get("plan") != []
            or junit.get("status") != "passed" or junit.get("tests") != 1):
        raise ValueError("unchanged healthy cluster JUnit did not pass")
    events = load(trial)
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and str(row.get("site", "")).startswith(DOOR_PREFIX)
             and ("@396:door:" in row["site"] or "@450:door:" in row["site"])
             and row.get("exception_class") ==
             "org.apache.zookeeper.KeeperException$ConnectionLossException"
             and row.get("node") not in (None, "", "unknown")]
    writes = [row for row in events if row.get("type") == "STATE_WRITE"
              and row.get("key") == FIELD
              and str(row.get("site", "")).startswith(WRITE_PREFIX)]
    reads = [row for row in events if row.get("type") == "STATE_READ"
             and row.get("key") == FIELD
             and str(row.get("site", "")).startswith(READ_PREFIX)]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK"
               and str(row.get("site", "")).startswith(TARGET_PREFIX)]
    intervals = region_intervals(events)
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    evidence = []
    for door in doors:
        for write in writes:
            if (not same_actor(door, write) or not same_thread(door, write)
                    or not door["seq"] < write["seq"]
                    or not inside_region(intervals, door, write, ELECTION_PREFIX)):
                continue
            for read in reads:
                if (not same_actor(write, read) or write.get("object") != read.get("object")
                        or write.get("object") in (None, "", "static")
                        or write.get("version") != read.get("version")
                        or not write["seq"] < read["seq"]):
                    continue
                if any(other["seq"] > write["seq"] and other["seq"] < read["seq"]
                       and same_actor(other, write) and other.get("object") == write.get("object")
                       for other in writes):
                    continue
                for target in targets:
                    if (not same_actor(read, target) or not same_thread(read, target)
                            or not read["seq"] < target["seq"]
                            or not inside_region(intervals, read, target,
                                "org.apache.solr.update.processor.DistributedZkUpdateProcessor#doDefensiveChecks")):
                        continue
                    path = graph.backward_event_reachability(target,
                        include_candidates=False).witness(door, require_edge=True)
                    evidence.append({"door": door.get("id"), "write": write.get("id"),
                                     "read": read.get("id"), "target": target.get("id"),
                                     "node": target.get("node"), "epoch": target.get("epoch"),
                                     "descriptor_object": write.get("object"),
                                     "sampled_version": write.get("version"),
                                     "observed_non_candidate_path": path is not None,
                                     "path_edge_kinds": [edge.kind for edge in path] if path else []})
    observed = [row for row in evidence if row["observed_non_candidate_path"]]
    return {"schema_version": 1, "case_id": "SOLR-38",
            "healthy_result_sha256": sha(trial / "result.json"),
            "counts": {"typed_election_doors": len(doors),
                       "leader_field_writes": len(writes),
                       "leader_field_reads": len(reads),
                       "exact_target_checks": len(targets),
                       "same_descriptor_candidates": len(evidence),
                       "observed_paths": len(observed)},
            "witnesses": evidence[:20],
            "healthy_path_gate_passed": bool(observed),
            "full_promotion_authorized": False,
            "remaining_gate": "A postfault target-retaining pilot and source review are required. Sampled field versions alone never authorize a full campaign."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_out", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = audit(args.campaign_out)
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
