"""Retry uncovered checks with a workload that reaches their exact guard."""

from __future__ import annotations

from dataclasses import replace
import argparse
import json
import os
from pathlib import Path
import traceback

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import TargetSpec

from analyze_checks import guard_sites
from run_batch import agent_properties, classify_error, save, trial_rows


HERE = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("special", "ramdisk", "editlog",
                                         "editlog_corrected",
                                         "blocksender", "cache", "cachepool"))
    parser.add_argument("--runs-per-target", type=int, default=4)
    args = parser.parse_args()
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    draws = {"special": (1, 2), "ramdisk": (2,), "editlog": (4,),
             "editlog_corrected": (4,),
             "blocksender": (7,), "cache": (9,),
             "cachepool": (10,)}[args.mode]
    config_name = ("campaign.json" if args.mode == "blocksender" else
                   "campaign_special.json" if args.mode == "ramdisk" else
                   "campaign_editlog.json" if args.mode == "editlog_corrected" else
                   "campaign_" + args.mode + ".json")
    base = Settings.from_file(HERE / config_name)
    root = HERE / ("out_" + args.mode + "_batch")
    root.mkdir(exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    progress_path = root / "progress.json"
    progress = (json.loads(progress_path.read_text()) if progress_path.exists()
                else {"mode": args.mode, "targets": {}})
    sites = json.loads((HERE / "mapped10.json").read_text())["sites"]
    for draw in draws:
        site = sites[draw - 1]
        name = "candidate-{:02d}".format(draw)
        if name in progress["targets"]:
            print(name, "already recorded", flush=True)
            continue
        guards = guard_sites(site)
        # checkForGaps must enter the loop and inspect at least one stream.
        guard = guards[-1]
        properties = configs / (name + ".properties")
        content = agent_properties(site).replace(
            "target.guard=\n", "target.guard=" + guard + "\n").replace(
            "target.entry=" + site["agent_method"] + "\n", "target.entry=\n")
        properties.write_text(content)
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
        directory = root / name
        if directory.exists():
            raise RuntimeError("unrecorded output already exists: " + str(directory))
        settings = replace(base, target=TargetSpec(guard),
                           output_dir=directory,
                           max_runs=args.runs_per_target,
                           random_seed=20261001 + draw)
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "target_guard": guard,
            "target_throw": site["compiled_target_throw"],
        }
        save(progress_path, progress)
        print(name, "starting", guard, flush=True)
        error = ""
        try:
            summary = Campaign(settings).run()
        except Exception:
            summary = None
            error = traceback.format_exc()
        trials = trial_rows(directory)
        status = "complete" if summary is not None else classify_error(trials)
        progress["targets"][name].update({
            "status": status, "summary": summary, "trials": trials,
            "error": error[-3000:],
        })
        save(progress_path, progress)
        print(name, status, "trials", len(trials), "matched",
              sum(row["matched_actions"] for row in trials), flush=True)


if __name__ == "__main__":
    main()
