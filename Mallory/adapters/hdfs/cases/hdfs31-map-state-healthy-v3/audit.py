#!/usr/bin/env python3
"""Read-only event audit after one HDFS-31 map-state healthy JUnit."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys


def main() -> None:
    root = Path(sys.argv[1])
    result = json.loads((root / "trials/r0000/result.json").read_text())
    with gzip.open(root / "trials/r0000/events.jsonl.gz", "rt") as handle:
        events = [json.loads(line) for line in handle]
    targets = [e for e in events if e.get("type") == "TARGET_CHECK"
               and "DataNode#getBPOSForBlock" in e.get("site", "")
               and e.get("node") == "hdfs-cluster-1/dn0"]
    get_regions = [e for e in events if e.get("type") == "REGION_ENTER"
                   and "BlockPoolManager#get" in e.get("site", "")]
    reads = [e for e in events if e.get("type") == "STATE_READ"
             and "BlockPoolManager#get" in e.get("site", "")]
    writes = [e for e in events if e.get("type") == "STATE_WRITE"
              and "BlockPoolManager#addBlockPool" in e.get("site", "")]
    scoped_reads = [(r, t) for r in reads for t in targets
                    if r.get("seq", -1) < t.get("seq", -1)
                    and r.get("node") == t.get("node")
                    and r.get("thread_id") == t.get("thread_id")
                    and any(g.get("occurrence") == r.get("occurrence")
                            and g.get("parent_id") == t.get("occurrence")
                            and g.get("seq", -1) < r.get("seq", -1)
                            for g in get_regions)]
    pairs = [(w, r) for w in writes for r, _ in scoped_reads
             if w.get("seq", -1) < r.get("seq", -1)
             and all(w.get(k) == r.get(k) for k in ("object", "key", "version"))]
    junit = result.get("junit_validation", {})
    passed = (junit.get("tests"), junit.get("failures"), junit.get("errors")) == (1, 0, 0)
    report = {
        "case_id": "HDFS-31", "healthy_junit_passed": passed,
        "named_target_events": len(targets), "map_reads": len(reads),
        "scoped_pretarget_map_reads": len(scoped_reads),
        "map_add_writes": len(writes), "matching_sampled_state_pairs": len(pairs),
        "graph_candidate_state_edges": result.get("feedback", {}).get("graph", {})
        .get("candidate_edges_by_kind", {}).get("state", 0),
        "target_exception_candidate": result.get("feedback", {}).get(
            "target_exception_candidate", False),
        "map_keys_at_read": sorted({str(r.get("key")) for r in reads}),
        "map_objects_at_read": sorted({str(r.get("object")) for r in reads}),
        "status": "healthy_map_evidence" if passed and targets and scoped_reads and pairs
        else "insufficient_healthy_map_evidence",
    }
    print(json.dumps(report, sort_keys=True))
    if report["status"] != "healthy_map_evidence":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
