#!/usr/bin/env python3
"""Write the first exact producer response-loss plan from two healthy seeds."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex

from campaign import plan_text, point, sequence_id
from identity_gate import KEYS, rows

HERE = Path(__file__).resolve().parent


def prepare(output: Path) -> dict:
    output = output.resolve()
    healthy = json.loads((output / "healthy_receipt.json").read_text())
    if healthy.get("case_id") != "HDFS-12" or healthy.get("pass") is not True:
        raise ValueError("two original HDFS-12 healthy seeds must pass before smoke")
    stable = {tuple(value) for value in healthy.get("stable_producer_selectors", [])}
    if not stable:
        raise ValueError("no stable rotated-key producer selector")
    candidates = [row for row in rows(output / "healthy-a")
                  if row.get("event") == "FAULT_POINT_OBSERVED"
                  and row.get("marker") == "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE"
                  and row.get("keyRole") == "ROTATED_CURRENT"
                  and tuple(row.get(key) for key in KEYS) in stable]
    if not candidates:
        raise ValueError("stable producer response marker absent from healthy-a trace")
    selected = min(candidates, key=lambda row: row["seq"])
    sequence = [point(selected, "SocketTimeoutException")]
    identity = sequence_id(sequence)
    plan = output / "plans" / (identity + ".tsv")
    plan.parent.mkdir(parents=True, exist_ok=True)
    contents = plan_text(sequence)
    if plan.exists() and plan.read_text() != contents:
        raise FileExistsError("existing smoke plan differs; preserve prior evidence")
    plan.write_text(contents)
    run = output / "runs" / identity
    commands = [
        ["python3", str(HERE / "run_original.py"), "--case", "HDFS-12",
         "--output", str(run), "--plan", str(plan), "--timeout", "600"],
        ["python3", str(HERE / "identity_gate.py"), "evaluate", "--case", "HDFS-12",
         "--run", str(run), "--plan", str(plan),
         "--healthy-receipt", str(output / "healthy_receipt.json")],
    ]
    script = output / "run-smoke-response-loss.sh"
    text = ("#!/bin/sh\nset -eu\n"
            + "if [ ! -f " + shlex.quote(str(run / "manifest.json")) + " ]; then\n"
            + "  " + shlex.join(commands[0]) + "\nfi\n"
            + shlex.join(commands[1]) + "\n")
    if script.exists() and script.read_text() != text:
        raise FileExistsError("existing smoke script differs; preserve prior evidence")
    script.write_text(text)
    script.chmod(0o700)
    return {"plan": str(plan), "run": str(run), "script": str(script),
            "sequence_id": identity, "fault_actor": selected["faultActor"],
            "resource": selected["resource"], "nn": selected.get("nnLogical"),
            "healthy_raw_key_id": selected.get("rawKeyId"),
            "runtime_required_raw_key_id": "*", "hit_ordinal": selected["hitOrdinal"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
