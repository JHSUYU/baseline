"""Combine discovery, target-branch, and matched-fault evidence for all 50 sites."""

from __future__ import annotations

import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(TEN))
from adhoc_crashfuzz.graph import read_events  # noqa: E402
from analyze_checks import guard_sites as first_ten_guards  # noqa: E402
from run_batch50 import MODE_CONFIG  # noqa: E402


FIRST_TEN_OUTPUTS = (
    "out_batch", "out_special_batch", "out_ramdisk_batch",
    "out_editlog_batch", "out_editlog_corrected_batch",
    "out_cache_batch", "out_cachepool_batch",
)


def run_dirs(site: dict):
    draw = site["draw"]
    name = "candidate-{:02d}".format(draw)
    roots = ([TEN / part for part in FIRST_TEN_OUTPUTS] if draw <= 10
             else [HERE / "out_batch"] + sorted(HERE.glob("out_recovery_*")))
    for root in roots:
        if not (root / name / "runs").is_dir():
            continue
        for result in sorted((root / name / "runs").glob("*/result.json")):
            yield root.name, result.parent, json.loads(result.read_text())


def main() -> None:
    sites = json.loads((HERE / "mapped50.json").read_text())["sites"]
    guards_file = HERE / "out_batch/check_coverage.json"
    if not guards_file.exists():
        raise RuntimeError("run analyze50.py before audit_all50.py")
    new_guards = {
        row["draw"]: row["guard_sites"]
        for row in json.loads(guards_file.read_text())["checks"]
    }
    discovered = {}
    for path in sorted(HERE.glob("out_discovery_*/coverage.json")):
        mode = path.parent.name.removeprefix("out_discovery_")
        if mode not in MODE_CONFIG:
            continue
        for row in json.loads(path.read_text())["rows"]:
            if row["method_entered"]:
                discovered.setdefault(row["draw"], []).append(mode)
    rows = []
    for site in sites:
        draw = site["draw"]
        guards = (first_ten_guards(site) if draw <= 10
                  else new_guards[draw])
        selected = (site.get("compiled_target_call")
                    or site.get("compiled_target_throw"))
        counts = {
            "healthy_seeds": 0, "planned_fault_trials": 0,
            "matched_fault_trials": 0, "mapped_guard_events": 0,
            "method_branch_events": 0,
            "exact_call_events": 0, "exact_throw_events": 0,
            "method_entry_events": 0, "fatal_trials": 0,
        }
        outputs = []
        for output, run_dir, result in run_dirs(site):
            run_id = result["run_id"]
            if run_id.startswith("seed-"):
                counts["healthy_seeds"] += 1
            elif run_id.startswith("run-"):
                counts["planned_fault_trials"] += 1
                counts["matched_fault_trials"] += bool(result["injected"])
            counts["fatal_trials"] += bool(result["target_fatal"])
            events = read_events(run_dir / "traces")
            counts["mapped_guard_events"] += sum(
                event.kind == "BRANCH" and event.site in guards
                for event in events)
            counts["method_branch_events"] += sum(
                event.kind == "BRANCH"
                and event.site.startswith(site["agent_method"] + "#B")
                for event in events)
            counts["exact_call_events"] += sum(
                event.kind == "TARGET" and event.site == selected
                for event in events) if site.get("compiled_target_call") else 0
            counts["exact_throw_events"] += sum(
                event.kind == "THROW" and event.site == selected
                for event in events)
            counts["method_entry_events"] += sum(
                event.kind == "METHOD_ENTER"
                and event.site == site["agent_method"] for event in events)
            outputs.append({"output": output, "run_id": run_id,
                            "matched_actions": len(result["injected"]),
                            "target_fatal": result["target_fatal"]})
        rows.append({
            "draw": draw, "site_id": site["site_id"],
            "method": site["agent_method"], "oracle": selected,
            "oracle_kind": "call" if site.get("compiled_target_call")
                           else "throw",
            "guard_sites": guards,
            "discovery_modes": discovered.get(draw, []),
            **counts, "runs": outputs,
        })
    report = {"population": 532, "sample_size": len(rows), "rows": rows}
    path = HERE / "audit50.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    for row in rows:
        print("{:02d} discovery={} seeds={} faults={}/{} branches={} guard={} call={} throw={}".format(
            row["draw"], ",".join(row["discovery_modes"]) or "-",
            row["healthy_seeds"], row["matched_fault_trials"],
            row["planned_fault_trials"], row["method_branch_events"],
            row["mapped_guard_events"],
            row["exact_call_events"], row["exact_throw_events"]))
    print("wrote", path)


if __name__ == "__main__":
    main()
