#!/usr/bin/env python3
"""Hash every retained original-JUnit artifact at a completed V3 boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REQUIRED = ("manifest.json", "runtime_trace.jsonl", "junit.log", "jacoco.exec")
COVERAGE = ("covered_probes.txt", "covered_methods.txt",
            "covered_branch_counts.txt")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    checkpoint = HERE / "checkpoint.json"
    audit_file = HERE / "audit-v3.json"
    before = sha(checkpoint)
    state = json.loads(checkpoint.read_text())
    audit = json.loads(audit_file.read_text())
    errors = []
    if audit.get("checkpoint_sha256") != before or audit.get("errors"):
        errors.append("independent semantic audit does not match checkpoint")
    if audit.get("attempts") != len(state["completed"]):
        errors.append("semantic audit has different completed denominator")
    directories = [HERE / "healthy-a", HERE / "healthy-b", HERE / "pilot-01"]
    for number, trial in enumerate(state["completed"], 1):
        directory = HERE / "runs" / ("trial-%04d" % number)
        if Path(trial["run"]).resolve() != directory.resolve():
            errors.append("trial path/order mismatch " + str(number))
        directories.append(directory)
    files = {}
    total = 0
    coverage_unavailable = []
    for directory in directories:
        if not directory.is_dir():
            errors.append("missing raw directory " + str(directory))
            continue
        expected = set(REQUIRED)
        if directory.name.startswith("trial-"):
            expected.add("fault-plan.tsv")
        jacoco = directory / "jacoco.exec"
        if jacoco.is_file() and jacoco.stat().st_size:
            expected.update(COVERAGE)
        elif jacoco.is_file():
            manifest_file = directory / "manifest.json"
            manifest = json.loads(manifest_file.read_text()) if manifest_file.is_file() else {}
            if not directory.name.startswith("trial-"):
                errors.append("healthy or pilot run has empty JaCoCo data " + str(directory))
            else:
                number = int(directory.name.removeprefix("trial-"))
                trial = state["completed"][number - 1]
                if manifest.get("junit_exit") != 124 or trial.get("junit_exit") != 124:
                    errors.append("empty JaCoCo without matching raw JUnit timeout "
                                  + str(directory))
                elif any((directory / name).exists() for name in COVERAGE):
                    errors.append("coverage text exists despite empty JaCoCo "
                                  + str(directory))
                else:
                    coverage_unavailable.append({"trial": number, "junit_exit": 124,
                                                 "jacoco_bytes": 0})
        for name in expected:
            if not (directory / name).is_file():
                errors.append("missing raw artifact " + str(directory / name))
        for path in sorted(p for p in directory.iterdir() if p.is_file()):
            relative = str(path.relative_to(HERE))
            size = path.stat().st_size
            files[relative] = {"sha256": sha(path), "bytes": size}
            total += size
    if sha(checkpoint) != before:
        errors.append("checkpoint changed during raw hashing; retry at a stable boundary")
    result = {"schema": 1, "case": "HDFS-32", "original_junit": state["test"],
              "checkpoint_sha256": before, "semantic_audit_sha256": sha(audit_file),
              "completed_attempts": len(state["completed"]),
              "healthy_runs": 2, "pilot_runs_outside_budget": 1,
              "coverage_unavailable_due_to_junit_timeout": coverage_unavailable,
              "raw_file_count": len(files), "raw_total_bytes": total,
              "files": files, "errors": errors}
    if not errors:
        destination = HERE / "raw-inventory.json"
        pending = destination.with_name(destination.name + ".tmp")
        with pending.open("w") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(destination)
    print(json.dumps({key: result[key] for key in
                      ("completed_attempts", "raw_file_count", "raw_total_bytes", "errors")}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
