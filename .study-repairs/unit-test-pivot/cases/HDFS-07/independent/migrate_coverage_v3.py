#!/usr/bin/env python3
"""Recompute saved JaCoCo feedback using only release Hadoop classes."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import campaign
import run_original

HERE = Path(__file__).resolve().parent
STATE = campaign.STATE
SNAPSHOT = HERE / "evidence/campaign-state.pre-production-coverage.json"
RECORD = HERE / "evidence/coverage-migration-v3.json"
CATEGORIES = ("probes", "methods", "branch_counts", "lines")


def production_names() -> set[str]:
    names = set()
    for path in (run_original.HDFS, run_original.CLIENT, run_original.COMMON):
        with ZipFile(path) as jar:
            names.update(entry.filename[:-6] for entry in jar.infolist()
                         if entry.filename.endswith(".class"))
    return names


def recompute(run: Path, production: set[str]) -> dict[str, set[str]]:
    # The old run's overlay may have a different bytecode CRC, so filter its
    # already recorded probe IDs instead of reanalyzing JaCoCo with today's
    # overlay. Method and branch text was production-only from the outset.
    file = run / "covered_probes.txt"
    old = set(file.read_text().splitlines())
    filtered = {probe for probe in old if probe.rsplit("#", 1)[0] in production}
    temporary = file.with_suffix(".txt.tmp")
    temporary.write_text("".join(probe + "\n" for probe in sorted(filtered)))
    temporary.replace(file)
    values = {name: campaign.covered(run, name) for name in CATEGORIES}
    assert values["probes"] == filtered
    return values


def main() -> None:
    state = json.loads(STATE.read_text())
    if state.get("production_coverage_revision") == 3:
        print("HDFS-07 coverage revision 3 already applied")
        return
    if not SNAPSHOT.exists():
        shutil.copy2(STATE, SNAPSHOT)
    original = json.loads(SNAPSHOT.read_text())
    assert list(state["completed"]) == list(original["completed"])

    production = production_names()
    healthy = recompute(campaign.HEALTHY, production)
    assert len(healthy["branch_counts"]) == state["healthy"]["branch_count"]
    aggregate = {name: set(values) for name, values in healthy.items()}
    differences = []
    # The checkpoint JSON sorts dictionary keys for stable serialization.
    # Coverage gains must be reconstructed in actual execution order.
    completion_order = []
    for line in (HERE / "evidence/campaign.log").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        identity = event.get("id")
        if "completed" in event and identity in state["completed"] and identity not in completion_order:
            completion_order.append(identity)
    assert set(completion_order) == set(state["completed"])
    for identity in completion_order:
        trial = state["completed"][identity]
        run = Path(trial["manifest"]).parent
        values = recompute(run, production)
        old = dict(trial["coverage_gain"])
        trial["coverage_total"] = {name: len(values[name]) for name in CATEGORIES}
        trial["coverage_gain"] = {
            name: len(values[name] - aggregate[name]) if trial["valid_for_feedback"] else 0
            for name in CATEGORIES
        }
        if trial["valid_for_feedback"]:
            for name in CATEGORIES:
                aggregate[name].update(values[name])
        assert old["methods"] == trial["coverage_gain"]["methods"], identity
        assert old["branch_counts"] == trial["coverage_gain"]["branch_counts"], identity
        differences.append({"id": identity, "old_probe_gain": old["probes"],
                            "production_probe_gain": trial["coverage_gain"]["probes"]})
    state["coverage"] = {name: sorted(values) for name, values in aggregate.items()}
    state["production_coverage_revision"] = 3
    campaign.atomic_json(STATE, state)
    campaign.update_result(state)
    campaign.atomic_json(RECORD, {
        "case_id": "HDFS-07", "completed_preserved": len(state["completed"]),
        "original_checkpoint": str(SNAPSHOT),
        "healthy_old_probe_count": original["healthy"]["probe_count"]
        if "probe_count" in original["healthy"] else None,
        "healthy_production_probe_count": len(healthy["probes"]),
        "method_and_branch_gains_unchanged": True,
        "differences": differences,
    })
    print("recomputed", len(state["completed"]), "trials; healthy production probes", len(healthy["probes"]))


if __name__ == "__main__":
    main()
