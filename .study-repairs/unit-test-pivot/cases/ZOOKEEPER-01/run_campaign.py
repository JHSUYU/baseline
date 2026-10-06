#!/usr/bin/env python3
"""Run ZK01's 64/6 campaign and extend the same checkpoint when useful."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


BASE = Path("/users/ZhenyuLi/zk01-unit")
sys.path.insert(0, str(BASE / "core-fuzzer"))
import fuzzer  # noqa: E402


CONFIG = BASE / "campaign/case.json"
ROOT = BASE / "campaign/results"
CASE = ROOT / "ZOOKEEPER-01"


def production_code(identifier: str) -> bool:
    if not identifier.startswith(("METHOD:", "BRANCH:")):
        return False
    method = identifier.split(":", 1)[1].split("#u", 1)[0]
    if not method.startswith("<org.apache.zookeeper."):
        return False
    owner = method[1:].split(":", 1)[0].split("$")[0]
    return not owner.rsplit(".", 1)[-1].endswith("Test")


def extension_evidence(state: dict) -> dict:
    seen = set(state["seed"]["feedback"]["coverage"])
    tail = []
    for completed in state["completed"]:
        result = json.loads(Path(completed["result"]).read_text())
        admitted = result.get("status") in {
            "checked", "target_exception_candidate",
            "baseline_exception_recurrence", "target_exception_unlinked"}
        coverage = set(result.get("coverage", []))
        gain = coverage - seen if admitted else set()
        if admitted:
            seen.update(coverage)
        tail.append({
            "number": completed["number"], "status": completed["status"],
            "new_production_code": sum(production_code(item) for item in gain),
            "new_io_families": result.get("new_io_count", 0) if admitted else 0,
        })
    recent = tail[-12:]
    return {
        "completed": len(tail), "recent_window": recent,
        "recent_new_production_code": sum(r["new_production_code"] for r in recent),
        "recent_new_io_families": sum(r["new_io_families"] for r in recent),
        "pending_queue": len(state.get("queue", [])),
    }


def invoke(phase: str) -> None:
    log = BASE / "campaign" / (phase + ".log")
    with log.open("w") as stream:
        process = subprocess.run(
            [sys.executable, str(BASE / "core-fuzzer/fuzzer.py"),
             str(CONFIG), "--root", str(ROOT)],
            cwd=BASE / "campaign", stdout=stream, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"{phase} failed with code {process.returncode}; see {log}")


def main() -> None:
    start = time.time()
    invoke("phase-64")
    state = json.loads((CASE / "state.json").read_text())
    audit = extension_evidence(state)
    audit["initial_budget"] = {"max_trials": 64, "max_faults": 6}
    audit["started_at"] = start
    extend = (audit["completed"] >= 64 and audit["pending_queue"] > 0 and
              (audit["recent_new_production_code"] > 0 or
               audit["recent_new_io_families"] > 0))
    audit["extended"] = extend
    if extend:
        config = json.loads(CONFIG.read_text())
        config["budget"]["max_trials"] = 128
        config["budget"]["max_faults"] = 8
        fuzzer.atomic_json(CONFIG, config)
        fuzzer.atomic_json(CASE / "extension-decision.json", audit)
        invoke("phase-128")
    state = json.loads((CASE / "state.json").read_text())
    audit["final_completed"] = len(state["completed"])
    audit["final_pending_queue"] = len(state.get("queue", []))
    audit["finished_at"] = time.time()
    fuzzer.atomic_json(CASE / "extension-decision.json", audit)
    fuzzer.atomic_json(CASE / "campaign.done.json", {
        "completed": len(state["completed"]), "extended": extend,
        "started_at": start, "finished_at": audit["finished_at"]})
    print(json.dumps({"completed": len(state["completed"]),
                      "extended": extend, "queue": len(state["queue"])}))


if __name__ == "__main__":
    main()
