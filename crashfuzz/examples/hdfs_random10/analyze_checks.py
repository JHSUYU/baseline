"""Report whether the branch guarding each sampled throw actually ran."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from adhoc_crashfuzz.graph import read_events  # noqa: E402
from map_bytecode import CLASSPATH, HEADER, SECTION  # noqa: E402


# Bytecode offsets of the condition immediately guarding the selected athrow.
# For checkForGaps, either condition can lead to its final gap exception.
GUARD_OFFSETS = {
    1: (4,), 2: (9,), 3: (126,), 4: (27, 53), 5: (121,),
    6: (14,), 7: (745,), 8: (25,), 9: (544,), 10: (88,),
}
INSTRUCTION = re.compile(r"(?m)^\s+(\d+): (\S+)")


def guard_sites(site: dict) -> list[str]:
    command = ["javap", "-classpath", CLASSPATH, "-c", "-s", "-p",
               site["class"]]
    output = subprocess.run(command, capture_output=True, text=True,
                            timeout=60, check=True).stdout
    method = site["agent_method"].split("#", 1)[1].split("(", 1)[0]
    descriptor = site["agent_method"].split(method, 1)[1]
    matches = []
    for section in SECTION.split(output):
        header = HEADER.search(section)
        if (header is None or header.group(2) != descriptor
                or (method != "<init>" and
                    re.search(r"\b" + re.escape(method) + r"\(",
                              header.group(1)) is None)):
            continue
        if method == "<init>" and site["class"].split(".")[-1] not in header.group(1):
            continue
        branch_index = 0
        mapped = {}
        for pc, opcode in INSTRUCTION.findall(section):
            if opcode.startswith("if"):
                branch_index += 1
                mapped[int(pc)] = branch_index
        matches.append(mapped)
    if len(matches) != 1:
        raise RuntimeError("ambiguous method: " + site["agent_method"])
    offsets = GUARD_OFFSETS[site["draw"]]
    missing = set(offsets) - matches[0].keys()
    if missing:
        raise RuntimeError("guard bytecode offsets missing: " + str(missing))
    return [site["agent_method"] + "#B" + str(matches[0][offset])
            for offset in offsets]


def summarize_run(directory: Path, guards: list[str]) -> dict:
    events = read_events(directory / "traces")
    branch_counts = Counter((event.site, event.outcome)
                            for event in events if event.kind == "BRANCH"
                            and event.site in guards)
    return {guard: {
        "true": branch_counts[(guard, "true")],
        "false": branch_counts[(guard, "false")],
    } for guard in guards}


def main() -> None:
    sites = json.loads((HERE / "mapped10.json").read_text())["sites"]
    progress = json.loads((HERE / "out_batch/progress.json").read_text())
    report = {"checks": []}
    for site in sites:
        name = "candidate-{:02d}".format(site["draw"])
        guards = guard_sites(site)
        row = {"candidate": name, "site_id": site["site_id"],
               "guards": guards, "runs": []}
        for trial in progress["targets"].get(name, {}).get("trials", []):
            run_dir = HERE / "out_batch" / name / "runs" / trial["run_id"]
            row["runs"].append({
                "run_id": trial["run_id"],
                "matched_actions": trial["matched_actions"],
                "guard_outcomes": summarize_run(run_dir, guards),
                "target_fatal": trial["target_fatal"],
            })
        report["checks"].append(row)
    path = HERE / "out_batch/check_coverage.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    for row in report["checks"]:
        aggregate = Counter()
        for run in row["runs"]:
            for counts in run["guard_outcomes"].values():
                aggregate.update(counts)
        print(row["candidate"], "guards", len(row["guards"]),
              "true", aggregate["true"], "false", aggregate["false"])


if __name__ == "__main__":
    main()
