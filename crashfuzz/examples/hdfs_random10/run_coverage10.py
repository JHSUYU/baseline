"""Rerun the frozen ten HDFS checks with graph, block, and branch feedback."""

from __future__ import annotations

from dataclasses import replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import traceback

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import TargetSpec

from analyze_checks import guard_sites
from run_batch import agent_properties, save, trial_rows, classify_error


HERE = Path(__file__).resolve().parent
CAMPAIGN = {
    1: "campaign_special.json",
    2: "campaign_special.json",  # RAM_DISK case, run alone
    4: "campaign_editlog.json",
    9: "campaign_cache.json",
    10: "campaign_cachepool.json",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--runs-per-target", type=int, default=4)
    parser.add_argument("--max-site-occurrence", type=int, default=0)
    parser.add_argument("--output-name", default="out_coverage10")
    args = parser.parse_args()
    if not (1 <= args.start <= 10 and 1 <= args.limit <= 10
            and args.start + args.limit <= 11 and args.runs_per_target >= 2
            and args.max_site_occurrence >= 0
            and not Path(args.output_name).is_absolute()
            and Path(args.output_name).name == args.output_name):
        raise ValueError("select draws 1..10 and at least two runs per target")
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    selection_bytes = (HERE / "mapped10.json").read_bytes()
    sites = json.loads(selection_bytes)["sites"]
    root = HERE / args.output_name
    root.mkdir(exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    progress_path = root / "progress.json"
    expected_hash = hashlib.sha256(selection_bytes).hexdigest()
    progress = (json.loads(progress_path.read_text()) if progress_path.exists()
                else {"selection_sha256": expected_hash, "targets": {}})
    if progress["selection_sha256"] != expected_hash:
        raise RuntimeError("mapped10.json changed after coverage campaign began")
    for draw in range(args.start, args.start + args.limit):
        site = sites[draw - 1]
        name = "candidate-{:02d}".format(draw)
        if progress["targets"].get(name, {}).get("status") == "complete":
            print(name, "already complete", flush=True)
            continue
        directory = root / name
        if directory.exists():
            raise RuntimeError("existing incomplete run requires inspection: "
                               + str(directory))
        guards = guard_sites(site)
        guard = guards[-1]
        properties = configs / (name + ".properties")
        content = agent_properties(site).replace(
            "target.guard=\n", "target.guard=" + guard + "\n").replace(
            "target.entry=" + site["agent_method"] + "\n", "target.entry=\n")
        properties.write_text(content)
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
        base = Settings.from_file(HERE / CAMPAIGN.get(draw, "campaign.json"))
        settings = replace(base, target=TargetSpec(guard),
                           output_dir=directory,
                           max_runs=args.runs_per_target,
                           random_seed=20261001 + draw,
                           max_site_occurrence=args.max_site_occurrence,
                           allow_unreached_seed=True)
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "target_guard": guard,
            "target_throw": site["compiled_target_throw"],
            "campaign": CAMPAIGN.get(draw, "campaign.json"),
            "max_site_occurrence": args.max_site_occurrence,
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
        print(name, status, "trials", len(trials), "matched fault trials",
              sum(row["run_id"].startswith("run-") and row["triggered"]
                  for row in trials), "matched actions",
              sum(row["matched_actions"] for row in trials), flush=True)


if __name__ == "__main__":
    main()
