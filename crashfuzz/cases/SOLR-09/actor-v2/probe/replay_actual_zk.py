#!/usr/bin/env python3
"""Non-budget replay: read server state after the selected Boolean is fixed."""

import json
import os
from pathlib import Path
import subprocess
import time

from feedback import atomic_json, events, sequence_applied_in_order
from replay_role059 import PLAN, prove_healthy


WORK = Path(__file__).resolve().parents[1]
BASE = WORK / "evidence/replay-actual-zk"
STATE = BASE / "summary.json"


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    proof = prove_healthy()
    diagnostic_cp = (WORK / "diagnostic/classpath.txt").read_text().strip()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "counted_as_fuzz_attempt": False,
        "diagnostic_read_after_boolean_fixed": True,
        "healthy_proof": proof, "plan": PLAN, "runs": [],
    }
    while len(state["runs"]) < 12:
        number = len(state["runs"]) + 1
        output = BASE / f"run-{number:02d}"
        env = dict(os.environ, SOLR09_CLASSPATH_OVERRIDE=diagnostic_cp,
                   SOLR09_DIAGNOSTIC_ACTUAL_ZK="1")
        started = time.time()
        subprocess.run(["/usr/bin/python3", str(WORK / "probe/run.py"),
                        str(output), "--coverage", "--faults", ";".join(PLAN),
                        "--timeout", "240"], env=env, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
        strict = sequence_applied_in_order(PLAN, applied, matched, trace)
        last = applied[-1]["seq"] if applied else -1
        target = [e for e in trace if e["kind"] == "TARGET_CHECK" and e["seq"] > last]
        actual = [e for e in trace if e["kind"] in ("ZK_ACTUAL_STATE", "ZK_ACTUAL_STATE_ERROR")
                  and target and e["seq"] > target[0]["seq"]]
        exception = [e for e in trace if e["kind"] == "TARGET_EXCEPTION"
                     and e["seq"] > last]
        row = {"number": number, "junit_exit": manifest["exit_code"],
               "matched": len(matched), "applied": len(applied),
               "strict": strict, "target_after": bool(target),
               "target_outcome": target[0]["parts"][0] if target else None,
               "target_exception": bool(exception),
               "actual_state_events": [{"kind": e["kind"], "parts": e["parts"]}
                                       for e in actual],
               "elapsed_seconds": round(time.time() - started, 3),
               "evidence": str(output.relative_to(WORK))}
        state["runs"].append(row)
        atomic_json(STATE, state)
        print(json.dumps({k: row[k] for k in (
            "number", "strict", "target_outcome", "target_exception",
            "actual_state_events", "elapsed_seconds")}, sort_keys=True), flush=True)
        confirmed = [r for r in state["runs"] if r["strict"] and
                     r["target_exception"] and any(
                         e["kind"] == "ZK_ACTUAL_STATE" and
                         "replica_present=false" in e["parts"]
                         for e in r["actual_state_events"])]
        if len(confirmed) >= 2:
            break


if __name__ == "__main__":
    main()
