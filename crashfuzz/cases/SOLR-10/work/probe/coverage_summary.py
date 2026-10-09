#!/usr/bin/env python3
"""Merge eligible JaCoCo runs independently for each selected check."""

import json
from pathlib import Path
import subprocess


WORK = Path(__file__).resolve().parents[1]
CAMPAIGN = WORK / "evidence/campaign"
STATE = CAMPAIGN / "state.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_VERSION = "9.10.1"
CASES = ("SOLR-10", "SOLR-39", "SOLR-40")
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
CLASSPATH = ":".join(map(str, [
    WORK / "classes-probe", WORK / "lib/jacoco-core.jar",
    ASM_ROOT / "asm" / ASM_VERSION / f"asm-{ASM_VERSION}.jar",
    ASM_ROOT / "asm-tree" / ASM_VERSION / f"asm-tree-{ASM_VERSION}.jar",
    ASM_ROOT / "asm-commons" / ASM_VERSION / f"asm-commons-{ASM_VERSION}.jar",
]))


def summarize(files: list[Path]) -> dict:
    for item in files:
        if not item.exists():
            raise FileNotFoundError(item)
    cmd = [JAVA, "-cp", CLASSPATH, "baseline.solr103940.CoverageSummary",
           str(DIST), str(WORK / "classes-probe"), *map(str, files)]
    return json.loads(subprocess.check_output(cmd, text=True))


def main() -> None:
    state = json.loads(STATE.read_text())
    healthy = WORK / "evidence/healthy-instrumented/jacoco.exec"
    baseline = summarize([healthy])
    results = {}
    for case_id in CASES:
        eligible = [CAMPAIGN / f"trial-{t['number']:03d}" / "jacoco.exec"
                    for t in state["trials"]
                    if t["all_faults_applied"] and t["target_after_fault"][case_id]]
        combined = summarize([healthy, *eligible])
        results[case_id] = {
            "eligible_trials": len(eligible),
            "healthy_plus_eligible": combined,
            "new_covered_methods": combined["covered_methods"] - baseline["covered_methods"],
            "new_covered_branches": combined["covered_branches"] - baseline["covered_branches"],
            "target_guard_taken": any(t["all_faults_applied"] and
                                      t["target_after_fault"][case_id] and
                                      t["target_exception"][case_id]
                                      for t in state["trials"]),
        }
    result = {"completed_trials": len(state["trials"]), "healthy": baseline,
              "cases": results}
    output = CAMPAIGN / "coverage-summary.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    print(json.dumps({cid: {k: v for k, v in item.items()
                            if k != "healthy_plus_eligible"}
                      for cid, item in results.items()}, sort_keys=True))


if __name__ == "__main__":
    main()
