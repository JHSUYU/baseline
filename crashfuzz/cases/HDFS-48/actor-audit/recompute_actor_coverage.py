#!/usr/bin/env python3
"""Recompute production coverage for the actor-joined HDFS-48 trial subset.

The historical scheduler counted some unbound RPC faults. Re-evaluate its
late-novelty gate using only the independently admitted raw JaCoCo files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from audit_heartbeat_actor import CASE, HERE, HEALTHY


JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
DEPS = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3/share/hadoop")
M2 = Path("/users/ZhenyuLi/.m2/repository")
IND = CASE / "independent"
CLASS = IND / "build/classes"
OVERLAY = IND / "build/overlay"
JACOCO_CORE = M2 / "org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar"
ASM = [M2 / f"org/ow2/asm/{name}/9.6/{name}-9.6.jar"
       for name in ("asm", "asm-tree", "asm-commons")]
JARS = [DEPS / "hdfs/hadoop-hdfs-3.4.3.jar",
        DEPS / "hdfs/hadoop-hdfs-client-3.4.3.jar",
        DEPS / "common/hadoop-common-3.4.3.jar"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def covered(directory: Path) -> tuple[set[str], set[str]]:
    return tuple(set((directory / name).read_text().splitlines()) for name in
                 ("covered_methods.txt", "covered_branch_counts.txt"))


def recompute() -> dict:
    audit = json.loads((HERE / "heartbeat-actor-audit.json").read_text())
    if audit["actor_joined_heartbeat_trials"] != 107:
        raise AssertionError("actor audit must be complete before coverage")
    for path in [JDK, CLASS / "CoverageHdfs50.class", OVERLAY, JACOCO_CORE,
                 *ASM, *JARS]:
        if not path.exists():
            raise FileNotFoundError(path)
    seen_m, seen_b = covered(HEALTHY)
    seen_p = set((HEALTHY / "covered_probes.txt").read_text().splitlines())
    healthy = {"methods": len(seen_m), "branch_count_buckets": len(seen_b),
               "exact_probes": len(seen_p)}
    cp = ":".join(str(path) for path in [CLASS, JACOCO_CORE, *ASM])
    rows = []
    for receipt in audit["raw_trial_receipts"]:
        number = receipt["trial"]
        original = IND / f"evidence/runs/trial-{number:03d}/jacoco.exec"
        if not original.is_file():
            raise FileNotFoundError(original)
        with tempfile.TemporaryDirectory(prefix=f"hdfs48-coverage-{number:03d}-") as temporary:
            directory = Path(temporary)
            copied = directory / "jacoco.exec"
            shutil.copyfile(original, copied)
            with (directory / "covered_probes.txt").open("w") as stream:
                subprocess.run([str(JDK), "-cp", cp, "CoverageHdfs50", str(copied),
                                str(OVERLAY), *(str(path) for path in JARS)],
                               stdout=stream, check=True)
            methods, branches = covered(directory)
            probes = set((directory / "covered_probes.txt").read_text().splitlines())
        new_m, new_b = methods - seen_m, branches - seen_b
        new_p = probes - seen_p
        seen_m |= methods
        seen_b |= branches
        seen_p |= probes
        rows.append({"trial": number, "ordinal": len(rows) + 1,
                     "exec_sha256": sha(original),
                     "new_methods": len(new_m), "new_branch_count_buckets": len(new_b),
                     "new_exact_probes": len(new_p),
                     "cumulative_methods": len(seen_m),
                     "cumulative_branch_count_buckets": len(seen_b),
                     "cumulative_exact_probes": len(seen_p)})
    first80 = rows[:80]
    return {"case_id": "HDFS-48", "actor_joined_trials": len(rows),
            "healthy": healthy, "first_80_last_8": first80[-8:],
            "late_method_or_branch_novelty": any(row["new_methods"] or
                                                 row["new_branch_count_buckets"]
                                                 for row in first80[-8:]),
            "late_exact_probe_novelty": any(row["new_exact_probes"]
                                             for row in first80[-8:]),
            "at_80": {"methods": first80[-1]["cumulative_methods"],
                      "branch_count_buckets": first80[-1]["cumulative_branch_count_buckets"],
                      "exact_probes": first80[-1]["cumulative_exact_probes"]},
            "at_107": {"methods": rows[-1]["cumulative_methods"],
                       "branch_count_buckets": rows[-1]["cumulative_branch_count_buckets"],
                       "exact_probes": rows[-1]["cumulative_exact_probes"]},
            "reporter_class_sha256": sha(CLASS / "CoverageHdfs50.class"),
            "trial_coverage": rows}


if __name__ == "__main__":
    output = HERE / "heartbeat-actor-coverage.json"
    output.write_text(json.dumps(recompute(), indent=2, sort_keys=True) + "\n")
    print(output)
