#!/usr/bin/env python3
"""Non-budget original-JUnit replay with guard-time reader and core-dir snapshots."""

import json
import os
import argparse
from pathlib import Path
import subprocess
import time

from feedback import atomic_json, events, sequence_applied_in_order
from replay_role059 import PLAN, prove_healthy


WORK = Path(__file__).resolve().parents[1]
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("directory", "timeout"), default="directory")
    args = parser.parse_args()
    base_name = "replay-directory" if args.mode == "directory" else "replay-timeout"
    BASE = WORK / "evidence" / base_name
    STATE = BASE / "summary.json"
    BASE.mkdir(parents=True, exist_ok=True)
    proof = prove_healthy()
    healthy_name = ("healthy-directory-diagnostic" if args.mode == "directory"
                    else "healthy-timeout-diagnostic")
    healthy = WORK / "evidence" / healthy_name / "manifest.json"
    if not healthy.exists() or json.loads(healthy.read_text())["exit_code"] != 0:
        raise RuntimeError("Directory diagnostic needs a passing healthy calibration")
    cp = (WORK / (args.mode + "-diagnostic/classpath.txt")).read_text().strip()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "counted_as_fuzz_attempt": False, "diagnostic_reads_after_boolean_fixed": True,
        "healthy_proof": proof, "plan": PLAN, "runs": [],
    }
    while len(state["runs"]) < 12:
        number = len(state["runs"]) + 1
        output = BASE / f"run-{number:02d}"
        env = dict(os.environ, SOLR09_CLASSPATH_OVERRIDE=cp,
                   SOLR09_DIAGNOSTIC_ACTUAL_ZK="1")
        load_before = os.getloadavg()
        java_before = subprocess.run(["/usr/bin/pgrep", "-c", "java"],
                                     text=True, capture_output=True, check=False)
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
        exception = [e for e in trace if e["kind"] == "TARGET_EXCEPTION"
                     and e["seq"] > last]
        wanted = {"READER_MAP_STATE", "READER_MAP_STATE_ERROR", "ZK_ACTUAL_STATE",
                  "ZK_ACTUAL_STATE_ERROR", "CORE_DIR_STATE",
                  "PRE_TIMEOUT_READER_STATE", "PRE_TIMEOUT_READER_STATE_ERROR"}
        diagnostic = [e for e in trace if e["kind"] in wanted]
        row = {"number": number, "junit_exit": manifest["exit_code"],
               "matched": len(matched), "applied": len(applied),
               "strict": strict, "target_after": bool(target),
               "target_outcome": target[0]["parts"][0] if target else None,
               "target_exception": bool(exception),
               "diagnostic_events": [{"kind": e["kind"], "parts": e["parts"]}
                                     for e in diagnostic],
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
        if strict and exception and any(
            e["kind"] == "ZK_ACTUAL_STATE" and "replica_present=false" in e["parts"]
            for e in row["diagnostic_events"]):
            break


if __name__ == "__main__":
    main()
