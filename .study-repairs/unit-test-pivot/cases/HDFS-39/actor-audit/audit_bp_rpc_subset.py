#!/usr/bin/env python3
"""Identify archived HDFS-39 trials with raw DN heartbeat-to-NN actor proof.

This is a partial audit, not a completed case. Client append and edit-log
faults lacking an independently observed RPC/storage identity are excluded.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re


CASE = Path(__file__).resolve().parent.parent
BASE = CASE / "independent-coverage-io"
CAMPAIGN = BASE / "campaign"
HEARTBEAT = re.compile(r" heartbeating to localhost/(?:127\.0\.0\.1|[0-9.]+):(\d+)$")
HANDLER = re.compile(r"^IPC Server handler \d+ on default port (\d+)$")
TARGET = "/testMultipleAppend/foo"
BLOCK = 1073741825
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testMultipleAppends"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def audit_trial(number: int) -> tuple[str, dict | None]:
    directory = CAMPAIGN / f"trial-{number:02d}"
    result_path = directory / "trial-result.json"
    manifest_path = directory / "manifest.json"
    trace_path = directory / "trace/runtime_trace.jsonl"
    result = json.loads(result_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    events = run_events(trace_path)
    plan = result["sequence"]
    applied = [event for event in events if event.get("event") == "FAULT_APPLIED"]
    matched = [event for event in events if event.get("event") == "FAULT_MATCHED"]
    if (manifest["test"] != TEST or result["requested_faults"] != len(plan)
            or len(applied) != len(plan) or len(matched) != len(plan)
            or not result["strict_injection"]):
        raise AssertionError(f"trial {number}: raw fault sequence differs")
    keys = ("marker", "api", "endpoint", "ordinal", "exception")
    for expected, event in zip(plan, applied):
        if any(expected[key] != event.get(key) for key in keys):
            raise AssertionError(f"trial {number}: plan/event mismatch")
    if any(applied[i]["seq"] >= applied[i + 1]["seq"] for i in range(len(applied) - 1)):
        raise AssertionError(f"trial {number}: fault order differs")
    last = applied[-1]["seq"]
    selected = [event for event in events
                if event.get("event") == "TARGET_GUARD" and event["seq"] > last
                and event.get("path") == TARGET and event.get("blockId") == BLOCK]
    if not selected:
        raise AssertionError(f"trial {number}: selected target lost despite ledger")
    handler_matches = [HANDLER.search(event.get("thread", "")) for event in selected]
    target_ports = {match.group(1) for match in handler_matches if match}
    if len(target_ports) != 1 or not all(handler_matches):
        return "target_actor_unproven", None
    port = next(iter(target_ports))
    if not all((match := HEARTBEAT.search(event.get("thread", "")))
               and match.group(1) == port for event in applied):
        return "fault_actor_unproven", None
    target_exceptions = [event for event in events
                         if event.get("event") == "TARGET_EXCEPTION"
                         and event["seq"] > last and event.get("path") == TARGET
                         and event.get("blockId") == BLOCK]
    return "actor_joined", {
        "trial": number, "faults": len(plan), "nn_rpc_port": port,
        "selected_guards_after_fault": len(selected),
        "selected_exceptions_after_fault": len(target_exceptions),
        "selected_exception_types": sorted(set(event.get("type", "")
                                               for event in target_exceptions)),
        "junit_exit": manifest["exit"], "junit_seconds": manifest["elapsed_seconds"],
        "trace_sha256": sha(trace_path), "manifest_sha256": sha(manifest_path),
        "trial_result_sha256": sha(result_path),
    }


def audit() -> dict:
    healthy = {}
    for name in ("original", "probed", "probed-v2"):
        path = BASE / f"healthy/{name}/manifest.json"
        manifest = json.loads(path.read_text())
        if manifest["test"] != TEST or manifest["exit"] != 0:
            raise AssertionError(f"healthy {name} did not pass original JUnit")
        healthy[name] = {"elapsed_seconds": manifest["elapsed_seconds"],
                         "manifest_sha256": sha(path)}
    ledger = list(csv.DictReader((CAMPAIGN / "trial-ledger.csv").open()))
    if len(ledger) != 205 or len({int(row["number"]) for row in ledger}) != 205:
        raise AssertionError("historical 205-attempt ledger incomplete")
    historical_effective = [int(row["number"]) for row in ledger
                            if row["strict_injection"] == "True"
                            and row["target_guard_after_last_fault"] == "True"]
    reasons = Counter()
    admitted = []
    for number in historical_effective:
        reason, receipt = audit_trial(number)
        reasons[reason] += 1
        if receipt:
            admitted.append(receipt)
    if len(historical_effective) != 128 or len(admitted) != 52:
        raise AssertionError(f"unexpected actor subset: {len(historical_effective)}/{len(admitted)}")
    return {"case_id": "HDFS-39", "status": "partial_actor_audit_budget_unmet",
            "original_junit": TEST, "healthy": healthy,
            "historical_attempts": len(ledger),
            "historical_target_retaining": len(historical_effective),
            "actor_joined_bp_only": len(admitted),
            "excluded_target_retaining": len(historical_effective) - len(admitted),
            "reasons": dict(reasons), "admitted": admitted,
            "conclusion": "Only 52 historical trials prove every fault's raw heartbeat RPC port equals the selected NameNode handler port after the last fault. The 80-effective base budget remains unmet; unbound client/edit-log trials cannot be imported."
            }


if __name__ == "__main__":
    output = CASE / "actor-audit/bp-rpc-subset.json"
    output.write_text(json.dumps(audit(), indent=2, sort_keys=True) + "\n")
    print(output)
