#!/usr/bin/env python3
"""Read-only audit of every HDFS-16 V2 trial against immutable raw evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_offline import HERE
from calibrate_v2 import inspect as inspect_seed, read_events, family
from campaign_v2 import (FIELDS, KINDS, coverage, evidence_errors, identity,
                         relevant, next_context, sha)
from run_v2 import TEST
from strict_receipt import audit


def inspect(root: Path) -> dict:
    state = json.loads((root / "campaign-v2/checkpoint.json").read_text())
    calibration = json.loads((root / "healthy-calibration.json").read_text())
    errors: list[str] = []
    if (state.get("case") != "HDFS-16" or state.get("version") != 2 or
            state.get("legacy_trials_imported") != 0 or
            calibration.get("legacy_trials_imported") != 0):
        errors.append("wrong case/version or historical trials imported")
    unions = {key: set() for key in KINDS}
    io_union: set[str] = set()
    for index, seed in enumerate(("healthy-a", "healthy-b")):
        try:
            if root == HERE / "evidence" and inspect_seed(seed) != calibration["seeds"][index]:
                errors.append(f"{seed}: raw/calibration receipt mismatch")
            run = root / seed
            for key, values in coverage(run).items():
                unions[key].update(values)
            trace = read_events(run / "runtime_trace.jsonl")
            io_union.update(family(event) for event in trace if relevant(event)
                            and next_context(trace, event["seq"]) is not None)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{seed}: raw audit error {exc}")
    rows = []
    seen_runs: set[str] = set()
    seen_ids: set[str] = set()
    for number, row in enumerate(state["completed"], 1):
        run = root / row["run"]
        if row["run"] in seen_runs or row["id"] in seen_ids:
            errors.append(f"{row['run']}: duplicate run or plan identity")
        seen_runs.add(row["run"])
        seen_ids.add(row["id"])
        if not row["run"].startswith(f"trial-{number:04d}-attempt-"):
            errors.append(f"{row['run']}: selected trial order mismatch")
        try:
            manifest = json.loads((run / "manifest.json").read_text())
            raw = json.loads((run / "trial-result.json").read_text())
            trace_path = run / "runtime_trace.jsonl"
            trace = read_events(trace_path)
            plan_path = root / "campaign-v2/plans" / (row["run"] + ".tsv")
            plan = [line.split("\t") for line in plan_path.read_text().splitlines() if line]
            expected = [[str(step[key]) for key in FIELDS] for step in row["sequence"]]
            if (plan != expected or row["id"] !=
                    identity(row["sequence"], row["target_context"])):
                errors.append(f"{row['run']}: planned sequence/identity changed")
            if (manifest.get("case_id") != "HDFS-16" or manifest.get("test") != TEST or
                    manifest.get("returncode") != row["junit_returncode"] or
                    manifest.get("elapsed_seconds") != row["elapsed_seconds"] or
                    manifest.get("plan_sha256") != sha(plan_path) or
                    manifest.get("trace_sha256") != sha(trace_path)):
                errors.append(f"{row['run']}: manifest/test/trace provenance differs")
            for problem in evidence_errors(run, manifest, calibration):
                errors.append(f"{row['run']}: {problem}")
            receipt = audit(trace, plan, row["target_context"])
            evidence = evidence_errors(run, manifest, calibration)
            if evidence:
                receipt["pass"] = False
                receipt["errors"].extend(evidence)
            if raw != row or receipt != row["receipt"] or receipt["pass"] != row["effective"]:
                errors.append(f"{row['run']}: strict actor/context receipt differs")
            now = coverage(run)
            gains = {key: sorted(values - unions[key]) if row["effective"] else []
                     for key, values in now.items()}
            new_io = sorted({family(event) for event in trace if relevant(event) and
                             next_context(trace, event["seq"]) is not None} - io_union)
            if not row["effective"]:
                new_io = []
            candidate = bool(receipt["pass"] and
                             receipt["same_context_postfault_exceptions"] > 0 and
                             manifest.get("returncode") != 0)
            if (gains != row["new_coverage_ids"] or new_io != row["new_io_family_ids"] or
                    candidate != row["candidate"] or
                    row["bug_mark"] != ("candidate" if candidate else "none")):
                errors.append(f"{row['run']}: coverage/I/O/candidate feedback differs")
            if row["effective"]:
                for key, values in now.items():
                    unions[key].update(values)
                io_union.update(new_io)
            rows.append({"run": row["run"], "effective": row["effective"],
                         "faults": len(row["sequence"]),
                         "seconds": row["elapsed_seconds"],
                         "target_contexts": receipt["concrete_postfault_target_contexts"],
                         "target_exceptions": receipt["same_context_postfault_exceptions"],
                         "bug_mark": row["bug_mark"]})
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{row['run']}: raw audit error {exc}")
    if any(set(state["coverage_union"][key]) != union for key, union in unions.items()):
        errors.append("aggregate production coverage union differs from raw")
    if set(state["io_union"]) != io_union:
        errors.append("aggregate actor-aware I/O union differs from raw")
    effective = sum(row["effective"] for row in state["completed"])
    if effective > state["budget"]["effective"]:
        errors.append("effective count exceeds budget")
    if state["status"].startswith("budget_complete_") and \
            effective != int(state["status"].rsplit("_", 1)[1]):
        errors.append("terminal effective count differs from status")
    return {"pass": not errors, "case": "HDFS-16", "status": state["status"],
            "attempts": len(rows), "effective": effective, "budget": state["budget"],
            "elapsed_junit_seconds": round(sum(row["seconds"] for row in rows), 3),
            "candidate_runs": [row["run"] for row in rows if row["bug_mark"] == "candidate"],
            "runs": rows, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=HERE / "evidence")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect(args.root)
    print(json.dumps(result, indent=2))
    if args.output:
        if args.output.exists():
            parser.error("immutable audit output exists")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
