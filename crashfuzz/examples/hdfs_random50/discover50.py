"""Measure method entry coverage of all fifty random HDFS sites."""

from __future__ import annotations

from dataclasses import replace
import argparse
import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(TEN))
from adhoc_crashfuzz.campaign import Campaign, Settings  # noqa: E402
from adhoc_crashfuzz.graph import read_events  # noqa: E402
from adhoc_crashfuzz.model import FaultSequence  # noqa: E402
from discover import TRANSPORT_METHODS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("normal", "special", "cache",
                                         "rich", "quota", "snapshot", "diskbalancer",
                                         "qjm", "crypto", "corrupt"))
    args = parser.parse_args()
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
        **({"dfs.blocksize": 1048576}
           if args.mode in ("rich", "snapshot") else {}),
    })
    selection = json.loads((HERE / "mapped50.json").read_text())
    methods = ({site["agent_method"].split("(", 1)[0]
                for site in selection["sites"]} | TRANSPORT_METHODS)
    classes = {method.split("#", 1)[0] for method in methods}
    properties = HERE / ("agent-discovery-" + args.mode + ".properties")
    properties.write_text("\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "point.entries=", "trace.fields=false", "trace.branches=false",
        "target.guard=", "target.throw=", "adapter.hdfs.datatransfer=true",
        "adapter.hadoop.rpc=true", "",
    ]))
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
    config_name = ("campaign.json" if args.mode == "normal" else
                   "campaign_" + args.mode + ".json")
    settings = Settings.from_file((HERE if args.mode in ("rich", "quota", "snapshot",
                                                         "diskbalancer", "qjm",
                                                         "crypto", "corrupt")
                                  else TEN)
                                  / config_name)
    output = HERE / ("out_discovery_" + args.mode)
    trial = Campaign(replace(settings, output_dir=output))._trial(
        FaultSequence(), "discovery")
    events = read_events(output / "runs" / trial.run_id / "traces")
    entered = {event.site for event in events if event.kind == "METHOD_ENTER"}
    thrown = {event.site for event in events if event.kind == "THROW"}
    report = {
        "mode": args.mode,
        "run_id": trial.run_id,
        "workload_returncode": trial.workload.returncode,
        "checker_returncode": (None if trial.checker is None
                               else trial.checker.returncode),
        "rows": [{
            "draw": site["draw"], "site_id": site["site_id"],
            "method_entered": site["agent_method"] in entered,
            "target_throw_observed": (
                site["compiled_target_throw"] in thrown
                if site["compiled_target_throw"] else False),
        } for site in selection["sites"]],
    }
    (output / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    print(args.mode, "covered methods",
          sum(row["method_entered"] for row in report["rows"]), "/ 50")
    print("workload", report["workload_returncode"],
          "checker", report["checker_returncode"])


if __name__ == "__main__":
    main()
