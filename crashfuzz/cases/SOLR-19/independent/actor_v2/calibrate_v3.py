#!/usr/bin/env python3
"""Resumable, sequential original-JUnit actor gate for the final V3 overlay."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import audit_seeds


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
STATE = EVIDENCE / "v3-calibration-state.json"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(value: dict) -> None:
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(STATE)


def healthy_complete(seed: Path) -> bool:
    manifest = seed / "manifest.json"
    if not manifest.exists():
        return False
    data = json.loads(manifest.read_text())
    return (data.get("exit_code") == 0 and
            (seed / "actor-events.tsv").exists() and
            (seed / "jacoco.exec").exists())


def main() -> int:
    commit = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if not commit.startswith("e27f44e"):
        raise RuntimeError(f"Wrong original Solr source: {commit}")
    EVIDENCE.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "case_id": "SOLR-19", "phase": "actor_v3_healthy",
        "original_junit": "AddReplicaTest.testAddMultipleReplicas",
        "source_commit": commit, "started_utc": utc(), "seeds": {},
    }
    for label in ("a", "b"):
        seed = EVIDENCE / f"v3-seed-{label}"
        if healthy_complete(seed):
            print(utc(), "REUSE_PASSING_SEED", label, flush=True)
        else:
            if seed.exists() and any(seed.iterdir()):
                state["status"] = "partial_seed_needs_review"
                state["partial_seed"] = label
                save(state)
                raise RuntimeError(f"Incomplete or failed {seed}; preserve raw evidence before retry")
            seed.mkdir(parents=True, exist_ok=True)
            state["status"] = "running_seed_" + label
            state["seeds"][label] = {"started_utc": utc(), "path": str(seed)}
            save(state)
            print(utc(), "START_SEED", label, flush=True)
            command = [sys.executable, str(HERE / "run_v2.py"), str(seed),
                       "--coverage", "--source-root", str(SOURCE)]
            with (seed / "runner.log").open("w") as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                        check=False)
            state["seeds"][label]["finished_utc"] = utc()
            state["seeds"][label]["runner_exit"] = result.returncode
            save(state)
            print(utc(), "END_SEED", label, result.returncode, flush=True)
            if result.returncode != 0:
                state["status"] = "failed_seed_needs_review"
                save(state)
                return result.returncode
        audit = audit_seeds.audit(seed)
        state["seeds"][label] = {
            **state["seeds"].get(label, {}),
            "junit_exit": audit["junit_exit"], "core_count": audit["core_count"],
            "issue_count": audit["issue_count"], "io_bound_count": audit["io_bound_count"],
            "io_unbound_count": audit["io_unbound_count"],
        }
        save(state)
        if audit["issue_count"] or audit["core_count"] != 9 or audit["io_bound_count"] == 0:
            state["status"] = "actor_gate_needs_review"
            save(state)
            print(utc(), "ACTOR_GATE_FAILED", label, audit["issue_count"], flush=True)
            return 2
    receipt = EVIDENCE / "v3-healthy-receipt.json"
    command = [sys.executable, str(HERE / "audit_seeds.py"),
               str(EVIDENCE / "v3-seed-a"), str(EVIDENCE / "v3-seed-b"),
               "--output", str(receipt)]
    with (EVIDENCE / "v3-audit.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    state["status"] = "two_healthy_seeds_passed"
    state["finished_utc"] = utc()
    state["receipt"] = str(receipt)
    save(state)
    print(utc(), "TWO_SEEDS_PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
