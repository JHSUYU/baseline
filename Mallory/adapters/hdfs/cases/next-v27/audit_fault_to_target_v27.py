"""Check one HDFS-11 NN fault to DN target with fa5f event-time witnesses."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from Mallory.core import graph as graph_module
from Mallory.core.graph import OccurrenceGraph


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    trial = args.trial.resolve()
    result = json.loads((trial / "result.json").read_text())
    with gzip.open(trial / "events.jsonl.gz", "rt") as source:
        events = tuple(json.loads(line) for line in source)
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED" and
               e.get("site") == "hdfs:nn-get-data-encryption-key"]
    if len(applied) != 1:
        raise ValueError(f"expected one exact NN fault, got {len(applied)}")
    fault = applied[0]
    points = (fault.get("site"), fault.get("node"), fault.get("epoch"),
              fault.get("door_ordinal"))
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             (e.get("site"), e.get("node"), e.get("epoch"),
              e.get("door_ordinal")) == points and e.get("seq", -1) < fault["seq"]]
    if len(doors) != 1:
        raise ValueError(f"expected one observed exact door, got {len(doors)}")
    door = doors[0]
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               e.get("seq", -1) > fault["seq"] and
               e.get("node", "").startswith("hdfs-cluster-") and
               "/dn" in e.get("node", "")]
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    witnesses = []
    for target in targets:
        path = graph.event_path(door, target, require_edge=True)
        if path is None:
            continue
        edges = [asdict(edge) for edge in path]
        sources = {edge["source"] for edge in edges}
        kinds = [edge["kind"] for edge in edges]
        witnesses.append({"target_id": target["id"], "target_node": target["node"],
                          "target_thread_id": target.get("thread_id"),
                          "edge_kinds": kinds, "edges": edges,
                          "source_occurrences": sorted(sources)})
    output = {
        "schema_version": 1,
        "case_id": "HDFS-11",
        "trial": str(trial),
        "result_sha256": hashlib.sha256((trial / "result.json").read_bytes()).hexdigest(),
        "events_gzip_sha256": hashlib.sha256((trial / "events.jsonl.gz").read_bytes()).hexdigest(),
        "graph_source": str(Path(graph_module.__file__).resolve()),
        "all_faults_effective": result["feedback"].get("all_faults_effective"),
        "fault_id": fault["id"],
        "door_id": door["id"],
        "fault_thread_id": fault.get("thread_id"),
        "target_check_count_after_fault": len(targets),
        "strict_path_witnesses": witnesses,
        "strict_path_proven": bool(witnesses),
        "graph_gaps": dict(graph.gaps),
    }
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"strict_path_proven": output["strict_path_proven"],
                      "witnesses": len(witnesses), "out": str(args.out)}, sort_keys=True))
    return 0 if witnesses else 2


if __name__ == "__main__":
    raise SystemExit(main())
