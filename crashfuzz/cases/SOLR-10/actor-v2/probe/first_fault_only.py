#!/usr/bin/env python3
"""SOLR-40 negative control: trial-481's first selector without alias-read fault.

Run the unchanged embedded-cluster JUnit with the frozen V4 actor agent. This
control does not alter the terminal campaign state or replay its trials.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from feedback import (atomic_json, checked_target_identity, events, fields,
                      runtime_actor, strict_sequence)
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "evidence/campaign-v4/state.json"
SOURCE = CASE / "evidence/lowlevel-single-retry-v10/build-receipt.json"
OUT = CASE / "evidence/first-fault-only-v10"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(count: int) -> None:
    source = json.loads(SOURCE.read_text())
    selector = source["first_fault_selector"]
    frozen = source["frozen_campaign_state_sha256"]
    if sha(STATE) != frozen or json.loads(STATE.read_text())["inflight"] is not None:
        raise RuntimeError("Frozen campaign state changed")
    if sha(CASE / "build-receipt.json") != source["original_build_receipt_sha256"]:
        raise RuntimeError("Actor-agent build receipt changed")
    if not selector.startswith("EXISTS_WATCH|/collections/myalias__TRA__2017-10-23/state.json|10|"):
        raise RuntimeError("Unexpected source selector")
    summary = OUT / "summary.json"
    rows = json.loads(summary.read_text())["runs"] if summary.exists() else []
    for number in range(len(rows) + 1, len(rows) + count + 1):
        if sha(STATE) != frozen or shutil.disk_usage(CASE).free < 10.5 * 1024 ** 3:
            raise RuntimeError("Frozen state changed or disk guard tripped")
        java_count = sum(line == "java" for line in subprocess.check_output(
            ["ps", "-eo", "comm="], text=True).splitlines())
        if java_count >= 5:
            raise RuntimeError(f"No isolated JVM slot ({java_count} Java processes)")
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CASE / "probe/run.py"),
                               str(output), "--coverage", "--faults", selector,
                               "--timeout", "360"], capture_output=True,
                              text=True, check=False)
        trace = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        faults = [event for event in trace if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        first = faults[0] if faults else None
        actor = runtime_actor(first) if first else None
        target = [event for event in trace if event["kind"] == "TARGET_CHECK" and
                  len(event["parts"]) > 1 and event["parts"][1] == "SOLR-40" and
                  first and event["seq"] > first["seq"] and runtime_actor(event) == actor]
        throws = [event for event in trace if event["kind"] == "TARGET_EXCEPTION" and
                  event["parts"] and event["parts"][0] == "SOLR-40" and
                  first and event["seq"] > first["seq"] and runtime_actor(event) == actor]
        persisted, records = persisted_alias(output / "scratch")
        receipt = {
            "number": number, "model": "same F0 collection-state selector only",
            "selector": selector, "strict": strict_sequence([selector], trace) and
                      checked_target_identity(trace),
            "fault_count": len(faults), "fault_actor": actor,
            "alias_underlying_fault_count": sum(event["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"
                                                for event in trace),
            "same_reader_target_count": len(target),
            "same_reader_target_values": [event["parts"][0] for event in target],
            "same_reader_throw_count": len(throws),
            "junit_exit": manifest["exit_code"], "runner_exit": proc.returncode,
            "elapsed_seconds": manifest["elapsed_seconds"],
            "alias_create_http_success": any("action=CREATEALIAS" in line and
                                             "status=0" in line for line in
                                             (output / "junit.log").read_text(errors="replace").splitlines()),
            "persisted_alias_in_zk_txlog": persisted, "alias_txn_records": records,
            "frozen_campaign_state_sha256": frozen,
            "source_build_receipt_sha256": sha(SOURCE),
            "original_build_receipt_sha256": sha(CASE / "build-receipt.json"),
            "original_test_class_sha256": manifest["original_test_class_sha256"],
            "events_sha256": sha(output / "events.tsv"),
            "junit_log_sha256": sha(output / "junit.log"),
            "jacoco_sha256": sha(output / "jacoco.exec"),
        }
        atomic_json(output / "receipt.json", receipt)
        rows.append(receipt)
        atomic_json(summary, {"model": receipt["model"], "runs": rows})
        print(json.dumps({"trial": number, "strict": receipt["strict"],
                          "same_reader_target": len(target), "same_reader_throw": len(throws),
                          "junit_exit": manifest["exit_code"]}), flush=True)
        if sha(STATE) != frozen:
            raise RuntimeError("Campaign checkpoint changed during negative control")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 5:
        parser.error("count must be 1..5")
    main(args.count)
