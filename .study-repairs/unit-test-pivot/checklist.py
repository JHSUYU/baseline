#!/usr/bin/env python3
"""Render the 102-check unit-test campaign from isolated case results."""

from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SELECTION = HERE / "selection102.json"
RESULTS = HERE / "cases"
TERMINAL = {"no_cluster_test", "source_excluded", "quality_complete",
            "confirmed_bug", "no_valid_target_trial"}
SYSTEM_NAMES = {
    "hdfs": "HDFS 3.4.3",
    "hbase": "HBase 2.6.6",
    "solr": "Solr 8.11.4",
    "zookeeper": "ZooKeeper 3.8.7",
}


def normalize_trial_counts(record: dict, update: dict) -> None:
    """Map older case ledgers to the shared checklist column names.

    Keep the case's original fields in the JSON row for auditability. A missing
    coverage value is unknown, rather than evidence of zero additional sites.
    """
    aliases = {
        "strict_injections": (
            "strict_injection_trials", "fully_matched_fault_sequences"
        ),
        "coverage_gain": ("target_retaining_production_coverage_gain",),
    }
    for column, candidates in aliases.items():
        if column in update:
            continue
        for candidate in candidates:
            if candidate in update:
                record[column] = update[candidate]
                break
        else:
            if column == "coverage_gain" and update.get("fault_trials", 0):
                record[column] = None

    # The generic fuzzer has used target_after_fault for the fatal outcome,
    # whereas case reports use it for reachability. Prefer explicit reach
    # counters; the exact exception count remains in the original result.
    for candidate in ("post_fault_target_reach_trials",
                      "strict_target_after_fault_trials",
                      "target_check_after_fault_trials"):
        if candidate in update:
            record["target_after_fault"] = update[candidate]
            break

    # Some ledgers count fault *events* in strict_injections and others count
    # fully applied *sequences*. Derive a separate comparable trial count.
    for candidate in ("fully_applied_trials", "strict_injection_trials",
                      "fully_matched_fault_sequences", "matched_applied_trials"):
        if candidate in update:
            record["fully_applied_trials"] = update[candidate]
            break
    else:
        trials = update.get("trial_results")
        if isinstance(trials, list) and trials:
            record["fully_applied_trials"] = sum(
                trial.get("requested_faults", 0) > 0
                and trial.get("requested_faults") == trial.get("matched_faults")
                == trial.get("applied_faults")
                for trial in trials
            )
        elif isinstance(update.get("strict_injections"), int) and (
                update["strict_injections"] <= update.get("fault_trials", 0)):
            record["fully_applied_trials"] = update["strict_injections"]
        else:
            record["fully_applied_trials"] = None


def rows() -> list[dict]:
    selected = json.loads(SELECTION.read_text())
    result = []
    for entry in selected["checks"]:
            case_id = entry["case_id"]
            record = {
                "case_id": case_id,
                "system": entry["system"],
                "source_path": entry["source_path"],
                "source_line": entry["source_line"],
                "function": entry["function"],
                "check_code": entry.get("check_code"),
                "site_id": entry["site_id"],
                "proposed_cluster_test": entry.get("proposed_cluster_test"),
                "cluster_test": None,
                "status": "pending_test_search",
                "target_reached": None,
                "fault_trials": 0,
                "strict_injections": 0,
                "fully_applied_trials": 0,
                "target_after_fault": 0,
                "coverage_gain": 0,
                "elapsed_seconds": 0,
                "bug_mark": "none",
                "evidence": None,
            }
            path = RESULTS / case_id / "result.json"
            if path.exists():
                update = json.loads(path.read_text())
                if update.get("case_id") != case_id:
                    raise ValueError(f"wrong case_id in {path}")
                record.update(update)
                normalize_trial_counts(record, update)
            # Per-case results can use a short system key or a display name.
            # Keep the 102-row ledger consistent regardless of worker format.
            record["system"] = SYSTEM_NAMES[entry["system"].lower()]
            result.append(record)
    result.sort(key=lambda row: (row["system"], row["case_id"]))
    if len(result) != 102 or len({row["case_id"] for row in result}) != 102:
        raise ValueError("selection must contain exactly 102 distinct checks")
    return result


def markdown(items: list[dict]) -> str:
    def cell(value: object) -> str:
        if value is None:
            return ""
        return str(value).replace("|", "&#124;").replace("\n", "<br>")

    def evidence_cell(row: dict) -> str:
        case_dir = RESULTS / row["case_id"]
        result = case_dir / "result.json"
        if not result.exists():
            return cell(row.get("evidence"))
        links = [f"[result](cases/{row['case_id']}/result.json)"]
        for name in ("README.md", "REPORT.md"):
            if (case_dir / name).exists():
                links.append(f"[review](cases/{row['case_id']}/{name})")
                break
        return ", ".join(links)

    counts = Counter(row["status"] for row in items)
    lines = [
        "# Unit-test cluster fuzz checklist (102 checks)", "",
        "This is the new campaign. Legacy Docker trials are not counted.", "",
        "Case time uses total elapsed time when reported, including setup and review. "
        "Fully applied trials matched and injected every selected fault. "
        "Target after fault counts check reach, not target exceptions. "
        "Coverage gain is the case's reported feedback; its provenance is in the result.",
        "",
        "Status: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
        "", "| Check | System | Source | Function | Check code | Cluster test | "
        "Case time (s) | Fault trials | Fully applied trials | Target after fault | "
        "Coverage gain | Result | Bug | Evidence |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in items:
        line = row.get("resolved_check_line") or row["source_line"]
        source = f"{row['source_path']}:{line}"
        if line != row["source_line"]:
            source += f" (selection line {row['source_line']})"
        values = [row["case_id"], row["system"],
                  source, row["function"],
                  row.get("check_code"),
                  row.get("cluster_test") or row.get("proposed_cluster_test"),
                  row.get("total_elapsed_seconds") or row.get("elapsed_seconds"),
                  row.get("fault_trials"), row.get("fully_applied_trials"),
                  row.get("target_after_fault"),
                  row.get("coverage_gain"), row["status"], row.get("bug_mark")]
        lines.append("| " + " | ".join(map(cell, values)) + " | "
                     + evidence_cell(row) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("render", "pending", "summary"))
    args = parser.parse_args()
    items = rows()
    if args.command == "pending":
        for row in items:
            if row["status"] not in TERMINAL:
                print(row["case_id"])
    elif args.command == "summary":
        print(json.dumps(dict(Counter(row["status"] for row in items)),
                         sort_keys=True))
    else:
        (HERE / "checklist102.json").write_text(
            json.dumps({"schema_version": 1, "rows": items},
                       ensure_ascii=False, indent=2) + "\n")
        (HERE / "checklist102.md").write_text(markdown(items))
        print(f"rendered {len(items)} rows")


if __name__ == "__main__":
    main()
