#!/usr/bin/env python3
"""Non-budget, actor-aware diagnostic of the coarse trial059 candidate."""

import json
from pathlib import Path
import subprocess
import time

from feedback import atomic_json, events, sequence_applied_in_order


WORK = Path(__file__).resolve().parents[1]
BASE = WORK / "evidence/replay-role-trial059"
STATE = BASE / "summary.json"
ZK_PATH = "/collections/deletereplica_test/state.json"
PLAN = [
    "HTTP_POST|/admin/cores?action=UNLOAD&core=<target>|1|"
    "caller=org.apache.solr.handler.component.ShardRequestor#call:130|"
    "actor=target_replica_http",
    "GET_CHILDREN_STAT|" + ZK_PATH + "|@1|"
    "caller=org.apache.solr.common.cloud.ZkStateReader$StateWatcher#"
    "refreshAndWatchChildren:1405|actor=target_overseer|after=F0|seed_global=1",
    "GET_DATA|" + ZK_PATH + "|@2|"
    "caller=org.apache.solr.common.cloud.ZkStateReader#"
    "fetchCollectionState:1641|actor=target_overseer|after=F1|seed_global=2",
]


def prove_healthy() -> dict:
    proof = {}
    for name in ("healthy-instrumented", "healthy-actor-diagnostic-003"):
        directory = WORK / "evidence" / name
        manifest = json.loads((directory / "manifest.json").read_text())
        trace = events(directory / "events.tsv")
        bound = [e for e in trace if e["kind"] == "TARGET_ACTORS_BOUND"]
        target = [e for e in trace if e["kind"] == "TARGET_CHECK"]
        if manifest["exit_code"] != 0 or len(bound) != 1 or len(target) != 1:
            raise RuntimeError(f"Healthy target calibration failed: {name}")
        last = bound[0]["seq"]
        points = []
        for operation, actor in (("HTTP_POST", "actor=target_replica_http"),
                                 ("GET_CHILDREN_STAT", "actor=target_overseer"),
                                 ("GET_DATA", "actor=target_overseer")):
            candidates = [e for e in trace if e["kind"] == "IO_OBSERVED"
                          and e["seq"] > last and e["seq"] < target[0]["seq"]
                          and e["parts"][0] == operation
                          and (operation == "HTTP_POST" or e["parts"][1] == ZK_PATH)
                          and actor in e["parts"]]
            if operation == "GET_DATA":
                candidates = [e for e in candidates if
                              e["seq"] > points[1] and
                              "caller=org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState:1641"
                              in e["parts"]]
                if len(candidates) < 2:
                    raise RuntimeError(f"Healthy second read absent: {name}")
                points.append(candidates[1]["seq"])
            elif not candidates:
                raise RuntimeError(f"Healthy actor-aware point absent: {name} {operation}")
            else:
                points.append(candidates[0]["seq"])
            last = points[-1]
        if not points[0] < points[1] < points[2] < target[0]["seq"]:
            raise RuntimeError(f"Healthy order failed: {name}")
        client = next(x.split("=", 1)[1] for x in bound[0]["parts"]
                      if x.startswith("overseer_client_id="))
        for event in trace:
            if event["seq"] in points[1:]:
                if "client_id=" + client not in event["parts"]:
                    raise RuntimeError(f"Different ZK client: {name}")
        proof[name] = {"sequence": points + [target[0]["seq"]],
                       "overseer_client_id": client}
    return proof


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    proof = prove_healthy()
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "source_trial": "http-stage2/evidence/campaign/trial-059",
        "role_relative_plan_is_distinct_from_old_absolute_plan": True,
        "counted_as_fuzz_attempt": False,
        "healthy_proof": proof, "plan": PLAN, "runs": [],
    }
    while len(state["runs"]) < 10:
        number = len(state["runs"]) + 1
        output = BASE / f"run-{number:02d}"
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
        target = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                  e["seq"] > last]
        exception = [e for e in trace if e["kind"] == "TARGET_EXCEPTION" and
                     e["seq"] > last]
        row = {"number": number, "junit_exit": manifest["exit_code"],
               "matched": len(matched), "applied": len(applied),
               "strict": strict, "target_after": bool(target),
               "target_outcomes": [e["parts"][0] for e in target],
               "target_exception": bool(exception),
               "elapsed_seconds": round(time.time() - started, 3),
               "evidence": str(output.relative_to(WORK))}
        state["runs"].append(row)
        atomic_json(STATE, state)
        print(json.dumps(row, sort_keys=True), flush=True)
        strict_count = sum(r["strict"] and r["target_after"] for r in state["runs"])
        exceptions = sum(r["strict"] and r["target_exception"] for r in state["runs"])
        if strict_count >= 3 and exceptions >= 2:
            break


if __name__ == "__main__":
    main()
