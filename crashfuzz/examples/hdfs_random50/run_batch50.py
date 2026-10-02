"""Fuzz the forty additional random checks with per-site exact oracles."""

from __future__ import annotations

from dataclasses import replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(TEN))
from adhoc_crashfuzz.campaign import Campaign, Settings  # noqa: E402
from adhoc_crashfuzz.model import TargetSpec  # noqa: E402
from discover import TRANSPORT_METHODS  # noqa: E402
from run_batch import (DATA_TRANSFER_RECEIVE, classify_error, save,
                       trial_rows)  # noqa: E402


MODE_CONFIG = {
    "normal": TEN / "campaign.json",
    "special": TEN / "campaign_special.json",
    "cache": TEN / "campaign_cache.json",
    "rich": HERE / "campaign_rich.json",
    "quota": HERE / "campaign_quota.json",
    "snapshot": HERE / "campaign_snapshot.json",
    "diskbalancer": HERE / "campaign_diskbalancer.json",
    "qjm": HERE / "campaign_qjm.json",
    "crypto": HERE / "campaign_crypto.json",
    "corrupt": HERE / "campaign_corrupt.json",
}
PREFERRED = {
    11: "special", 13: "quota", 14: "diskbalancer", 16: "special", 20: "special", 21: "special",
    32: "qjm",
    44: "crypto",
    36: "corrupt",
    23: "special", 30: "rich", 34: "rich", 48: "special",
    49: "rich",
}


HADOOP_RPC_SERVER = (
    "org/apache/hadoop/ipc/Server$Connection#processRpcRequest("
    "Lorg/apache/hadoop/ipc/protobuf/RpcHeaderProtos$RpcRequestHeaderProto;"
    "Lorg/apache/hadoop/ipc/RpcWritable$Buffer;)V")


def properties_for(site: dict, extra_points: tuple[str, ...] = ()) -> tuple[str, str]:
    target = site["agent_method"]
    writers = site["writer_methods"][:2]
    methods = ({method.split("(", 1)[0]
                for method in [target] + writers + list(extra_points)}
               | TRANSPORT_METHODS)
    classes = {method.split("#", 1)[0] for method in methods}
    points = list(dict.fromkeys(
        [DATA_TRANSFER_RECEIVE, target] + writers + list(extra_points)))
    selected = (site.get("compiled_target_call")
                or site.get("compiled_target_throw"))
    if not selected:
        raise ValueError("no exact oracle for " + site["site_id"])
    lines = [
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "point.entries=" + ",".join(points),
        "trace.fields=true", "trace.branches=true",
        "coverage.blocks=true", "coverage.branches=true",
        "coverage.include.prefixes=org/apache/hadoop/hdfs/",
        "target.guard=",
        "adapter.hdfs.datatransfer=true", "adapter.hadoop.rpc=true",
    ]
    if site.get("compiled_target_call"):
        lines.extend(["target.entry=", "target.throw=",
                      "target.call=" + selected,
                      "target.exception=" + site["target_exception"]])
    else:
        lines.extend(["target.entry=" + target,
                      "target.throw=" + selected, "target.call="])
    return "\n".join(lines) + "\n", selected


def mode_for(site: dict) -> str | None:
    available = []
    for mode in MODE_CONFIG:
        path = HERE / ("out_discovery_" + mode) / "coverage.json"
        if path.exists():
            rows = json.loads(path.read_text())["rows"]
            if rows[site["draw"] - 1]["method_entered"]:
                available.append(mode)
    preferred = PREFERRED.get(site["draw"])
    if preferred in available:
        return preferred
    return next((mode for mode in ("normal", "rich", "quota", "special", "cache",
                                   "snapshot", "diskbalancer", "qjm",
                                   "crypto", "corrupt")
                 if mode in available), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=11)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--runs-per-target", type=int, default=2)
    args = parser.parse_args()
    if not 11 <= args.start <= 50 or args.limit < 1:
        raise ValueError("start must be 11..50; limit must be positive")
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    raw = (HERE / "mapped50.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    sites = json.loads(raw)["sites"]
    root = HERE / "out_batch"
    root.mkdir(exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    progress_path = root / "progress.json"
    progress = (json.loads(progress_path.read_text()) if progress_path.exists()
                else {"selection_sha256": digest, "targets": {}})
    if progress["selection_sha256"] != digest:
        raise RuntimeError("mapped50.json changed since campaign started")
    for site in sites[args.start - 1:args.start - 1 + args.limit]:
        name = "candidate-{:02d}".format(site["draw"])
        if name in progress["targets"]:
            print(name, "already recorded", flush=True)
            continue
        mode = mode_for(site)
        if mode is None:
            print(name, "deferred: method not entered in discovery", flush=True)
            continue
        directory = root / name
        if directory.exists():
            raise RuntimeError("unrecorded output exists: " + str(directory))
        content, oracle = properties_for(
            site, (HADOOP_RPC_SERVER,) if mode == "qjm" else ())
        properties = configs / (name + ".properties")
        properties.write_text(content)
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
        os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
            "dfs.namenode.acls.enabled": "true",
            "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
            **({"dfs.blocksize": 1048576}
               if mode in ("rich", "snapshot") else {}),
        })
        base = Settings.from_file(MODE_CONFIG[mode])
        settings = replace(base, target=TargetSpec(oracle),
                           output_dir=directory,
                           max_runs=args.runs_per_target,
                           random_seed=20261001 + site["draw"])
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "mode": mode, "oracle": oracle,
            "bytecode_status": site["bytecode_status"],
        }
        save(progress_path, progress)
        print(name, "starting", mode, oracle, flush=True)
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
