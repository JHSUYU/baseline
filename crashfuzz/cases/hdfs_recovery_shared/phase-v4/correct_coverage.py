#!/usr/bin/env python3
"""Recompute saved campaign feedback using released production classes only.

The original JaCoCo exec files remain untouched. The earlier derived text
included fresh Mockito-generated class names under Hadoop's package prefix,
which are not comparable from one JUnit process to the next.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import zipfile

import campaign
import run_original


HERE = Path(__file__).resolve().parent
CATEGORIES = ("probes", "methods", "branch_counts", "lines")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def class_name(value: str, category: str) -> str:
    return value.rsplit(":", 1)[0] if category == "lines" else value.split("#", 1)[0]


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if state.get("stop_reason") != "operator_pause" or state.get("active") is not None:
        raise RuntimeError("pause campaign at completed-trial boundary first")
    if (HERE / "coverage-correction.json").exists():
        raise RuntimeError("coverage correction already recorded")
    raw_state = campaign.STATE.read_bytes()
    with gzip.open(HERE / "campaign-state.before-coverage-correction.json.gz", "wb") as backup:
        backup.write(raw_state)

    allowed = set()
    for archive_path in (run_original.HDFS, run_original.HDFS_CLIENT, run_original.COMMON):
        with zipfile.ZipFile(archive_path) as archive:
            allowed.update(entry[:-6] for entry in archive.namelist()
                           if entry.endswith(".class"))
    directories = list(dict.fromkeys(
        [Path(x) for x in state["healthy_dirs"]]
        + [Path(trial["run"]) for trial in state["completed"]]))
    evidence = []
    for directory in directories:
        before_after = {}
        for category in CATEGORIES:
            path = directory / ("covered_" + category + ".txt")
            original = path.read_bytes()
            values = original.decode().splitlines()
            kept = sorted(set(value for value in values
                              if class_name(value, category) in allowed))
            revised = ("\n".join(kept) + "\n").encode() if kept else b""
            path.write_bytes(revised)
            before_after[category] = {
                "old_count": len(values), "new_count": len(kept),
                "old_sha256": sha256(original), "new_sha256": sha256(revised),
            }
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for category in CATEGORIES:
            manifest["covered_" + category + "_count"] = before_after[category]["new_count"]
        manifest["coverage_scope"] = "released_hadoop_hdfs_hdfs_client_common_classes_only"
        campaign.atomic_json(manifest_path, manifest)
        evidence.append({"run": str(directory), "counts": before_after})

    baseline = {category: set() for category in campaign.COVERAGE}
    for directory in map(Path, state["healthy_dirs"]):
        for category in campaign.COVERAGE:
            baseline[category].update(campaign.covered(directory, category))
    state["healthy_coverage"] = {key: sorted(value) for key, value in baseline.items()}
    accumulated = {case: {key: set(value) for key, value in baseline.items()}
                   for case in campaign.CASES}
    for trial in state["completed"]:
        directory = Path(trial["run"])
        run_coverage = {category: campaign.covered(directory, category)
                        for category in campaign.COVERAGE}
        for case in campaign.CASES:
            retained = bool(trial["post_fault_target_checks"][case])
            trial["coverage_gain"][case] = {
                category: len(run_coverage[category] - accumulated[case][category])
                if retained else 0 for category in campaign.COVERAGE}
            if retained:
                for category in campaign.COVERAGE:
                    accumulated[case][category].update(run_coverage[category])
    state["coverage"] = {
        case: {key: sorted(value) for key, value in categories.items()}
        for case, categories in accumulated.items()}

    by_id = {trial["id"]: trial for trial in state["completed"]}
    reweighted = 0
    for item in state["queue"]:
        if len(item["sequence"]) == 1:
            item["priority"] = item.get("retry", 0)
            reweighted += 1
            continue
        parent = by_id.get(campaign.sequence_id(item["sequence"][:-1]))
        if parent is None:
            continue
        item["priority"] = (sum(g["probes"] for g in parent["coverage_gain"].values())
                            + 50 * any(parent["new_io_families"].values())
                            + 3 * len(parent["sequence"]) + item.get("retry", 0))
        reweighted += 1
    correction = {
        "reason": "generated Mockito classes had random names under Hadoop package prefix",
        "raw_state_sha256": sha256(raw_state),
        "released_jars": [str(run_original.HDFS), str(run_original.HDFS_CLIENT),
                          str(run_original.COMMON)],
        "stable_class_count": len(allowed),
        "completed_trial_count": len(state["completed"]),
        "reweighted_queued_sequences": reweighted,
        "stable_probe_gain": {case: len(state["coverage"][case]["probes"])
                              - len(state["healthy_coverage"]["probes"])
                              for case in campaign.CASES},
        "runs": evidence,
    }
    campaign.atomic_json(campaign.STATE, state)
    campaign.write_result(state)
    campaign.atomic_json(HERE / "coverage-correction.json", correction)
    print(json.dumps({key: correction[key] for key in
                      ("completed_trial_count", "reweighted_queued_sequences",
                       "stable_probe_gain")}, sort_keys=True))


if __name__ == "__main__":
    main()
