#!/usr/bin/env python3
"""Independently replay the strict SOLR-40 watch-read candidate.

The unchanged original cluster test runs afresh each time. ZooKeeper's retained
transaction log is inspected after shutdown to distinguish a persisted alias
from a failed alias creation request.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from feedback import (atomic_json, checked_target_identity, events,
                      strict_sequence, target_after, target_relations)


CASE = Path(__file__).resolve().parents[1]
SOURCE_TRIAL = CASE / "evidence/campaign-v4/trial-018/trial.json"
OUTPUT = CASE / "evidence/candidate-solr40-v4"
ALIAS_PATH = b"/solr/aliases.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persisted_alias(scratch: Path) -> tuple[bool | None, list[dict]]:
    """Read the path and length-prefixed alias JSON in the ZK txn log."""
    records = []
    logs = sorted(scratch.rglob("version-2/log.*"))
    for log in logs:
        data = log.read_bytes()
        cursor = 0
        while (index := data.find(ALIAS_PATH, cursor)) >= 0:
            cursor = index + len(ALIAS_PATH)
            if cursor + 4 > len(data):
                continue
            size = int.from_bytes(data[cursor:cursor + 4], "big")
            if not 0 < size < 65536 or cursor + 4 + size > len(data):
                continue
            try:
                payload = json.loads(data[cursor + 4:cursor + 4 + size])
            except (ValueError, UnicodeDecodeError):
                continue
            records.append({
                "log": str(log.relative_to(scratch)),
                "log_sha256": digest(log), "offset": index,
                "collection": payload.get("collection", {}).get("myalias"),
                "router_name": payload.get("collection_metadata", {})
                                      .get("myalias", {}).get("router.name"),
            })
    if not logs:
        return None, records  # JUnit normally removes healthy scratch on success.
    return any(record["collection"] and record["router_name"] == "time"
               for record in records), records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.count <= 10:
        parser.error("count must be between 1 and 10")
    source = json.loads(SOURCE_TRIAL.read_text())
    plan = source["plan"]
    if not source["strict"] or not source["target_exception"]["SOLR-40"]:
        raise RuntimeError("Source trial is not the strict SOLR-40 candidate")
    if len(plan) != 1 or not plan[0].startswith("GET_DATA|/aliases.json|1|"):
        raise RuntimeError("Source plan is not the expected watch-read fault")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = OUTPUT / "summary.json"
    records = json.loads(summary.read_text())["runs"] if summary.exists() else []
    for receipt in records:
        run = OUTPUT / f"replay-{receipt['number']:03d}"
        persisted, parsed = persisted_alias(run / "scratch")
        if receipt["persisted_alias_in_zk_txlog"] != persisted:
            receipt["persisted_alias_in_zk_txlog"] = persisted
            receipt["alias_txn_records"] = parsed
            atomic_json(run / "replay-receipt.json", receipt)
    atomic_json(summary, {"source_trial": 18, "runs": records})
    starting_number = len(records) + 1
    for number in range(starting_number, starting_number + args.count):
        run = OUTPUT / f"replay-{number:03d}"
        subprocess.run([sys.executable, str(CASE / "probe/run.py"), str(run),
                        "--coverage", "--faults", ";".join(plan), "--timeout", "360"],
                       check=False)
        trace = events(run / "events.tsv")
        manifest = json.loads((run / "manifest.json").read_text())
        applied = [event for event in trace if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        final = max((event["seq"] for event in applied), default=-1)
        reached, exception = target_after(trace, final)
        alias_persisted, alias_records = persisted_alias(run / "scratch")
        log = (run / "junit.log").read_text(errors="replace")
        receipt = {
            "number": number, "source_trial": 18, "plan": plan,
            "strict": strict_sequence(plan, trace) and checked_target_identity(trace),
            "postfault_target": reached["SOLR-40"],
            "target_exception": exception["SOLR-40"],
            "target_relations": target_relations(trace, final)["SOLR-40"],
            "persisted_alias_in_zk_txlog": alias_persisted,
            "alias_txn_records": alias_records,
            "create_alias_http_success": any(
                "action=CREATEALIAS" in line and "status=0" in line
                for line in log.splitlines()),
            "exact_failure_in_junit": "Routed alias myalias appears to have been removed" in log,
            "junit_exit": manifest["exit_code"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "build_receipt_sha256": manifest["build_receipt_sha256"],
            "source_commit": manifest["source_commit"],
            "original_test_class_sha256": manifest["original_test_class_sha256"],
            "actor_probe_class_sha256": manifest["actor_probe_class_sha256"],
            "events_sha256": digest(run / "events.tsv"),
            "junit_log_sha256": digest(run / "junit.log"),
            "jacoco_sha256": digest(run / "jacoco.exec"),
        }
        atomic_json(run / "replay-receipt.json", receipt)
        records.append(receipt)
        atomic_json(summary, {"source_trial": 18, "runs": records})
        print(json.dumps({"replay": number, "strict": receipt["strict"],
                          "postfault_target": receipt["postfault_target"],
                          "target_exception": receipt["target_exception"],
                          "persisted_alias_in_zk_txlog": alias_persisted,
                          "junit_exit": receipt["junit_exit"]}), flush=True)


if __name__ == "__main__":
    main()
