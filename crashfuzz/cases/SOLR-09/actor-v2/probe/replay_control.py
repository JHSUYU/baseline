#!/usr/bin/env python3
"""Non-budget differential: fresh ZK read after two original waits."""

import json
import os
from pathlib import Path
import subprocess
import time

from feedback import atomic_json, events, sequence_applied_in_order
from replay_role059 import PLAN, prove_healthy


WORK = Path(__file__).resolve().parents[1]
BASE = WORK / "evidence/replay-fresh-state-control"
STATE = BASE / "summary.json"


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    proof = prove_healthy()
    control_cp = (WORK / "differential-control/classpath.txt").read_text().strip()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "counted_as_fuzz_attempt": False, "modified_production_control": True,
        "control_semantics": "After both original 30s waits fail, read actual state.json once; regard absent target replica as success",
        "healthy_original_proof": proof, "plan": PLAN, "runs": [],
    }
    while len(state["runs"]) < 12:
        number = len(state["runs"]) + 1
        output = BASE / f"run-{number:02d}"
        env = dict(os.environ, SOLR09_CLASSPATH_OVERRIDE=control_cp)
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
        markers = [line.strip() for line in (output / "junit.log").read_text(errors="replace").splitlines()
                   if "SOLR09_DIFFERENTIAL_FRESH_STATE " in line]
        row = {"number": number, "junit_exit": manifest["exit_code"],
               "matched": len(matched), "applied": len(applied),
               "strict": strict, "target_after": bool(target),
               "target_outcome": target[0]["parts"][0] if target else None,
               "target_exception": bool(exception),
               "fresh_state_markers": markers,
               "elapsed_seconds": round(time.time() - started, 3),
               "evidence": str(output.relative_to(WORK))}
        state["runs"].append(row)
        atomic_json(STATE, state)
        print(json.dumps({k: row[k] for k in (
            "number", "strict", "target_outcome", "target_exception",
            "fresh_state_markers", "junit_exit", "elapsed_seconds")}, sort_keys=True), flush=True)
        informative = [r for r in state["runs"] if r["strict"] and
                       any("present=false" in m for m in r["fresh_state_markers"])]
        if len(informative) >= 2:
            break


if __name__ == "__main__":
    main()
