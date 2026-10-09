#!/usr/bin/env python3
"""Audit exact postfault Result-token paths in the bounded HBASE-35 pilot."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import Mallory.core.graph as graph_module
from Mallory.core.graph import OccurrenceGraph


TARGET = ("org.apache.hadoop.hbase.util.HBaseFsck$3#visit"
          "(Lorg/apache/hadoop/hbase/client/Result;)Z@2715:branch:10")
DOOR = ("org.apache.hadoop.hbase.client.ScannerCallable#openScanner()"
        "Lorg/apache/hadoop/hbase/shaded/protobuf/generated/ClientProtos$ScanResponse;@365:door:1")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require("fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
            in str(Path(graph_module.__file__).resolve()), "wrong core release")
    root = args.campaign.resolve()
    result = json.loads((root / "result.json").read_text())
    audit = json.loads((root / "offline-causal-audit.json").read_text())
    require(result["case_id"] == audit["case_id"] == "HBASE-35", "case changed")
    require(result["status"] == "budget_exhausted" and result["fault_trials_completed"] == 3,
            "unexpected pilot budget")
    require(audit["campaign_result_sha256"] == digest(root / "result.json") and
            audit["report_gate_passed"] and audit["require_event_time_paths"] and
            audit["reject_coarse_roots"], "fixed-core audit failed")
    require(result["exact_exception_trials"] == 0, "selected exception needs independent review")
    trials = []
    for number in (1, 2, 3):
        directory = root / "trials" / f"r{number:04d}"
        trial = json.loads((directory / "result.json").read_text())
        plan = json.loads((directory / "plan.json").read_text())
        require(len(plan["faults"]) == 1 and
                plan["faults"][0]["point"]["site"] == DOOR and
                plan["faults"][0]["exception_class"] == "java.io.IOException",
                f"wrong planned fault r{number:04d}")
        require(trial["junit_validation"]["status"] == "passed" and
                trial["feedback"]["all_faults_matched"] and
                trial["feedback"]["all_faults_applied"] and
                trial["feedback"]["all_faults_effective"],
                f"fault or JUnit failed r{number:04d}")
        compressed = (directory / "events.jsonl.gz").read_bytes()
        raw = gzip.decompress(compressed)
        require(hashlib.sha256(raw).hexdigest() == trial["events_sha256"] and
                hashlib.sha256(compressed).hexdigest() ==
                trial["events_evidence"]["gzip_sha256"],
                f"trace hash mismatch r{number:04d}")
        events = tuple(json.loads(line) for line in raw.splitlines() if line)
        applied = [event for event in events if event.get("type") == "FAULT_APPLIED"]
        require(len(applied) == 1 and applied[0]["site"] == DOOR and
                applied[0]["fault_id"] == plan["faults"][0]["fault_id"] and
                applied[0]["node"] == "client" and
                isinstance(applied[0].get("thread_id"), int),
                f"applied identity mismatch r{number:04d}")
        checks = [event for event in events if event.get("type") == "TARGET_CHECK" and
                  event.get("site") == TARGET and event["seq"] > applied[0]["seq"]]
        require(checks and all(event["node"] == "client" for event in checks),
                f"no later named selected check r{number:04d}")
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        witnesses = []
        for check in checks:
            path = graph.event_path(applied[0], check, require_edge=True)
            if path is None:
                continue
            require(all(edge.certainty == "observed" for edge in path),
                    f"candidate edge r{number:04d}")
            witnesses.append({
                "target_check_id": check["id"], "target_check_seq": check["seq"],
                "target_context": check.get("context"),
                "edges": [{"kind": edge.kind, "producer_event": edge.producer_event,
                           "consumer_event": edge.consumer_event} for edge in path],
            })
        trials.append({
            "trial_id": number,
            "plan_sha256": digest(directory / "plan.json"),
            "result_sha256": digest(directory / "result.json"),
            "events_gzip_sha256": digest(directory / "events.jsonl.gz"),
            "events_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "fault_applied_id": applied[0]["id"],
            "fault_applied_seq": applied[0]["seq"],
            "fault_node": applied[0]["node"],
            "fault_epoch": applied[0]["epoch"],
            "fault_occurrence": applied[0]["occurrence"],
            "fault_thread_id": applied[0]["thread_id"],
            "fault_context": applied[0].get("context"),
            "later_named_check_ids": [event["id"] for event in checks],
            "strict_event_time_witnesses": witnesses,
        })
    count = sum(bool(row["strict_event_time_witnesses"]) for row in trials)
    require(count == 1, "bounded pilot path count changed")
    review = {
        "schema_version": 1, "case_id": "HBASE-35",
        "status": "bounded_pilot_partial_strict_path_no_full_admission",
        "campaign_result_sha256": digest(root / "result.json"),
        "campaign_audit_sha256": digest(root / "offline-causal-audit.json"),
        "fault_trials": 3, "strict_postfault_path_trials": count,
        "selected_exception_trials": 0, "trials": trials,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        require(json.loads(args.out.read_text()) == review, "stored pilot review differs")
    else:
        args.out.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"fault_trials": 3, "strict_postfault_path_trials": count,
                      "review_sha256": digest(args.out)}, sort_keys=True))


if __name__ == "__main__":
    main()
