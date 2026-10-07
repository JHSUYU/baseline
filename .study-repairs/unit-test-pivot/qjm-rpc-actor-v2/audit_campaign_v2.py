#!/usr/bin/env python3
"""Read-only audit of QJM V2 checkpoint against every raw trial artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_offline import HERE
from calibrate_v2 import inspect as inspect_seed
from campaign_v2 import (FIELDS, METHOD, coverage, events, evidence_errors,
                         family, identity, observed, target_after)
from strict_receipt import actor, audit


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(case: str) -> dict:
    root = HERE / "evidence" / f"HDFS-{case}"
    state = json.loads((root / "campaign-v2/checkpoint.json").read_text())
    calibration = json.loads((root / "healthy-calibration.json").read_text())
    errors = []
    if (state.get("case") != f"HDFS-{case}" or state.get("version") != 2 or
            state.get("legacy_trials_imported") != 0 or
            calibration.get("new_effective_trials") != 0):
        errors.append("case/version or fresh denominator mismatch")
    unions = {key: set() for key in ("probes", "methods", "branch_counts", "lines")}
    io_union = set()
    for index, name in enumerate(("healthy-a", "healthy-b")):
        try:
            if inspect_seed(case, name) != calibration["seeds"][index]:
                errors.append(f"{name}: healthy raw/calibration receipt mismatch")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            errors.append(f"{name}: healthy raw audit error {error}")
        for key, values in coverage(root / name).items():
            unions[key].update(values)
        trace = events(root / name / "runtime_trace.jsonl")
        io_union.update(family(e) for e in trace if observed(e) and
                        target_after(trace, case, actor(e["sourceKey"]), e["seq"]))
    seen = set()
    cases = []
    for number, row in enumerate(state["completed"], 1):
        run = root / row["run"]
        if row["run"] in seen:
            errors.append(f"duplicate run ID {row['run']}")
        seen.add(row["run"])
        if not row["run"].startswith(f"trial-{number:04d}-attempt-"):
            errors.append(f"run ordering mismatch {row['run']}")
        try:
            manifest = json.loads((run / "manifest.json").read_text())
            trace_path = run / "runtime_trace.jsonl"
            trace = events(trace_path)
            raw = json.loads((run / "trial-result.json").read_text())
            plan_path = root / "campaign-v2/plans" / (row["run"] + ".tsv")
            plan = [line.split("\t") for line in plan_path.read_text().splitlines()
                    if line.strip()]
            expected_plan = [[str(p[key]) for key in FIELDS[:-1]] +
                             ["pending", p["faultType"]] for p in row["sequence"]]
            if plan != expected_plan or row["id"] != identity(row["sequence"]):
                errors.append(f"{row['run']}: saved plan/ID differs from selected sequence")
            if (manifest.get("case_id") != f"HDFS-{case}" or
                    manifest.get("test") !=
                    "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" + METHOD[case] or
                    manifest.get("returncode") != row["junit_returncode"] or
                    manifest.get("elapsed_seconds") != row["elapsed_seconds"] or
                    manifest.get("plan_sha256") != sha(plan_path) or
                    manifest.get("trace_sha256") !=
                    (sha(trace_path) if trace_path.is_file() else None) or
                    manifest.get("overlay_probe_sha256") !=
                    calibration["seeds"][0]["overlay_probe_sha256"] or
                    manifest.get("overlay_client_sha256") !=
                    calibration["seeds"][0]["overlay_client_sha256"]):
                errors.append(f"{row['run']}: manifest/trace/build provenance mismatch")
            for error in evidence_errors(run, case, manifest, calibration):
                errors.append(f"{row['run']}: {error}")
            receipt = audit(trace, plan, case, row["target_actor"])
            evidence = evidence_errors(run, case, manifest, calibration)
            if evidence:
                receipt["pass"] = False
                receipt["errors"].extend(evidence)
            if (raw != row or receipt != row["receipt"] or
                    receipt["pass"] != row["effective"] or
                    row["target_actor"] != actor(row["sequence"][-1]["sourceKey"])):
                errors.append(f"{row['run']}: strict actor/target receipt mismatch")
            now = coverage(run)
            gain = {key: sorted(values - unions[key]) if row["effective"] else []
                    for key, values in now.items()}
            new_io = sorted({family(e) for e in trace if observed(e)} - io_union)
            if not row["effective"]:
                new_io = []
            candidate = receipt["pass"] and receipt["post_fault_target_throws"] > 0
            if (gain != row["new_coverage_ids"] or
                    new_io != row["new_io_family_ids"] or
                    candidate != row["candidate"] or
                    row["bug_mark"] != ("candidate" if candidate else "none")):
                errors.append(f"{row['run']}: coverage/I/O/candidate feedback mismatch")
            if row["effective"]:
                for key, values in now.items():
                    unions[key].update(values)
                io_union.update(new_io)
            cases.append({"run": row["run"], "effective": row["effective"],
                          "faults": len(row["sequence"]), "actor": row["target_actor"],
                          "junit_seconds": row["elapsed_seconds"],
                          "target_throws": receipt["post_fault_target_throws"],
                          "bug_mark": row["bug_mark"]})
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            errors.append(f"{row['run']}: raw audit error {error}")
    if any(set(state["coverage_union"][key]) != values for key, values in unions.items()):
        errors.append("aggregate JaCoCo union differs from raw recomputation")
    if set(state["io_union"]) != io_union:
        errors.append("aggregate actor-aware I/O union differs from raw")
    effective = sum(row["effective"] for row in state["completed"])
    if effective > state["budget"]["effective"] or len(cases) != len(state["completed"]):
        errors.append("effective budget or raw row count mismatch")
    if state["status"].startswith("budget_complete_") and \
            effective != int(state["status"].rsplit("_", 1)[1]):
        errors.append("terminal effective count differs from budget status")
    return {"pass": not errors, "case": f"HDFS-{case}",
            "status": state["status"], "attempts": len(state["completed"]),
            "effective": effective, "budget": state["budget"],
            "elapsed_junit_seconds": round(sum(r["junit_seconds"] for r in cases), 3),
            "candidate_runs": [r["run"] for r in cases if r["bug_mark"] == "candidate"],
            "runs": cases, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=METHOD, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(args.case)
    print(json.dumps(result, indent=2))
    if args.output:
        if args.output.exists():
            parser.error("audit output exists; choose a new immutable receipt path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
