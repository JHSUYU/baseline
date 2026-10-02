"""Explore checks that appear only after a crash in the healthy workload."""

from __future__ import annotations

from dataclasses import replace
import argparse
import json
import os
from pathlib import Path
import traceback

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import TargetSpec

from run_batch50 import HADOOP_RPC_SERVER, MODE_CONFIG, properties_for
from run_batch import classify_error, save, trial_rows


HERE = Path(__file__).resolve().parent
LATE_WRITE_POINTS = (
    "org/apache/hadoop/hdfs/server/datanode/BlockReceiver#receivePacket()I",
    "org/apache/hadoop/hdfs/server/datanode/LocalReplicaInPipeline#"
    "setBytesAcked(J)V",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draws", default="17,18,41,43,47")
    parser.add_argument("--mode", choices=tuple(MODE_CONFIG), default="rich")
    parser.add_argument("--runs-per-target", type=int, default=6)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--late-write-points", action="store_true")
    parser.add_argument("--max-site-occurrence", type=int, default=0)
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if args.tag and not args.tag.replace("_", "").isalnum():
        raise ValueError("tag must contain only letters, digits, or underscores")
    if args.max_site_occurrence < 0:
        raise ValueError("max-site-occurrence must be nonnegative")
    draws = [int(value) for value in args.draws.split(",")]
    sites = json.loads((HERE / "mapped50.json").read_text())["sites"]
    root = HERE / ("out_recovery_" + args.mode
                   + ("_" + args.tag if args.tag else ""))
    root.mkdir(exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    progress_path = root / "progress.json"
    progress = (json.loads(progress_path.read_text()) if progress_path.exists()
                else {"mode": args.mode, "targets": {}})
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    for draw in draws:
        site = sites[draw - 1]
        name = "candidate-{:02d}".format(draw)
        if name in progress["targets"]:
            print(name, "already recorded", flush=True)
            continue
        output = root / name
        if output.exists():
            raise RuntimeError("unrecorded output exists: " + str(output))
        extra_points = ((HADOOP_RPC_SERVER,) if args.mode == "qjm" else ())
        if args.late_write_points:
            extra_points += LATE_WRITE_POINTS
        content, oracle = properties_for(site, extra_points)
        if args.late_write_points:
            content = "\n".join(
                "point.entries=" + ",".join(LATE_WRITE_POINTS)
                if line.startswith("point.entries=") else line
                for line in content.splitlines()) + "\n"
        properties = configs / (name + ".properties")
        properties.write_text(content)
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
        os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
            "dfs.namenode.acls.enabled": "true",
            "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
            **({"dfs.blocksize": 1048576}
               if args.mode in ("rich", "snapshot") else {}),
        })
        base = Settings.from_file(MODE_CONFIG[args.mode])
        settings = replace(base, target=TargetSpec(oracle), output_dir=output,
                           max_runs=args.runs_per_target,
                           allow_unreached_seed=True,
                           max_site_occurrence=args.max_site_occurrence,
                           random_seed=20261001 + draw + args.seed_offset)
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "oracle": oracle, "seed_offset": args.seed_offset,
            "late_write_points": args.late_write_points,
            "max_site_occurrence": args.max_site_occurrence,
        }
        save(progress_path, progress)
        print(name, "starting recovery search", flush=True)
        error = ""
        try:
            summary = Campaign(settings).run()
        except Exception:
            summary = None
            error = traceback.format_exc()
        trials = trial_rows(output)
        status = ("complete" if any(row["target_reached"] for row in trials)
                  else "searched_unreached") if summary is not None else classify_error(trials)
        progress["targets"][name].update({
            "status": status, "summary": summary, "trials": trials,
            "error": error[-3000:],
        })
        save(progress_path, progress)
        print(name, status, "trials", len(trials), "matched",
              sum(row["matched_actions"] for row in trials), flush=True)


if __name__ == "__main__":
    main()
