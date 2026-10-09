#!/usr/bin/env python3
"""Validate same-run meta role and exact raw actor after a role-aware JUnit."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "work-upstream"))
from campaign import fault_events, parse_log, strict  # noqa: E402


def raw_lines(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", errors="replace") as stream:
        yield from enumerate(stream, 1)


def fields(line: str) -> dict:
    return dict(re.findall(r"([a-z_]+)=([^\s]+)", line))


def audit(log: Path, plan: list[str]) -> dict:
    trace = parse_log(log)
    applied = fault_events(trace)
    matched = strict(trace, plan)
    meta_events = []
    selected_events = []
    for number, line in raw_lines(log):
        if "HBASE32ROLE META_LOCATION " in line:
            meta_events.append({"line": number, **fields(line)})
        elif "HBASE32ROLE SELECTED_ACTOR " in line:
            selected_events.append({"line": number, **fields(line)})
    reasons = []
    first = applied[0] if applied else None
    second = applied[1] if len(applied) > 1 else None
    if not matched:
        reasons.append("fault_plan_not_strictly_applied")
    if first is None or second is None:
        reasons.append("missing_fault_event")
        return {"identity_valid": False, "reasons": reasons, "junit": trace["junit"]}
    latest_meta = next((event for event in reversed(meta_events)
                        if event["line"] < first["line"]), None)
    if (latest_meta is None or latest_meta.get("state") != "OPEN"
            or latest_meta.get("server") != first.get("server")):
        reasons.append("f1_not_current_successful_meta_open_host")
    if (first.get("meta_host") != first.get("server")
            or latest_meta is None
            or first.get("meta_host_generation") != latest_meta.get("generation")):
        reasons.append("f1_role_generation_mismatch")
    selected = next((event for event in selected_events
                     if event["line"] < first["line"]
                     and event.get("raw_primary_region") == first.get("raw_primary_region")
                     and event.get("raw_secondary_region") == first.get("raw_secondary_region")
                     and event.get("server") == first.get("server")), None)
    replica = first.get("replica_id")
    if (selected is None or selected.get("replica_id") != replica
            or not replica or not replica.isdigit() or int(replica) <= 0):
        reasons.append("f1_selected_actor_receipt_missing")
    if (first.get("raw_primary_region") != second.get("raw_primary_region")
            or first.get("raw_secondary_region") != second.get("raw_secondary_region")
            or first.get("stable_region") != second.get("stable_region")
            or replica != second.get("replica_id")
            or second.get("selected_actor") != "true"
            or second.get("target_ordinal") != "1"):
        reasons.append("f2_actor_or_target_mismatch")
    target = next((event for event in trace["TARGET"]
                   if first["line"] < event["line"] < second["line"]
                   and event.get("raw_primary_region") == first.get("raw_primary_region")
                   and event.get("raw_secondary_region") == first.get("raw_secondary_region")
                   and event.get("replica") == replica
                   and event.get("target_ordinal") == "1"), None)
    if target is None:
        reasons.append("same_raw_secondary_target_missing")
    b7 = [event for event in trace["TARGET_B7_RETHROW"]
          if matched and event["line"] > second["line"]
          and event.get("raw_primary_region") == first.get("raw_primary_region")
          and event.get("replica_id") == replica
          and event.get("target_ordinal") == "1"]
    if len(b7) != 1:
        reasons.append("postfault_same_actor_b7_missing_or_duplicate")
    return {"identity_valid": not reasons, "reasons": reasons,
            "strict_fault_plan": matched, "faults_applied": len(applied),
            "latest_meta_before_f1": latest_meta, "selected_actor": selected,
            "raw_primary_region": first.get("raw_primary_region"),
            "raw_secondary_region": first.get("raw_secondary_region"),
            "replica_id": replica,
            "target": target, "same_actor_b7": len(b7),
            "junit": trace["junit"], "elapsed_seconds": trace["elapsed_seconds"],
            "fuzz_budget_admitted": False}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: audit_role_run.py LOG OUTPUT.json")
    plan = json.loads((HERE / "role-plan.json").read_text())["plan"]
    result = audit(Path(sys.argv[1]), plan)
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"identity_valid": result["identity_valid"],
                      "reasons": result["reasons"], "junit": result["junit"]}))
