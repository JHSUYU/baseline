#!/usr/bin/env python3
"""Summarize observer-only ServerStateNode lock events for a diagnostic run."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
EVENT = re.compile(
    r"HBASE32LOCK seq=(\d+) utc=([^ ]+) phase=(BEFORE_LOCK|ACQUIRED|RELEASED) "
    r"thread_id=(\d+) thread=(.*?) mode=(READ|WRITE) node_identity=([^ ]+) "
    r"server=([^ ]+) lock_identity=([^ ]+)")


def analyze(log: Path, summary: Path) -> dict:
    run = json.loads(summary.read_text())
    selected = run.get("selected_master_report_server")
    if selected is None:
        selected = next((x["server"] for x in run.get("applied_faults", [])
                         if x.get("selector", "").startswith("MASTER_OPENED_RPC~")), None)
    held = defaultdict(list)
    writes = []
    events = 0
    anomalies = []
    for line_number, line in enumerate(log.open(errors="replace"), 1):
        m = EVENT.search(line)
        if not m:
            continue
        seq, utc, phase, tid, thread, mode, node, server, lock = m.groups()
        events += 1
        key = (tid, node, lock)
        if phase == "ACQUIRED":
            held[key].append({"seq": int(seq), "line": line_number, "utc": utc,
                              "thread": thread, "mode": mode, "node_identity": node,
                              "server": server, "lock_identity": lock})
        elif phase == "RELEASED":
            if held[key]:
                held[key].pop()
            else:
                anomalies.append({"line": line_number, "reason": "release_without_acquire",
                                  "thread": thread, "server": server})
        elif (phase == "BEFORE_LOCK" and mode == "WRITE"
              and "RegionServerTracker" in thread and server == selected):
            readers = [event for stack in held.values() for event in stack
                       if event["mode"] == "READ" and event["node_identity"] == node]
            writes.append({"seq": int(seq), "line": line_number, "utc": utc,
                           "tracker_thread": thread, "server": server,
                           "node_identity": node, "active_readers": readers})
    result = {
        "log": str(log), "summary": str(summary), "event_count": events,
        "selected_server": selected,
        "selected_server_carried_meta_at_fault": run.get(
            "selected_server_carried_meta_at_fault"),
        "first_scp": run.get("first_scp"),
        "first_shutdown_hook": run.get("first_shutdown_hook"),
        "tracker_write_attempts_on_selected_server": writes,
        "remaining_held_locks_at_process_end": sum(map(len, held.values())),
        "event_anomalies": anomalies,
        "fuzz_budget_admitted": False,
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: analyze_lock_identity.py 2|3|4")
    suffix = f"diag-fault-{int(sys.argv[1])}-s203"
    result = analyze(HERE / "logs" / f"{suffix}.log",
                     HERE / "logs" / f"{suffix}.summary.json")
    out = HERE / "logs" / f"{suffix}.lock-analysis.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"selected_server": result["selected_server"],
                      "meta": result["selected_server_carried_meta_at_fault"],
                      "write_attempts": len(result["tracker_write_attempts_on_selected_server"]),
                      "active_readers_at_first_write": len(
                          result["tracker_write_attempts_on_selected_server"][0]
                          ["active_readers"]) if result[
                              "tracker_write_attempts_on_selected_server"] else None,
                      "event_anomalies": len(result["event_anomalies"])},
                     sort_keys=True))
