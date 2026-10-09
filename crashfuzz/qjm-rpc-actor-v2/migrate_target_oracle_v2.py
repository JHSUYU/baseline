#!/usr/bin/env python3
"""Correct derived candidate labels while retaining every original raw run."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from build_offline import HERE
from campaign_v2 import atom, events, evidence_errors
from strict_receipt import audit


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("09", "10"), required=True)
    args = parser.parse_args()
    root = HERE / "evidence" / f"HDFS-{args.case}"
    campaign = root / "campaign-v2"
    if not (campaign / "PAUSE").exists():
        parser.error("pause the campaign at a complete JUnit boundary first")
    receipt_path = campaign / "target-oracle-v2-migration.json"
    if receipt_path.exists():
        parser.error("migration receipt already exists")
    with (campaign / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checkpoint = campaign / "checkpoint.json"
        before = checkpoint.read_bytes()
        state = json.loads(before)
        if state["current"] is not None or state["status"] != "running":
            parser.error("checkpoint is not paused between complete trials")
        calibration = json.loads((root / "healthy-calibration.json").read_text())
        changes = []
        replacements = []
        for row in state["completed"]:
            path = root / row["run"] / "trial-result.json"
            original = path.read_bytes()
            raw = json.loads(original)
            if raw != row:
                raise RuntimeError(f"checkpoint/raw derived row differs: {row['run']}")
            manifest = json.loads((root / row["run"] / "manifest.json").read_text())
            evidence = evidence_errors(root / row["run"], args.case,
                                       manifest, calibration)
            if evidence:
                raise RuntimeError(f"{row['run']}: {evidence}")
            trace = events(root / row["run"] / "runtime_trace.jsonl")
            plan_path = campaign / "plans" / (row["run"] + ".tsv")
            plan = [line.split("\t") for line in plan_path.read_text().splitlines()
                    if line.strip()]
            exact = audit(trace, plan, args.case, row["target_actor"])
            if exact != row["receipt"]:
                raise RuntimeError(f"{row['run']}: actor/target raw receipt differs")
            expected = bool(exact["pass"] and exact["post_fault_target_throws"])
            if row["candidate"] == expected:
                continue
            if row["candidate"] or row["bug_mark"] != "none":
                raise RuntimeError(f"unexpected prior candidate classification: {row['run']}")
            row["candidate"] = expected
            row["bug_mark"] = "candidate" if expected else "none"
            updated = canonical(row)
            changes.append({"run": row["run"], "raw_trace_sha256":
                            manifest["trace_sha256"], "manifest_sha256":
                            sha((root / row["run"] / "manifest.json").read_bytes()),
                            "derived_before_sha256": sha(original),
                            "derived_after_sha256": sha(updated),
                            "junit_returncode": manifest["returncode"],
                            "post_fault_target_throws":
                            exact["post_fault_target_throws"]})
            replacements.append((path, updated))
        state["target_oracle_rule"] = "postfault_target_throw_independent_of_junit_exit"
        after = canonical(state)
        receipt = {"case": f"HDFS-{args.case}",
                   "rule_before": "postfault_target_throw_and_nonzero_junit_exit",
                   "rule_after": state["target_oracle_rule"],
                   "raw_trace_and_manifest_modified": False,
                   "completed_trials_preserved": len(state["completed"]),
                   "effective_trials_preserved":
                   sum(row["effective"] for row in state["completed"]),
                   "checkpoint_before_sha256": sha(before),
                   "checkpoint_after_sha256": sha(after),
                   "changes": changes}
        pending = receipt_path.with_suffix(".pending.json")
        atom(pending, receipt)
        for path, value in replacements:
            temp = path.with_name(path.name + f".oracle-v2.tmp.{os.getpid()}")
            temp.write_bytes(value)
            os.replace(temp, path)
        temp = checkpoint.with_name(checkpoint.name + f".oracle-v2.tmp.{os.getpid()}")
        temp.write_bytes(after)
        os.replace(temp, checkpoint)
        os.replace(pending, receipt_path)
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
