"""Fuzz each sampled HDFS check with its own target oracle and clean seed."""

from __future__ import annotations

from dataclasses import replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from adhoc_crashfuzz.campaign import Campaign, Settings  # noqa: E402
from adhoc_crashfuzz.model import TargetSpec  # noqa: E402
from discover import TRANSPORT_METHODS  # noqa: E402


DATA_TRANSFER_RECEIVE = (
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/"
    "SaslDataTransferServer#receive(Lorg/apache/hadoop/hdfs/net/Peer;"
    "Ljava/io/OutputStream;Ljava/io/InputStream;I"
    "Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)"
    "Lorg/apache/hadoop/hdfs/protocol/datatransfer/IOStreamPair;")


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def agent_properties(site: dict) -> str:
    target = site["agent_method"]
    writers = site["writer_methods"][:2]
    methods = ({method.split("(", 1)[0] for method in [target] + writers}
               | TRANSPORT_METHODS)
    classes = {method.split("#", 1)[0] for method in methods}
    points = list(dict.fromkeys([DATA_TRANSFER_RECEIVE, target] + writers))
    return "\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "point.entries=" + ",".join(points),
        "trace.fields=true", "trace.branches=true", "target.guard=",
        "target.entry=" + target,
        "target.throw=" + site["compiled_target_throw"],
        "adapter.hdfs.datatransfer=true", "adapter.hadoop.rpc=true", "",
    ])


def trial_rows(directory: Path) -> list[dict]:
    rows = []
    for path in sorted((directory / "runs").glob("*/result.json")):
        row = json.loads(path.read_text())
        rows.append({
            "run_id": row["run_id"],
            "planned_actions": len(row["sequence"]["actions"]),
            "matched_actions": len(row["injected"]),
            "match_modes": [event.get("match_mode", "exact")
                            for event in row["injected"]],
            "target_reached": row["target_reached"],
            "target_fatal": row["target_fatal"],
            "workload_returncode": row["workload"]["returncode"],
            "checker_returncode": (None if row["checker"] is None else
                                   row["checker"]["returncode"]),
            "closure_nodes": row["closure_nodes"],
            "closure_edges": row["closure_edges"],
        })
    return rows


def classify_error(rows: list[dict]) -> str:
    seed = next((row for row in rows if row["run_id"].startswith("seed-")), None)
    if seed is None:
        return "setup_error"
    if seed["workload_returncode"] or seed["checker_returncode"] not in (0, None):
        return "seed_failed"
    if not seed["target_reached"]:
        return "uncovered"
    if seed["target_fatal"]:
        return "baseline_fatal"
    return "error"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--runs-per-target", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10 or args.runs_per_target < 2:
        raise ValueError("limit must be 1..10 and runs per target >= 2")
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    selection_file = HERE / "mapped10.json"
    raw = selection_file.read_bytes()
    selection_hash = hashlib.sha256(raw).hexdigest()
    sites = json.loads(raw)["sites"]
    root = HERE / "out_batch"
    root.mkdir(exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    progress_path = root / "progress.json"
    progress = (json.loads(progress_path.read_text()) if progress_path.exists()
                else {"selection_sha256": selection_hash, "targets": {}})
    if progress["selection_sha256"] != selection_hash:
        raise RuntimeError("mapped10.json changed after batch began")
    base = Settings.from_file(HERE / "campaign.json")
    result = subprocess.run(base.backend.docker_command + [
        "info", "--format", "{{.ServerVersion}}"], capture_output=True,
        text=True, timeout=15)
    if result.returncode:
        raise RuntimeError("Docker daemon unavailable: " + result.stderr)
    for site in sites[:args.limit]:
        name = "candidate-{:02d}".format(site["draw"])
        if name in progress["targets"]:
            print(name, "already recorded", flush=True)
            continue
        if site["compiled_target_throw"] is None:
            progress["targets"][name] = {
                "status": "oracle_unmapped", "site_id": site["site_id"]}
            save(progress_path, progress)
            continue
        directory = root / name
        if directory.exists():
            raise RuntimeError("unrecorded output already exists: " + str(directory))
        properties = configs / (name + ".properties")
        properties.write_text(agent_properties(site))
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
        settings = replace(base, target=TargetSpec(site["compiled_target_throw"]),
                           output_dir=directory,
                           max_runs=args.runs_per_target,
                           random_seed=20261001 + site["draw"])
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "agent_method": site["agent_method"],
            "target_throw": site["compiled_target_throw"],
            "site_kind": site["site_kind"],
        }
        save(progress_path, progress)
        print(name, "starting", site["agent_method"], flush=True)
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
