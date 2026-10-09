#!/usr/bin/env python3
"""Summarize production methods and branches in strict target-retaining trials."""

import json
from pathlib import Path
import subprocess


WORK = Path(__file__).resolve().parents[1]
CASE_ID = WORK.parent.name
STATE = WORK / "evidence/campaign/state.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
VERSION = "9.10.1"
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
CLASSPATH = ":".join(map(str, [
    WORK / "classes", WORK / "lib/jacoco-core.jar",
    ASM / "asm" / VERSION / f"asm-{VERSION}.jar",
    ASM / "asm-tree" / VERSION / f"asm-tree-{VERSION}.jar",
    ASM / "asm-commons" / VERSION / f"asm-commons-{VERSION}.jar",
]))


def summarize(files: list[Path]) -> dict:
    for item in files:
        if not item.exists():
            raise FileNotFoundError(item)
    command = [JAVA, "-cp", CLASSPATH, "baseline.solr06.CoverageSummary",
               str(DIST), str(WORK / "classes"), *map(str, files)]
    return json.loads(subprocess.check_output(command, text=True))


def has_coverage(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def main() -> None:
    state = json.loads(STATE.read_text())
    healthy = WORK / "evidence/healthy-instrumented/jacoco.exec"
    target_retaining = [trial for trial in state["trials"]
                        if trial["all_faults_applied"] and
                        trial["target_after_fault"][CASE_ID]]
    eligible = [WORK / "evidence/campaign" / f"trial-{trial['number']:03d}" / "jacoco.exec"
                for trial in target_retaining
                if has_coverage(WORK / "evidence/campaign" /
                                f"trial-{trial['number']:03d}" / "jacoco.exec")]
    excluded_without_coverage = [trial["number"] for trial in target_retaining
                                 if not has_coverage(WORK / "evidence/campaign" /
                                                     f"trial-{trial['number']:03d}" /
                                                     "jacoco.exec")]
    baseline = summarize([healthy])
    combined = summarize([healthy, *eligible])
    result = {
        "case_id": CASE_ID, "completed_trials": len(state["trials"]),
        "eligible_trials": len(eligible), "healthy": baseline,
        "target_retaining_trials_without_coverage": excluded_without_coverage,
        "healthy_plus_eligible": combined,
        "new_covered_methods": combined["covered_methods"] - baseline["covered_methods"],
        "new_covered_branches": combined["covered_branches"] - baseline["covered_branches"],
        "new_unmodified_covered_methods": (
            combined["unmodified_covered_methods"] - baseline["unmodified_covered_methods"]),
        "new_unmodified_covered_branches": (
            combined["unmodified_covered_branches"] - baseline["unmodified_covered_branches"]),
        "target_guard_taken": any(trial["all_faults_applied"] and
                                  trial["target_after_fault"][CASE_ID] and
                                  trial["target_exception"][CASE_ID]
                                  for trial in state["trials"]),
    }
    output = WORK / "evidence/campaign/coverage-summary.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("healthy", "healthy_plus_eligible")}, sort_keys=True))


if __name__ == "__main__":
    main()
