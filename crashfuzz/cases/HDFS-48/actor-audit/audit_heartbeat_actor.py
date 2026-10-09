#!/usr/bin/env python3
"""Rejoin HDFS-48's archived heartbeat faults to the selected NN RPC actor.

The old selector used a normalized thread name. This audit admits only the
subset whose *raw* BPServiceActor thread contains the destination RPC port,
and whose selected guard ran on that same server port after the last fault.
Other historical trials remain unverified and are excluded.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
LEDGER = CASE / "independent/trial-ledger.csv"
HEALTHY = CASE / "independent/evidence/instrumented-healthy-01"
NN_PORT = re.compile(r"NameNode RPC up at: .*:(\d+)\.")
HEARTBEAT_PORT = re.compile(r" heartbeating to localhost/(?:127\.0\.0\.1|[0-9.]+):(\d+)$")
HANDLER_PORT = re.compile(r"^IPC Server handler \d+ on default port (\d+)$")
TEST = "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots#testRenameUndo_1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(path: Path) -> list[list[str]]:
    return [line.split("\t") for line in path.read_text().splitlines() if line.strip()]


def nn_port(log: Path) -> str:
    found = NN_PORT.findall(log.read_text(errors="replace"))
    if len(found) != 1:
        raise AssertionError(f"expected one NameNode RPC endpoint in {log}: {found}")
    return found[0]


def selected_guards(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if len(row) >= 9 and row[1] == "TARGET_GUARD"
            and row[3:5] == ["/dir1", "foo"]]


def inspect_healthy() -> dict:
    manifest = json.loads((HEALTHY / "manifest.json").read_text())
    if manifest["cluster_test"] != TEST or manifest["returncode"] != 0:
        raise AssertionError("original instrumented healthy JUnit did not pass")
    rows = events(HEALTHY / "runtime_trace.tsv")
    port = nn_port(HEALTHY / "junit.log")
    guards = selected_guards(rows)
    if not guards or not all(HANDLER_PORT.search(row[2])
                              and HANDLER_PORT.search(row[2]).group(1) == port
                              for row in guards):
        raise AssertionError("healthy selected guard lacks the sole NN RPC actor")
    if any(row[1] == "FAULT_APPLIED" for row in rows):
        raise AssertionError("healthy seed unexpectedly injected a fault")
    return {"nn_rpc_port": port, "selected_guards": len(guards),
            "trace_sha256": digest(HEALTHY / "runtime_trace.tsv"),
            "manifest_sha256": digest(HEALTHY / "manifest.json")}


def inspect_trial(record: dict) -> dict:
    directory = CASE / record["run_dir"]
    manifest_path = directory / "manifest.json"
    trace_path = directory / "runtime_trace.tsv"
    log_path = directory / "junit.log"
    manifest = json.loads(manifest_path.read_text())
    if manifest["cluster_test"] != TEST:
        raise AssertionError(f"trial {record['trial']} changed original JUnit")
    if float(record["elapsed_seconds"]) != manifest["elapsed_seconds"]:
        raise AssertionError(f"trial {record['trial']} duration differs from raw manifest")
    plan = json.loads(record["plan"])
    if plan != manifest["plan"].split("|||"):
        raise AssertionError(f"trial {record['trial']} plan differs from raw manifest")
    rows = events(trace_path)
    applied = [row for row in rows if row[1] == "FAULT_APPLIED"]
    matched = [row for row in rows if row[1] == "FAULT_MATCHED"]
    port = nn_port(log_path)
    if len(applied) != len(plan) or len(matched) != len(plan):
        raise AssertionError(f"trial {record['trial']} incomplete fault sequence")
    for index, (point, event) in enumerate(zip(plan, applied)):
        site, normalized_thread, ordinal, fault = point.split("|")
        if (event[3:7] != [site, normalized_thread, ordinal, str(index)]
                or event[7] != fault):
            raise AssertionError(f"trial {record['trial']} raw fault mismatch")
        heart = HEARTBEAT_PORT.search(event[2])
        if not heart or heart.group(1) != port:
            raise AssertionError(f"trial {record['trial']} fault reached another actor")
    last_fault = int(applied[-1][0])
    guards = [row for row in selected_guards(rows) if int(row[0]) > last_fault]
    if not guards or not all(HANDLER_PORT.search(row[2])
                             and HANDLER_PORT.search(row[2]).group(1) == port
                             for row in guards):
        raise AssertionError(f"trial {record['trial']} target actor not retained")
    if any(row[1] == "TARGET_FALSE" and row[3:5] == ["/dir1", "foo"]
           and int(row[0]) > last_fault for row in rows):
        raise AssertionError(f"trial {record['trial']} has selected false branch")
    return {"trial": int(record["trial"]), "faults": len(plan),
            "nn_rpc_port": port, "post_fault_selected_guards": len(guards),
            "junit_returncode": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "trace_sha256": digest(trace_path),
            "manifest_sha256": digest(manifest_path),
            "junit_log_sha256": digest(log_path)}


def audit() -> dict:
    healthy = inspect_healthy()
    ledger = list(csv.DictReader(LEDGER.open()))
    if len(ledger) != 183 or len({row["trial"] for row in ledger}) != 183:
        raise AssertionError("historical 183-trial ledger is incomplete")
    historical_effective = [row for row in ledger
                            if row["exact_order_applied"] == "True"
                            and row["target_after_fault"] == "True"]
    admitted = [row for row in historical_effective
                if all("heartbeating to" in point
                       for point in json.loads(row["plan"]))]
    details = [inspect_trial(row) for row in admitted]
    if len({row["trial"] for row in details}) != len(details):
        raise AssertionError("duplicate actor-bound trial")
    return {"case_id": "HDFS-48", "original_junit": TEST,
            "healthy": healthy, "historical_attempts": len(ledger),
            "historical_target_retaining_trials": len(historical_effective),
            "actor_joined_heartbeat_trials": len(details),
            "unverified_historical_target_retaining_trials":
                len(historical_effective) - len(details),
            "admitted_trial_ids": [row["trial"] for row in details],
            "admitted_fault_depths": dict(Counter(row["faults"] for row in details)),
            "admitted_junit_returncodes":
                dict(Counter(row["junit_returncode"] for row in details)),
            "admitted_elapsed_seconds": round(sum(row["elapsed_seconds"]
                                                   for row in details), 3),
            "raw_trial_receipts": details,
            "inference": "The original JUnit starts one NameNode. Each admitted raw BPServiceActor fault names its RPC port, the same port logged by that NameNode and by the selected IPC handler after the final fault."
            }


if __name__ == "__main__":
    path = HERE / "heartbeat-actor-audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit(), indent=2, sort_keys=True) + "\n")
    print(path)
