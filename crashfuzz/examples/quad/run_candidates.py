"""Select workload-reached checks, then fuzz each with its own healthy seed."""

from __future__ import annotations

from dataclasses import replace
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import random
import traceback

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.graph import read_events
from adhoc_crashfuzz.model import TargetSpec


ROOT = Path(__file__).resolve().parent.parent
SYSTEMS = {
    "hbase": ("hbase_266", {"hm1", "hm2", "rs1", "rs2", "rs3"}),
    "zookeeper": ("zookeeper_387", {"zk1", "zk2", "zk3"}),
    "solr": ("solr_8114", {"solr1", "solr2"}),
}


def read_properties(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.startswith("#"))


def select(system: str, count: int) -> dict:
    directory, servers = SYSTEMS[system]
    example = ROOT / directory
    mapping = json.loads((example / "out_mapping/mapped.json").read_text())
    run = example / "out_branch_discovery/runs/seed-00001"
    result = json.loads((run / "result.json").read_text())
    first = result["workload_start_wall_ms"]
    last = result["workload_end_wall_ms"]
    branch_hits: dict[str, Counter] = defaultdict(Counter)
    for event in read_events(run / "traces"):
        if (event.kind == "BRANCH" and first <= event.wall_ms <= last
                and event.node in servers):
            branch_hits[event.site][(event.node, event.outcome)] += 1
    reachable = []
    for row in mapping["sites"]:
        hits = branch_hits.get(row["target_guard"])
        if hits:
            reachable.append({**row, "seed_guard_hits": sum(hits.values()),
                              "seed_guard_nodes": sorted({node for node, _ in hits}),
                              "seed_guard_outcomes": sorted({outcome for _, outcome in hits})})
    reachable.sort(key=lambda row: row["site_id"])
    rng = random.Random("20261002:" + system)
    picked = rng.sample(reachable, min(count, len(reachable)))
    selected = {
        "system": system, "requested": count,
        "mapped_direct": mapping["direct_mapped"],
        "classifier_decisions_sha256": mapping["decisions_sha256"],
        "workload_reached_server_guards": len(reachable),
        "selection_seed": "20261002:" + system,
        "cases": [{"draw": index, **row}
                  for index, row in enumerate(picked, 1)],
    }
    (example / "selected10.json").write_text(
        json.dumps(selected, indent=2, sort_keys=True) + "\n")
    return selected


def properties_for(example: Path, row: dict) -> Path:
    base = read_properties(example / "agent.properties")
    target = row["agent_method"]
    methods = {target} | set(row["writer_methods"])
    classes = set(base.get("include.classes", "").split(","))
    rules = set(base.get("method.rules", "").split(","))
    points = set(base.get("point.entries", "").split(","))
    classes.discard("")
    rules.discard("")
    points.discard("")
    for method in methods:
        classes.add(method.split("#", 1)[0])
        rules.add(method.split("(", 1)[0])
    points.add(target)
    base["include.classes"] = ",".join(sorted(classes))
    base["method.rules"] = ",".join(sorted(rules))
    base["point.entries"] = ",".join(sorted(points))
    base["target.guard"] = row["target_guard"]
    base["target.throw"] = row["target_throw"]
    config = example / "configs" / "target-{:02d}.properties".format(row["draw"])
    config.parent.mkdir(exist_ok=True)
    config.write_text("\n".join(key + "=" + value for key, value in base.items()) + "\n")
    return config


