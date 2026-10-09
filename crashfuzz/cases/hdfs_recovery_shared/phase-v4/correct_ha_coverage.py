#!/usr/bin/env python3
"""Filter the separate original HA-JUnit pilot to released production classes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import campaign
import run_original


HERE = Path(__file__).resolve().parent
RUNS = ("healthy-ha-failover-resources", "ha-smoke-file", "ha-smoke-file-b")
CATEGORIES = ("probes", "methods", "branch_counts", "lines")


def main() -> None:
    correction_path = HERE / "ha-coverage-correction.json"
    if correction_path.exists():
        raise RuntimeError("HA pilot coverage already corrected")
    allowed = set()
    for archive_path in (run_original.HDFS, run_original.HDFS_CLIENT, run_original.COMMON):
        with zipfile.ZipFile(archive_path) as archive:
            allowed.update(name[:-6] for name in archive.namelist()
                           if name.endswith(".class"))
    records = []
    for label in RUNS:
        directory = HERE / label
        before_after = {}
        for category in CATEGORIES:
            path = directory / ("covered_" + category + ".txt")
            raw = path.read_bytes()
            values = raw.decode().splitlines()
            kept = sorted(set(value for value in values
                              if (value.rsplit(":", 1)[0] if category == "lines"
                                  else value.split("#", 1)[0]) in allowed))
            revised = ("\n".join(kept) + "\n").encode() if kept else b""
            path.write_bytes(revised)
            before_after[category] = {
                "old_count": len(values), "new_count": len(kept),
                "old_sha256": hashlib.sha256(raw).hexdigest(),
                "new_sha256": hashlib.sha256(revised).hexdigest(),
            }
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for category in CATEGORIES:
            manifest["covered_" + category + "_count"] = before_after[category]["new_count"]
        manifest["coverage_scope"] = "released_hadoop_hdfs_hdfs_client_common_classes_only"
        campaign.atomic_json(manifest_path, manifest)
        records.append({"run": str(directory), "counts": before_after})
    healthy = HERE / RUNS[0]
    faulted = HERE / RUNS[-1]
    gain = {category: len(campaign.covered(faulted, category)
                          - campaign.covered(healthy, category))
            for category in campaign.COVERAGE}
    trial_path = faulted / "evaluation.json"
    trial = json.loads(trial_path.read_text())
    old_gain = trial["coverage_gain"]
    for case in campaign.CASES:
        trial["coverage_gain"][case] = gain.copy()
    campaign.atomic_json(trial_path, trial)
    pilot_path = HERE / "ha-pilot-evidence.json"
    pilot = json.loads(pilot_path.read_text())
    for case in campaign.CASES:
        pilot["coverage_gain"][case] = gain.copy()
    pilot["coverage_scope"] = "released_hadoop_hdfs_hdfs_client_common_classes_only"
    campaign.atomic_json(pilot_path, pilot)
    campaign.atomic_json(correction_path, {
        "reason": "exclude random Mockito classes and test-only classes from production coverage",
        "previous_gain": old_gain, "corrected_gain": gain,
        "raw_jacoco_exec_files_untouched": True, "runs": records,
    })
    print(json.dumps(gain, sort_keys=True))


if __name__ == "__main__":
    main()
