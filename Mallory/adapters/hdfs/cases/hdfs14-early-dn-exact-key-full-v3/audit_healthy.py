#!/usr/bin/env python3
"""Seal a strict HDFS-14 registration -> exact key state -> check witness."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


BASE = Path("/users/ZhenyuLi/baseline")
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path[:0] = [str(CORE), str(BASE)]
from Mallory.core.graph import OccurrenceGraph  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    xml = ET.fromstring(args.junit.read_bytes())
    if tuple(int(xml.attrib.get(k, "-1")) for k in
             ("tests", "failures", "errors", "skipped")) != (2, 0, 0, 0):
        raise ValueError("HDFS-14 JUnit counts are not 2/0/0/0")
    testcases = xml.findall("testcase")
    if len(testcases) != 2 or {row.attrib.get("name") for row in testcases} != {
            "testEncryptedReadDefaultAlgorithmCipherSuite[0]",
            "testEncryptedReadDefaultAlgorithmCipherSuite[1]"}:
        raise ValueError("HDFS-14 exact parameterized JUnit selector was not run")

    packed = args.events.read_bytes()
    raw = gzip.decompress(packed)
    rows = [json.loads(line) for line in raw.splitlines()]
    if any(row.get("type") == "FAULT_APPLIED" for row in rows):
        raise ValueError("healthy trace contains an applied fault")
    if any(row.get("type") == "TARGET_THROW" and "#checkAccess(" in row.get("site", "")
           for row in rows):
        raise ValueError("selected target threw in healthy trace")

    graph = OccurrenceGraph(rows, reject_coarse_roots=True)
    by_id = {row.get("id"): row for row in rows}
    doors = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
             and "BPServiceActor#register(" in row.get("site", "")
             and "@829:door" in row.get("site", "")
             and row.get("exception_class") == "java.io.IOException"]
    targets = [row for row in rows if row.get("type") == "TARGET_CHECK"
               and "BlockTokenSecretManager#checkAccess(" in row.get("site", "")
               and "@411:branch" in row.get("site", "")]
    witnesses = []
    for door in doors:
        for target in targets:
            if door.get("node") != target.get("node") or target.get("outcome") != "TAKEN":
                continue
            if not str(door.get("node", "")).startswith("hdfs-cluster-"):
                continue
            path = graph.event_path(door, target, require_edge=True)
            if not path:
                continue
            state_edges = [edge for edge in path if edge.kind == "state"
                           and edge.certainty == "observed"]
            for edge in state_edges:
                write, read = by_id[edge.producer_event], by_id[edge.consumer_event]
                if (write.get("site") != "hdfs14:allKeys:write"
                        or read.get("site") != "hdfs14:allKeys:read"
                        or write.get("version_confidence") != "exact"
                        or read.get("version_confidence") != "exact"):
                    continue
                keys = ("node", "epoch", "object", "key", "version", "value_id",
                        "bpid", "state_token")
                if any(write.get(key) != read.get(key) for key in keys):
                    continue
                if (door.get("occurrence") != write.get("occurrence")
                        or door.get("thread_id") != write.get("thread_id")
                        or read.get("occurrence") != target.get("occurrence")
                        or read.get("thread_id") != target.get("thread_id")
                        or not door["seq"] < write["seq"] < read["seq"] < target["seq"]):
                    continue
                witnesses.append({"node": door["node"], "epoch": door["epoch"],
                                  "door_event": door["id"], "door_seq": door["seq"],
                                  "write_event": write["id"], "write_seq": write["seq"],
                                  "read_event": read["id"], "read_seq": read["seq"],
                                  "target_event": target["id"], "target_seq": target["seq"],
                                  "manager": write["object"], "key": write["key"],
                                  "version": write["version"], "value_id": write["value_id"],
                                  "state_token": write["state_token"],
                                  "path": [{"kind": e.kind, "producer": e.producer_event,
                                            "consumer": e.consumer_event,
                                            "certainty": e.certainty} for e in path]})
    if not witnesses or len({row["node"] for row in witnesses}) < 2:
        raise ValueError("no two-node exact registration/key/check witnesses")
    result = {"status": "healthy_observed_path_admitted", "case_id": "HDFS-14",
              "core_release": str(CORE), "config_sha256": sha(args.config.read_bytes()),
              "events_gzip_sha256": sha(packed), "events_raw_sha256": sha(raw),
              "junit_xml_sha256": sha(args.junit.read_bytes()),
              "junit": {"tests": 2, "failures": 0, "errors": 0, "skipped": 0},
              "door_count": len(doors), "target_count": len(targets),
              "graph": graph.summary(), "witnesses": witnesses}
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": result["status"], "witnesses": len(witnesses),
                      "nodes": sorted({row["node"] for row in witnesses})}, sort_keys=True))


if __name__ == "__main__":
    main()
