#!/usr/bin/env python3
"""Independent full-checkpoint replay over raw SOLR-05 V4 evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from audit_v4 import CASE, EVIDENCE, healthy, trace_events, trial
from deps import asm_jars

ROOT = EVIDENCE / "campaign-v4"
STATE = ROOT / "checkpoint.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage(directory: Path) -> tuple[set[str], set[str], dict[str, int]]:
    execution = directory / "jacoco.exec"
    if not execution.is_file():
        return set(), set(), {}
    cp = ":".join([str(CASE / "classes"), str(CASE.parent / "lib/jacoco-core.jar"),
                   *map(str, asm_jars()), (CASE / "classpath.txt").read_text().strip()])
    block_output = subprocess.check_output([JAVA, "-cp", cp,
        "baseline.solr05v4.CoverageProbes", str(execution), DIST], text=True)
    branch_output = subprocess.check_output([JAVA, "-cp", cp,
        "baseline.solr05v4.CoverageFeedback", DIST, str(CASE / "classes"),
        str(execution)], text=True)
    branches = {}
    for line in branch_output.splitlines():
        method, count = line.rsplit("\t", 1)
        branches[method] = int(count)
    return set(block_output.splitlines()), set(branches), branches


def io_family(event: dict) -> str | None:
    if event["kind"] not in ("IO_OBSERVED", "RECEIVER_IO_OBSERVED", "UPSTREAM_IO_OBSERVED"):
        return None
    parts = event["parts"]
    if len(parts) < 3:
        return None
    op, path, caller = parts[:3]
    if not (path.startswith("/collections/testAddMultipleReplicas") or
            path.startswith("/live_nodes") or path.startswith("/overseer")):
        return None
    if "/leader_elect/" in path:
        resource = "leader-election"
    elif "/leaders/" in path:
        resource = "leader-state"
    elif path.endswith("/state.json"):
        resource = "collection-state"
    elif path.startswith("/overseer"):
        resource = "overseer"
    elif path.startswith("/live_nodes"):
        resource = "live-nodes"
    else:
        resource = "collection-other"
    return "|".join((op, resource, caller.split(":", 1)[0]))


def main() -> None:
    state_bytes = STATE.read_bytes()
    state = json.loads(state_bytes)
    errors = []
    if (state.get("case") != "SOLR-05" or
            state.get("identity_version") != "receiver-state-read-v4" or
            state.get("legacy_attempts_imported") != 0 or
            state.get("legacy_effective_imported") != 0 or
            state.get("test") != "AddReplicaTest.testAddMultipleReplicas"):
        errors.append("checkpoint case, JUnit, identity or legacy import differs")
    expected_calibration = [healthy(EVIDENCE / name) for name in
        ("original-001", "original-002", "healthy-001", "healthy-002")]
    if state["calibration"] != expected_calibration:
        errors.append("healthy calibration differs from raw")
    blocks, methods, branches, ios = set(), set(), {}, set()
    for name in ("healthy-001", "healthy-002"):
        directory = EVIDENCE / name
        new_blocks, new_methods, new_branches = coverage(directory)
        blocks |= new_blocks
        methods |= new_methods
        for key, count in new_branches.items():
            branches[key] = max(branches.get(key, 0), count)
        ios |= {value for e in trace_events(directory / "events.tsv")
                if (value := io_family(e)) is not None}
    effective = 0
    candidates = []
    seconds = 0.0
    seen_plans = []
    for number, row in enumerate(state["trials"], 1):
        directory = CASE / row["evidence"]
        if number != row["number"] or not directory.is_dir():
            errors.append(f"trial {number}: numbering or raw directory missing")
            continue
        try:
            reconstructed = trial(directory, row["plan"])
            if reconstructed != row["audit"] or json.loads(
                    (directory / "v4-trial.json").read_text()) != row:
                errors.append(f"trial {number}: raw audit or immutable row mismatch")
            manifest = json.loads((directory / "manifest.json").read_text())
            if (manifest["test"] != state["test"] or
                    manifest["identity_version"] != state["identity_version"]):
                errors.append(f"trial {number}: wrong original test or identity version")
            token = hashlib.sha256(";".join(row["plan"]).encode()).hexdigest()[:20]
            if token in seen_plans:
                errors.append(f"trial {number}: repeated plan")
            seen_plans.append(token)
            seconds += reconstructed["elapsed_seconds"]
            eligible = reconstructed["strict"] and reconstructed["effective"]
            new_blocks, new_methods, new_branches = (coverage(directory)
                if eligible else (set(), set(), {}))
            new_io = {value for e in trace_events(directory / "events.tsv")
                      if (value := io_family(e)) is not None} if eligible else set()
            novelty = {"blocks": len(new_blocks - blocks),
                       "methods": len(new_methods - methods),
                       "branches": sum(max(0, count - branches.get(k, 0))
                                       for k, count in new_branches.items()),
                       "io": len(new_io - ios)}
            if novelty != row["new"]:
                errors.append(f"trial {number}: coverage/I/O feedback differs")
            if eligible:
                effective += 1
                blocks |= new_blocks
                methods |= new_methods
                ios |= new_io
                for k, count in new_branches.items():
                    branches[k] = max(branches.get(k, 0), count)
            if reconstructed["target_exception"]:
                candidates.append(number)
        except Exception as exc:
            errors.append(f"trial {number}: {type(exc).__name__}: {exc}")
    if (effective != state["effective"] or blocks != set(state["coverage_union"]) or
            methods != set(state["method_union"]) or
            branches != state["branch_union"] or ios != set(state["io_union"]) or
            seen_plans != state["seen_plans"]):
        errors.append("recomputed denominator or feedback union differs")
    if state["status"] == "budget_reached" and effective < state["budget"]["effective_goal"]:
        errors.append("terminal budget claim lacks effective raw trials")
    result = {"case": "SOLR-05", "identity_version": "receiver-state-read-v4",
              "checkpoint_sha256": hashlib.sha256(state_bytes).hexdigest(),
              "completed_trials": len(state["trials"]), "effective_trials": effective,
              "total_trial_seconds": round(seconds, 3), "candidate_trials": candidates,
              "status": state["status"], "inflight": state["inflight"] is not None,
              "errors": errors}
    destination = ROOT / "independent-raw-audit.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
