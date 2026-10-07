#!/usr/bin/env python3
"""Summarize Solr production method/branch coverage for valid V2 trials."""

import json
from pathlib import Path
import subprocess

from feedback import atomic_json


WORK = Path(__file__).resolve().parents[1]
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"
ANALYSIS = WORK / "coverage-analysis/classes"
OUTPUT = WORK / "evidence/campaign/coverage-summary.json"


def summary(files: list[Path], classpath: str) -> dict:
    result = subprocess.run(
        [JAVA, "-cp", classpath, "baseline.solr09.CoverageSummary",
         str(DIST), str(WORK / "classes"), *(str(file) for file in files)],
        text=True, capture_output=True, check=True)
    return json.loads(result.stdout.strip())


def main() -> None:
    state = json.loads((WORK / "evidence/campaign/state.json").read_text())
    if "finished_at" not in state:
        raise RuntimeError("Coverage summary requires the completed V2 checkpoint")
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    jacoco = WORK / "lib/jacoco-core.jar"
    app_cp = (WORK / "classpath.txt").read_text().strip()
    build_cp = f"{WORK / 'classes'}:{jacoco}:{app_cp}"
    subprocess.run([JAVAC, "-cp", build_cp, "-d", str(ANALYSIS),
                    str(WORK / "probe/CoverageSummary.java")], check=True)
    asm_core = ASM / "asm/9.10.1/asm-9.10.1.jar"
    asm_tree = ASM / "asm-tree/9.10.1/asm-tree-9.10.1.jar"
    run_cp = f"{ANALYSIS}:{jacoco}:{asm_core}:{asm_tree}:{app_cp}"
    healthy_execs = [WORK / "evidence/healthy-instrumented/jacoco.exec",
                     WORK / "evidence/healthy-instrumented-002/jacoco.exec"]
    valid = [trial for trial in state["trials"]
             if trial["all_faults_applied"] and trial["target_after_fault"]["SOLR-09"]]
    trial_execs = [WORK / trial["evidence"] / "jacoco.exec" for trial in valid]
    if any(not file.exists() for file in healthy_execs + trial_execs):
        raise RuntimeError("Missing healthy or valid-trial JaCoCo raw data")
    baseline = summary(healthy_execs, run_cp)
    cumulative = summary(healthy_execs + trial_execs, run_cp)
    keys = ("covered_methods", "covered_branches", "selected_delete_core_branches_covered")
    result = {
        "case_id": "SOLR-09", "identity_version": "actor-v2",
        "production_only": True,
        "healthy_runs": len(healthy_execs), "valid_trials": len(valid),
        "healthy": baseline, "cumulative": cumulative,
        "delta": {key: cumulative[key] - baseline[key] for key in keys},
        "note": "JaCoCo cumulative production method and branch counts; selected method is DeleteReplicaCmd.deleteCore. Probe feedback is recorded separately in the campaign result.",
    }
    atomic_json(OUTPUT, result)
    print(json.dumps({key: result[key] for key in (
        "healthy_runs", "valid_trials", "delta")}, sort_keys=True))


if __name__ == "__main__":
    main()