def summarize_case(output: Path, row: dict, summary: dict | None,
                   error: str = "") -> dict:
    runs = []
    for path in sorted((output / "runs").glob("*/result.json")):
        result = json.loads(path.read_text())
        sequence = result["sequence"]["actions"]
        injected = result["injected"]
        full = len(sequence) == len(injected)
        runs.append({
            "run_id": result["run_id"], "planned_actions": len(sequence),
            "injected_actions": len(injected),
            "fully_matched": full,
            "match_modes": [item["match_mode"] for item in injected],
            "target_reached": result["target_reached"],
            "target_fatal": result["target_fatal"],
            "target_hit_count": len(result.get("target_hits", [])),
            "checker_returncode": None if result["checker"] is None
            else result["checker"]["returncode"],
            "workload_returncode": result["workload"]["returncode"],
            "closure_branch_outcomes": result["closure_branch_outcomes"],
            "global_branch_outcomes": result["global_branch_outcomes"],
        })
    faults = [item for item in runs if item["planned_actions"]]
    matched = [item for item in faults if item["fully_matched"]]
    return {
        "draw": row["draw"], "site_id": row["site_id"],
        "guard": row["target_guard"], "throw": row["target_throw"],
        "status": "complete" if summary is not None else "error",
        "error": error, "summary": summary, "runs": runs,
        "fault_trials": len(faults), "fully_matched_fault_trials": len(matched),
        "exact_fault_trials": sum(all(mode == "exact" for mode in item["match_modes"])
                                  for item in matched),
        "matched_reaching_target": sum(item["target_reached"] for item in matched),
        "matched_target_fatal": sum(item["target_fatal"] for item in matched),
        "matched_checker_failures": sum(item["checker_returncode"] not in (0, None)
                                        for item in matched),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("system", choices=SYSTEMS)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--draws", default="",
                        help="comma-separated draw numbers for focused reruns")
    parser.add_argument("--max-runs", type=int, default=4)
    parser.add_argument("--matched-limit", type=int, default=2)
    parser.add_argument("--allow-shape-fallback", action="store_true")
    parser.add_argument("--variant", default="",
                        help="separate result/output suffix for a secondary run")
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    example = ROOT / SYSTEMS[args.system][0]
    selected_path = example / "selected10.json"
    selected = (json.loads(selected_path.read_text())
                if selected_path.exists() else select(args.system, args.count))
    if args.select_only:
        print(json.dumps({key: value for key, value in selected.items()
                          if key != "cases"}, sort_keys=True))
        return
    if args.variant and not args.variant.replace("_", "").isalnum():
        raise ValueError("variant must contain only letters, digits, underscores")
    suffix = "_" + args.variant if args.variant else ""
    result_path = example / ("results10" + suffix + ".json")
    results = json.loads(result_path.read_text()) if result_path.exists() else {
        "system": args.system, "selection": str(selected_path.name), "cases": []}
    cases = selected["cases"]
    if args.draws:
        draws = {int(item) for item in args.draws.split(",")}
        cases = [row for row in cases if row["draw"] in draws]
    elif args.limit:
        cases = [row for row in cases if args.start <= row["draw"]
                 < args.start + args.limit]
    else:
        cases = [row for row in cases if row["draw"] >= args.start]
    for row in cases:
        if any(item["draw"] == row["draw"] for item in results["cases"]):
            continue
        config = properties_for(example, row)
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(config.resolve())
        settings = replace(
            Settings.from_file(example / "campaign.json"),
            target=TargetSpec(row["target_guard"]),
            output_dir=(example / ("out_campaign" + suffix)
                        / "case-{:02d}".format(row["draw"])),
            max_runs=args.max_runs, max_faults=2, matched_trial_limit=args.matched_limit,
            max_site_occurrence=1, allow_unreached_seed=True,
            allow_site_occurrence_fallback=args.allow_shape_fallback,
            replay_count=1)
        print(args.system, "case", row["draw"], row["site_id"], flush=True)
        summary = None
        error = ""
        try:
            summary = Campaign(settings).run()
        except Exception:
            error = traceback.format_exc()
            (settings.output_dir / "error.txt").write_text(error)
        case = summarize_case(settings.output_dir, row, summary, error)
        results["cases"].append(case)
        result_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(args.system, "case", row["draw"], case["status"],
              "matched", case["fully_matched_fault_trials"],
              "target", case["matched_reaching_target"],
              "fatal", case["matched_target_fatal"], flush=True)


if __name__ == "__main__":
    main()
