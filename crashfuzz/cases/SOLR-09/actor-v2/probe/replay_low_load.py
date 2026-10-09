#!/usr/bin/env python3
"""Bounded non-budget replay using the frozen V2 classes with host-load receipts."""

import json
import os
from pathlib import Path
import subprocess
import time

from feedback import atomic_json, events, sequence_applied_in_order
from replay_role059 import PLAN, prove_healthy


WORK = Path(__file__).resolve().parents[1]
BASE = WORK / "evidence/replay-low-load"
STATE = BASE / "summary.json"


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    proof = prove_healthy()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "counted_as_fuzz_attempt": False,
        "frozen_v2_business_logic": True,
        "healthy_proof": proof, "plan": PLAN, "runs": [],
    }
    while len(state["runs"]) < 12:
        number = len(state["runs"]) + 1
        output = BASE / f"run-{number:02d}"
        load_before = os.getloadavg()
        java_before = subprocess.run(["/usr/bin/pgrep", "-c", "java"],
                                     text=True, capture_output=True, check=False)
        started = time.time()
        subprocess.run(["/usr/bin/python3", str(WORK / "probe/run.py"),
                        str(output), "--coverage", "--faults", ";".join(PLAN),
                        "--timeout", "240"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
        strict = sequence_applied_in_order(PLAN, applied, matched, trace)
        last = applied[-1]["seq"] if applied else -1
        target = [e for e in trace if e["kind"] == "TARGET_CHECK" and e["seq"] > last]
        exception = [e for e in trace if e["kind"] == "TARGET_EXCEPTION"
                     and e["seq"] > last]
        row = {"number": number, "junit_exit": manifest["exit_code"],
               "matched": len(matched), "applied": len(applied),
               "strict": strict, "target_after": bool(target),
               "target_outcome": target[0]["parts"][0] if target else None,
               "target_exception": bool(exception),
               "loadavg_before": load_before,
               "other_java_processes_before": int(java_before.stdout.strip() or 0),
               "elapsed_seconds": round(time.time() - started, 3),
               "evidence": str(output.relative_to(WORK))}
        state["runs"].append(row)
        atomic_json(STATE, state)
        print(json.dumps({k: row[k] for k in (
            "number", "strict", "target_outcome", "target_exception",
            "loadavg_before", "other_java_processes_before", "elapsed_seconds")},
            sort_keys=True), flush=True)
        if strict and exception:
            break


if __name__ == "__main__":
    main()
