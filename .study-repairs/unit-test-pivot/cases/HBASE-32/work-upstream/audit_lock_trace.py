#!/usr/bin/env python3
"""Audit trace-only ServerStateNode lock events in event-sequence order."""

from __future__ import annotations

from collections import defaultdict
import gzip
import json
from pathlib import Path
import re
import sys

EVENT = re.compile(
    r"HBASE32LOCK seq=(\d+) utc=([^ ]+) phase=(BEFORE_LOCK|ACQUIRED|RELEASED) "
    r"thread_id=(\d+) thread=(.*?) mode=(READ|WRITE) node_identity=([^ ]+) "
    r"server=([^ ]+) lock_identity=([^ ]+)")


def lines(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", errors="replace") as stream:
        yield from enumerate(stream, 1)


def audit(path: Path) -> dict:
    events = []
    shutdown = None
    for number, line in lines(path):
        if shutdown is None and "Shutdown hook starting" in line:
            shutdown = number
        match = EVENT.search(line)
        if match:
            seq, utc, phase, tid, thread, mode, node, server, lock = match.groups()
            events.append({"seq": int(seq), "line": number, "utc": utc,
                           "phase": phase, "thread_id": tid, "thread": thread,
                           "mode": mode, "node_identity": node, "server": server,
                           "lock_identity": lock})
    events.sort(key=lambda event: event["seq"])
    if len({event["seq"] for event in events}) != len(events):
        raise ValueError("Duplicate event sequence numbers")
    held = defaultdict(list)
    anomalies = []
    tracker_writes = []
    for event in events:
        key = (event["thread_id"], event["node_identity"], event["mode"])
        if event["phase"] == "ACQUIRED":
            held[key].append(event)
        elif event["phase"] == "RELEASED":
            if held[key]:
                held[key].pop()
            else:
                anomalies.append({"reason": "release_without_acquire", "event": event})
        elif (event["mode"] == "WRITE"
              and "RegionServerTracker" in event["thread"]):
            readers = [reader for (_, node, mode), stack in held.items()
                       if node == event["node_identity"] and mode == "READ"
                       for reader in stack]
            tracker_writes.append({"attempt": event, "active_readers": readers,
                                   "acquired_before_shutdown": any(
                                       next_event["seq"] > event["seq"]
                                       and next_event["mode"] == "WRITE"
                                       and next_event["node_identity"] == event["node_identity"]
                                       and next_event["phase"] == "ACQUIRED"
                                       and (shutdown is None or next_event["line"] < shutdown)
                                       for next_event in events)})
    return {"log": str(path), "event_count": len(events),
            "shutdown_hook_line": shutdown, "tracker_write_attempts": tracker_writes,
            "anomalies": anomalies}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: audit_lock_trace.py LOG OUTPUT.json")
    result = audit(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"events": result["event_count"],
                      "tracker_writes": len(result["tracker_write_attempts"]),
                      "anomalies": len(result["anomalies"])}))
