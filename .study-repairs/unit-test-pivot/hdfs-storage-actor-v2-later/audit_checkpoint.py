#!/usr/bin/env python3
"""Read-only audit of an HDFS storage V2 campaign checkpoint and raw trials."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re


FIELDS = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
          "actorKey", "storageKey", "peerRole", "faultType")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def volume(value: str | None) -> str:
    match = re.match(r"^dfs/(?:data[0-9]+|data|datanodeMaster)(?:/|$)", value or "")
    return match.group(0).rstrip("/") if match else "unbound"


def check_trial(item: dict, result: dict, receipt: dict) -> tuple[dict[str, bool], list[str]]:
    issues: list[str] = []
    trace_path = Path(result["trace"])
    manifest_path = Path(result["manifest"])
    trace = rows(trace_path)
    manifest = json.loads(manifest_path.read_text())
    if hashlib.sha256(trace_path.read_bytes()).hexdigest() != result["trace_sha256"]:
        issues.append("trace digest mismatch")
    if manifest.get("instrumentation_digest_sha256") != receipt["seeds"][0]["instrumentation_digest_sha256"]:
        issues.append("trial overlay digest differs from healthy seeds")
    if manifest.get("returncode") != result["junit_exit"]:
        issues.append("JUnit exit differs from manifest")
    if not (manifest_path.parent / "jacoco.exec").is_file():
        issues.append("missing JaCoCo data")
    for category in ("probes", "methods", "branch_counts", "lines"):
        if not (manifest_path.parent / f"covered_{category}.txt").is_file():
            issues.append(f"missing {category} coverage")
    applied = [row for row in trace if row["event"] == "FAULT_APPLIED"]
    sequence = item["sequence"]
    exact = len(sequence) == len(applied) and all(
        event.get("faultIndex") == index and all(
            step.get(field) == event.get(field) for field in FIELDS)
        for index, (step, event) in enumerate(zip(sequence, applied)))
    endpoints: dict[str, set[str]] = defaultdict(set)
    for row in trace:
        if row.get("peerRole") == "NN0" and row.get("endpointRaw"):
            endpoints[row.get("actorKey", "unbound")].add(row["endpointRaw"])
    if exact:
        for step, event in zip(sequence, applied):
            if "RPC:" not in step["marker"]:
                continue
            actual = endpoints.get(step["actorKey"], set())
            if (len(actual) != 1 or event.get("endpointRaw") not in actual
                    or event.get("actorNamenodeRaw") != event.get("endpointRaw")):
                exact = False
                issues.append("ambiguous or mismatched actor RPC endpoint")
                break
    if exact != result["exact_order_applied"]:
        issues.append("strict applied count differs from checkpoint")
    effective: dict[str, bool] = {}
    last = applied[-1] if exact and applied else None
    for case, saved in result["by_case"].items():
        matching = []
        throws = []
        if last is not None:
            actor = sequence[-1]["actorKey"]
            target_volume = (volume(sequence[-1].get("storageKey"))
                             if "FILE:" in sequence[-1]["marker"] else None)
            for row in trace:
                if (row.get("caseId") != case or row["seq"] <= last["seq"]
                        or row.get("actorKey") != actor
                        or (target_volume is not None
                            and volume(row.get("storageKey")) != target_volume)):
                    continue
                if row["event"] == "TARGET_CHECK" and row.get("storageKey") != "unbound":
                    matching.append(row)
                if row["event"] == "TARGET_THROW":
                    throws.append(row)
        effective[case] = bool(matching)
        if len(matching) != saved["same_actor_post_target"] or effective[case] != saved["valid_for_feedback"]:
            issues.append(f"{case} postfault target receipt differs from checkpoint")
        if len(throws) != saved["target_exception_after_fault"]:
            issues.append(f"{case} target-throw count differs from checkpoint")
    return effective, issues


def audit(anchor: Path) -> dict:
    state = json.loads((anchor / "campaign-state.json").read_text())
    receipt_path = anchor / "healthy_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    issues: list[str] = []
    if not receipt.get("pass") or len(receipt.get("seeds", [])) != 2:
        issues.append("two-seed healthy receipt not passed")
    if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != state["healthy_receipt_sha256"]:
        issues.append("healthy receipt digest differs from checkpoint")
    ids = state["completion_order"]
    if len(ids) != len(set(ids)) or set(ids) != set(state["completed"]):
        issues.append("completed sequence IDs are duplicated or missing")
    effective = Counter({case: 0 for case in state["case_ids"]})
    strict = 0
    junit_exit = Counter()
    target_throws = Counter()
    elapsed = 0.0
    all_attempt_elapsed = 0.0
    effective_elapsed = Counter({case: 0.0 for case in state["case_ids"]})
    last_completed_at = None
    for sequence_id in ids:
        entry = state["completed"][sequence_id]
        result = entry["result"]
        trial_effective, trial_issues = check_trial(entry["item"], result, receipt)
        issues.extend(f"{sequence_id}: {issue}" for issue in trial_issues)
        strict += bool(result["exact_order_applied"])
        junit_exit[str(result["junit_exit"])] += 1
        elapsed += result["elapsed_seconds"]
        all_attempt_elapsed += sum(attempt["elapsed_seconds"] for attempt in entry["attempts"])
        last_completed_at = json.loads(Path(result["manifest"]).read_text()).get("finished_at_utc")
        for case, valid in trial_effective.items():
            effective[case] += valid
            if valid:
                effective_elapsed[case] += result["elapsed_seconds"]
            target_throws[case] += result["by_case"][case]["target_exception_after_fault"]
    if dict(effective) != state["effective_by_case"]:
        issues.append("effective counts differ from independently reconstructed trace counts")
    return {
        "schema": "hdfs-storage-v2-raw-checkpoint-audit-1",
        "group": state["group"], "checkpoint_status": state.get("status"),
        "completed_distinct_sequences": len(ids), "strict_sequences": strict,
        "effective_by_case": dict(effective),
        "reported_effective_by_case": state["effective_by_case"],
        "target_exceptions_after_fault_by_case": dict(target_throws),
        "junit_exit_counts": dict(junit_exit),
        "sum_selected_attempt_seconds": round(elapsed, 3),
        "sum_all_attempt_seconds": round(all_attempt_elapsed, 3),
        "effective_attempt_seconds_by_case": {case: round(value, 3)
                                              for case, value in effective_elapsed.items()},
        "campaign_started_at_utc": state.get("started_at_utc"),
        "last_completed_at_utc": last_completed_at,
        "queue": len(state["queue"]),
        "in_flight": state["in_flight"]["id"] if state.get("in_flight") else None,
        "healthy_receipt_sha256": state["healthy_receipt_sha256"],
        "instrumentation_digest_sha256": receipt["seeds"][0]["instrumentation_digest_sha256"],
        "pass": not issues, "issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", type=Path)
    args = parser.parse_args()
    result = audit(args.anchor)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
