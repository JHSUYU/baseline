#!/usr/bin/env python3
"""Summarize passive HBASE-32 upstream probes without claiming causal edges."""

import base64
import collections
import json
import re
import sys
from pathlib import Path


KINDS = ("TARGET", "META_STATE_GET", "META_SCAN_NEXT", "MASTER_OPENED_RPC",
         "WAL_FLUSH_MARKER")
FIELDS = re.compile(r"([a-z_]+)=([^\s]+)")


def table_of(encoded: str) -> str:
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    return raw.split(b",", 1)[0].decode("utf-8", "replace")


def summarize(path: Path) -> dict:
    events = {kind: [] for kind in KINDS}
    woven = set()
    failed = []
    base_target = []
    guards = []
    b7 = []
    junit = None
    for line_number, line in enumerate(path.open(errors="replace"), 1):
        if "HBASE32U PROBE_WOVEN class=" in line:
            woven.add(line.split("class=", 1)[1].strip())
        if "HBASE32U PROBE_FAILED" in line:
            failed.append({"line": line_number, "text": line.strip()})
        if "HBASE32U " in line:
            fragment = line.split("HBASE32U ", 1)[1]
            kind = fragment.split(" ", 1)[0]
            if kind in events:
                record = dict(FIELDS.findall(fragment))
                record["line"] = line_number
                events[kind].append(record)
        if "HBASE32 TARGET_ENTER" in line:
            base_target.append({"line": line_number, **dict(FIELDS.findall(line))})
        if "HBASE32 TARGET_GUARD" in line:
            guards.append({"line": line_number, **dict(FIELDS.findall(line))})
        if "HBASE32 TARGET_B7_RETHROW" in line:
            b7.append({"line": line_number, **dict(FIELDS.findall(line))})
        if "HBASE32 JUNIT found=" in line:
            match = re.search(r"found=(\d+) succeeded=(\d+) failed=(\d+)", line)
            if match:
                junit = {"found": int(match[1]), "succeeded": int(match[2]),
                         "failed": int(match[3])}

    table = "testLotsOfRegionRepli2"
    subset = {kind: [e for e in records
                     if table_of(e["raw_primary_region"]) == table]
              for kind, records in events.items()}
    same_target_meta_gets = []
    for event in subset["META_STATE_GET"]:
        if any(guard["line"] < event["line"]
               and guard.get("raw_primary_region") == event["raw_primary_region"]
               and guard.get("replica_id") == event["replica"]
               and guard.get("target_ordinal") == event["target_ordinal"]
               for guard in guards):
            same_target_meta_gets.append(event)

    return {
        "source_log": str(path),
        "probe_woven_classes": sorted(woven),
        "probe_failures": failed,
        "original_junit": junit,
        "base_target_enters": len(base_target),
        "upstream_target_enters": len(events["TARGET"]),
        "target_enters_agree": len(base_target) == len(events["TARGET"]),
        "table2_event_counts": {kind: len(records) for kind, records in subset.items()},
        "table2_flush_rpc_wal_markers": sum(e.get("from_flush_rpc") == "true"
                                             for e in subset["WAL_FLUSH_MARKER"]),
        "table2_wal_actions": dict(collections.Counter(
            e.get("action") for e in subset["WAL_FLUSH_MARKER"])),
        "table2_meta_gets_after_same_target_guard": len(same_target_meta_gets),
        "examples": {kind: records[:3] for kind, records in subset.items()},
    }


if __name__ == "__main__":
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2, sort_keys=True))
