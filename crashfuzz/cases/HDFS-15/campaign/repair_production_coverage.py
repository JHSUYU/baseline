#!/usr/bin/env python3
"""Recount existing HDFS-15 JaCoCo runs using production classes only.

No JUnit or fault injection is replayed. The original TSV and result files
are archived before any replacement; the campaign checkpoint is retained.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from run_campaign import (CAMPAIGN, CASE, COVERAGE, HEALTHY, LEDGER, RESULT,
                          RSYNC, SSH, STATE, atomic_json, coverage_ids, now,
                          persist)

ARCHIVE = CAMPAIGN / "coverage-filter-repair-2026-10-06"


def kinds(values: set[str]) -> dict[str, int]:
    return {kind: sum(value.startswith(kind + "\t") for value in values)
            for kind in ("METHOD", "BRANCH_UNIT", "PROBE")}


def preserve(path: Path) -> None:
    relative = path.relative_to(CASE)
    archived = ARCHIVE / relative
    archived.parent.mkdir(parents=True, exist_ok=True)
    if not archived.exists() and path.is_file():
        shutil.copy2(path, archived)


def remote_recount(remote_output: Path) -> None:
    execution = remote_output.with_name("jacoco.exec")
    cmd = SSH + ["python3", str(CASE / "system-test/run_coverage.py"),
                 "--exec", str(execution), "--output", str(remote_output)]
    subprocess.run(cmd, check=True)
    subprocess.run(RSYNC + ["ZhenyuLi@node2:" + str(remote_output),
                            str(remote_output)], check=True)


def main() -> None:
    state = json.loads(STATE.read_text())
    paths = [STATE, RESULT, LEDGER, COVERAGE,
             HEALTHY / "healthy-summary.json"]
    for row in state["completed"]:
        paths.extend((Path(row["coverage"]),
                      CAMPAIGN / row["trial"] / "trial-result.json"))
    for path in paths:
        preserve(path)
    source = CASE / "system-test/CoverageDump.java"
    subprocess.run(RSYNC + [str(source),
                            "ZhenyuLi@node2:" + str(source)], check=True)

    summary = {"repaired_at_utc": now(), "reason":
               "Prior JaCoCo probe IDs included test-JAR classes; now restrict "
               "probes to the production classes actually analyzed from "
               "HDFS JARs plus two case-local source overrides.",
               "original_junit_replayed": False, "trials": []}
    remote_recount(COVERAGE)
    healthy_new = coverage_ids(COVERAGE)
    healthy_old = coverage_ids(ARCHIVE / COVERAGE.relative_to(CASE))
    summary["healthy_before"] = kinds(healthy_old)
    summary["healthy_after"] = kinds(healthy_new)
    union = set(healthy_new)
    for row in state["completed"]:
        output = Path(row["coverage"])
        remote_recount(output)
        ids = coverage_ids(output)
        original = coverage_ids(ARCHIVE / output.relative_to(CASE))
        admitted = row["strict_injection"] and row[
            "target_guard_after_last_fault"]
        fresh = ids - union if admitted else set()
        summary["trials"].append({"trial": row["trial"],
                                  "before": kinds(original),
                                  "after": kinds(ids),
                                  "old_new_coverage": row["new_coverage_count"],
                                  "new_coverage": len(fresh)})
        row["coverage_ids"] = len(ids)
        row["coverage_by_kind"] = kinds(ids)
        row["new_coverage_ids"] = sorted(fresh)
        row["new_coverage_count"] = len(fresh)
        if admitted:
            union.update(ids)
        atomic_json(CAMPAIGN / row["trial"] / "trial-result.json", row)

    healthy_summary_path = HEALTHY / "healthy-summary.json"
    healthy_summary = json.loads(healthy_summary_path.read_text())
    healthy_summary["coverage_ids_by_kind"] = kinds(healthy_new)
    healthy_summary["coverage_scope"] = (
        "production HDFS JAR classes and case-local source overrides only")
    healthy_summary["coverage_filter_repair"] = str(ARCHIVE.relative_to(CASE))
    atomic_json(healthy_summary_path, healthy_summary)
    result = json.loads(RESULT.read_text())
    result["healthy_production_coverage_ids"] = kinds(healthy_new)
    result["coverage_scope"] = healthy_summary["coverage_scope"]
    result["coverage_filter_repair"] = str(ARCHIVE.relative_to(CASE))
    atomic_json(RESULT, result)
    atomic_json(STATE, state)
    summary["current_trial_preserved"] = state["current"]
    summary["completed_trials_preserved"] = len(state["completed"])
    atomic_json(ARCHIVE / "repair-summary.json", summary)
    persist(state)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
