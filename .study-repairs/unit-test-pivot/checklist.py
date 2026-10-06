#!/usr/bin/env python3
"""Render the 102-check unit-test campaign from isolated case results."""

from __future__ import annotations

from collections import Counter
import argparse
import json
import os
from pathlib import Path
import tempfile


HERE = Path(__file__).resolve().parent
SELECTION = HERE / "selection102.json"
RESULTS = HERE / "cases"
# Losing the target in every attempted sequence is a search gap. A later
# fault family or a larger budget may still yield a target-retaining trial.
TERMINAL = {"no_cluster_test", "no_usable_cluster_test", "source_excluded", "quality_complete",
            "confirmed_bug"}
SYSTEM_NAMES = {
    "hdfs": "HDFS 3.4.3",
    "hbase": "HBase 2.6.6",
    "solr": "Solr 8.11.4",
    "zookeeper": "ZooKeeper 3.8.7",
}


def atomic_write_text(path: Path, contents: str) -> None:
    """Publish a complete checklist even while case results arrive."""
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def normalize_trial_counts(record: dict, update: dict,
                           selection: dict) -> None:
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
    # A case report may use compact names for the resolved bytecode site.
    # Keep the full selection text in the checklist's source/code columns;
    # resolved locations and case-specific explanations remain in the row.
    if update.get("function"):
        record["reported_function"] = update["function"]
    if update.get("check_code"):
        record["reported_check_code"] = update["check_code"]
    record["function"] = selection["function"]
    record["check_code"] = selection.get("check_code")
    if not record.get("cluster_test") and update.get("cluster_tests"):
        record["cluster_test"] = ", ".join(update["cluster_tests"])
    if record.get("target_reached") is None:
        if "healthy_target_guard_reached" in update:
            record["target_reached"] = bool(update["healthy_target_guard_reached"])
        elif "healthy_target_checks" in update:
            record["target_reached"] = update["healthy_target_checks"] > 0
        elif isinstance(update.get("healthy_target"), dict):
            record["target_reached"] = bool(
                update["healthy_target"].get("exact_call_count", 0))
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
    if (record.get("coverage_gain") is None and
            isinstance(update.get("coverage"), dict)):
        gain = update["coverage"].get("gain")
        if isinstance(gain, dict) and isinstance(gain.get("total_ids"), int):
            record["coverage_gain"] = gain["total_ids"]
    if "admitted_coverage_gain" in update:
        record["coverage_gain"] = update["admitted_coverage_gain"]

    # The generic fuzzer has used target_after_fault for the fatal outcome,
    # whereas case reports use it for reachability. Prefer explicit reach
    # counters; the exact exception count remains in the original result.
    for candidate in ("post_fault_target_reach_trials",
                      "strict_target_after_fault_trials",
                      "strict_target_after_fault",
                      "target_check_after_fault_trials",
                      "target_after_fault_trials"):
        if candidate in update:
            record["target_after_fault"] = update[candidate]
            break

    # Some ledgers count fault *events* in strict_injections and others count
    # fully applied *sequences*. A phase-local matched_applied_trials must not
    # override a plausible full-case strict_injections count.
    for candidate in ("fully_applied_trials", "strict_trials",
                      "strict_injection_trials",
                      "fully_matched_fault_sequences", "strict_injections",
                      "matched_applied_trials"):
        if (candidate in update and
                (candidate != "strict_injections" or
                 update[candidate] <= update.get("fault_trials", 0))):
            record["fully_applied_trials"] = update[candidate]
            break
    else:
        trials = update.get("trial_results")
        if isinstance(trials, list) and trials:
            def exact(trial: dict) -> bool | None:
                if "strict_injection" in trial:
                    return bool(trial["strict_injection"])
                if "exact_order_applied" in trial:
                    return bool(trial["exact_order_applied"])
                requested = trial.get("requested_faults")
                if requested is not None:
                    return (requested > 0 and requested ==
                            trial.get("matched_faults") ==
                            trial.get("applied_faults"))
                return None

            indicators = [exact(trial) for trial in trials]
            if all(indicator is not None for indicator in indicators):
                record["fully_applied_trials"] = sum(indicators)
            elif isinstance(update.get("strict_injections"), int) and (
                    update["strict_injections"] <= update.get("fault_trials", 0)):
                record["fully_applied_trials"] = update["strict_injections"]
            else:
                record["fully_applied_trials"] = None
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
                normalize_trial_counts(record, update, entry)
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

    def coverage_cell(value: object) -> str:
        if isinstance(value, dict):
            return "<br>".join(f"{cell(key)}: {cell(amount)}"
                                  for key, amount in value.items())
        return cell(value)

    counts = Counter(row["status"] for row in items)
    lines = [
        "# Unit-test cluster fuzz checklist (102 checks)", "",
        "This is the new campaign. Legacy Docker trials and trials that load "
        "GraphChecker runtime or region-woven classes are not counted.", "",
        "Time uses total elapsed time when reported; otherwise it uses the "
        "case's measured duration (see the result for its scope). "
        "Fully applied trials matched and injected every selected fault. "
        "Target after fault counts check reach, not target exceptions. "
        "Coverage gain is the case's reported feedback; its provenance is in the result.",
        "New and resumed campaigns use 80 trials / at most 8 faults, with "
        "a conditional 128 / 10 extension when production method/branch coverage "
        "or stable I/O families still grow near the limit. Completed earlier budgets remain "
        "recorded as run; they are not replayed.",
        "",
        "Status: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
        "", "| Check | System | Source | Function | Check code | Cluster test | "
        "Reported time (s) | Fault trials | Fully applied trials | Target after fault | "
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
                  row.get("target_after_fault")]
        tail = [row["status"], row.get("bug_mark")]
        lines.append("| " + " | ".join(map(cell, values)) + " | "
                     + coverage_cell(row.get("coverage_gain")) + " | "
                     + " | ".join(map(cell, tail)) + " | "
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
        atomic_write_text(
            HERE / "checklist102.json",
            json.dumps({"schema_version": 1, "rows": items},
                       ensure_ascii=False, indent=2) + "\n")
        atomic_write_text(HERE / "checklist102.md", markdown(items))
        print(f"rendered {len(items)} rows")


if __name__ == "__main__":
    main()
