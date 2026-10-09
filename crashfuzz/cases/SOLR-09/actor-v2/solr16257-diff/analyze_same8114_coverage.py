#!/usr/bin/env python3
"""Recompute production JaCoCo method/branch feedback for same-version A/B."""

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASE = ROOT.parent
STAGE = ROOT / "same8114-causal"
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
CLASSPATH = ":".join([
    str(CASE / "coverage-analysis/classes"),
    str(CASE / "lib/jacoco-core.jar"),
    str(ASM / "asm/9.10.1/asm-9.10.1.jar"),
    str(ASM / "asm-tree/9.10.1/asm-tree-9.10.1.jar"),
    (CASE / "classpath.txt").read_text().strip(),
])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(mode: str, names: list[str]) -> dict:
    paths = [STAGE / "evidence" / name / "jacoco.exec" for name in names]
    if any(not path.is_file() for path in paths):
        raise RuntimeError("missing JaCoCo raw file")
    output = subprocess.run([
        "/usr/lib/jvm/java-8-openjdk-amd64/bin/java", "-cp", CLASSPATH,
        "baseline.solr09.CoverageSummary", str(DIST),
        str(STAGE / (mode + "-classes")), *(str(path) for path in paths),
    ], capture_output=True, text=True, check=True)
    return json.loads(output.stdout.strip())


def main() -> None:
    result = {"case_id": "SOLR-09", "purpose": "independent diagnostic, not fuzz budget",
              "production_only": True, "modes": {}}
    for mode in ("baseline", "causal"):
        healthy = mode + "-healthy-01"
        fault = mode + "-fault-01"
        receipts = [json.loads((STAGE / "evidence" / name / "receipt.json").read_text())
                    for name in (healthy, fault)]
        if receipts[0]["exit_code"] != 0 or receipts[1]["exit_code"] != 0:
            raise RuntimeError("one JUnit failed; inspect raw before coverage comparison")
        if not receipts[1]["trace_review"]["strict_same_actor_posttarget"]:
            raise RuntimeError("fault run lacks strict full-plan selected target")
        healthy_counts = summarize(mode, [healthy])
        fault_counts = summarize(mode, [fault])
        union_counts = summarize(mode, [healthy, fault])
        keys = ("covered_methods", "covered_branches",
                "selected_delete_core_branches_covered")
        result["modes"][mode] = {
            "healthy": healthy_counts, "fault": fault_counts, "union": union_counts,
            "fault_increment_over_healthy": {
                key: union_counts[key] - healthy_counts[key] for key in keys},
            "raw_jacoco_sha256": {
                name: sha256(STAGE / "evidence" / name / "jacoco.exec")
                for name in (healthy, fault)},
        }
    (STAGE / "coverage_summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({mode: data["fault_increment_over_healthy"]
                      for mode, data in result["modes"].items()}), flush=True)


if __name__ == "__main__":
    main()
