"""Audit fault matching, exact throw or call events, and guarding branches."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(TEN))
from adhoc_crashfuzz.graph import read_events  # noqa: E402
from map_bytecode import CLASSPATH, HEADER, SECTION  # noqa: E402


INSTRUCTION = re.compile(r"(?m)^[ \t]+(\d+):[ \t]+(\S+)(?:[ \t]+(\d+))?")


def guard_sites(site: dict, bytecode: str) -> list[str]:
    if site.get("compiled_target_call"):
        return []
    method = site["agent_method"].split("#", 1)[1].split("(", 1)[0]
    descriptor = site["agent_method"].split(method, 1)[1]
    for section in SECTION.split(bytecode):
        header = HEADER.search(section)
        if header is None or header.group(2) != descriptor:
            continue
        declaration = header.group(1)
        if method == "<init>":
            if site["class"].split(".")[-1].split("$")[-1] not in declaration:
                continue
        elif re.search(r"\b" + re.escape(method) + r"\(", declaration) is None:
            continue
        instructions = [(int(pc), opcode, int(operand) if operand else None)
                        for pc, opcode, operand in INSTRUCTION.findall(section)]
        branches = []
        for pc, opcode, destination in instructions:
            if opcode.startswith("if"):
                branches.append((pc, destination, len(branches) + 1))
        selected_line = int(site["compiled_target_throw"].rsplit("#L", 1)[1])
        throw_offsets = [row["bytecode_offset"]
                         for row in site["compiled_throws"]
                         if row["source_line"] == selected_line]
        sites = set()
        for throw_pc in throw_offsets:
            guards = [row for row in branches
                      if row[1] is not None and row[0] < throw_pc < row[1]]
            if guards:
                nearest = max(guards, key=lambda row: row[0])
                sites.add(site["agent_method"] + "#B" + str(nearest[2]))
        return sorted(sites)
    raise RuntimeError("compiled method missing: " + site["agent_method"])


def main() -> None:
    sites = json.loads((HERE / "mapped50.json").read_text())["sites"]
    progress_path = HERE / "out_batch/progress.json"
    progress = (json.loads(progress_path.read_text())["targets"]
                if progress_path.exists() else {})
    cache = {}
    report = {"checks": []}
    for site in sites[10:]:
        name = "candidate-{:02d}".format(site["draw"])
        if site["class"] not in cache:
            cache[site["class"]] = subprocess.run(
                ["javap", "-classpath", CLASSPATH, "-c", "-l", "-s", "-p",
                 site["class"]], capture_output=True, text=True,
                timeout=60, check=True).stdout
        guards = guard_sites(site, cache[site["class"]])
        rows = []
        for trial in progress.get(name, {}).get("trials", []):
            run_dir = HERE / "out_batch" / name / "runs" / trial["run_id"]
            events = read_events(run_dir / "traces")
            branches = Counter((event.site, event.outcome)
                               for event in events if event.kind == "BRANCH"
                               and event.site in guards)
            oracle = site.get("compiled_target_call") or site["compiled_target_throw"]
            rows.append({
                "run_id": trial["run_id"],
                "matched_actions": trial["matched_actions"],
                "target_reached": trial["target_reached"],
                "target_fatal": trial["target_fatal"],
                # For throw targets this is a method-entry anchor; for
                # precondition targets it is the selected call itself.
                "target_anchor_events": sum(event.kind == "TARGET"
                                            and event.site == oracle
                                            for event in events),
                "exact_throws": sum(event.kind == "THROW"
                                    and event.site == oracle for event in events),
                "guard_outcomes": {
                    guard: {"true": branches[(guard, "true")],
                            "false": branches[(guard, "false")]}
                    for guard in guards},
            })
        report["checks"].append({
            "draw": site["draw"], "site_id": site["site_id"],
            "oracle": (site.get("compiled_target_call")
                       or site["compiled_target_throw"]),
            "guard_sites": guards, "runs": rows,
        })
    (HERE / "out_batch/check_coverage.json").write_text(
        json.dumps(report, indent=2) + "\n")
    for row in report["checks"]:
        if not row["runs"]:
            continue
        print("{:02d} runs={} matches={} anchors={} guards={} fatal={}".format(
            row["draw"], len(row["runs"]),
            sum(run["matched_actions"] for run in row["runs"]),
            sum(run["target_anchor_events"] for run in row["runs"]),
            sum(sum(outcome.values()) for run in row["runs"]
                for outcome in run["guard_outcomes"].values()),
            sum(run["target_fatal"] for run in row["runs"])))


if __name__ == "__main__":
    main()
