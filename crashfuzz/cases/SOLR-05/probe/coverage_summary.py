#!/usr/bin/env python3
"""Report JaCoCo method/branch coverage for eligible SOLR-05 trials."""

import json
from pathlib import Path
import subprocess


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
STATE = EVIDENCE / "campaign/state.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
MAVEN = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_VERSION = "9.10.1"
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
CLASSPATH = ":".join(map(str, [
    CASE / "classes", CASE / "lib/jacoco-core.jar",
    MAVEN / "asm" / ASM_VERSION / f"asm-{ASM_VERSION}.jar",
    MAVEN / "asm-tree" / ASM_VERSION / f"asm-tree-{ASM_VERSION}.jar",
    MAVEN / "asm-commons" / ASM_VERSION / f"asm-commons-{ASM_VERSION}.jar",
]))


def summarize(files: list[Path]) -> dict:
    cmd = [JAVA, "-cp", CLASSPATH, "baseline.solr05.CoverageSummary",
           str(DIST), str(CASE / "classes"), *map(str, files)]
    return json.loads(subprocess.check_output(cmd, text=True))


def main() -> None:
    state = json.loads(STATE.read_text())
    healthy = EVIDENCE / "healthy-callsite/jacoco.exec"
    eligible = [EVIDENCE / "campaign" / f"trial-{t['number']:03d}" / "jacoco.exec"
                for t in state["trials"] if t["eligible_feedback"]]
    for item in [healthy, *eligible]:
        if not item.exists():
            raise FileNotFoundError(item)
    baseline = summarize([healthy])
    combined = summarize([healthy, *eligible])
    result = {
        "case_id": "SOLR-05",
        "total_completed_trials": len(state["trials"]),
        "eligible_trials": len(eligible),
        "healthy": baseline,
        "healthy_plus_eligible": combined,
        "new_covered_methods": combined["covered_methods"] - baseline["covered_methods"],
        "new_covered_branches": combined["covered_branches"] - baseline["covered_branches"],
        "target_guard_taken": any(t["target_exception"] for t in state["trials"]),
    }
    output = EVIDENCE / "campaign/coverage-summary.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
