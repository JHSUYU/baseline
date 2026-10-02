"""Run twenty frozen HBase 3.0.0 checks as independent target oracles."""

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


TRANSPORT_METHODS = {
    "org/apache/hadoop/hbase/ipc/NettyRpcDuplexHandler#writeRequest",
    "org/apache/hadoop/hbase/ipc/NettyRpcDuplexHandler#readResponse",
    "org/apache/hadoop/hbase/ipc/ServerRpcConnection#processRequest",
    "org/apache/hadoop/hbase/ipc/NettyServerCall#sendResponseIfReady",
    "org/apache/hadoop/hbase/ipc/CallRunner#run",
    "org/apache/hadoop/hbase/procedure2/ProcedureExecutor#submitProcedure",
    "org/apache/hadoop/hbase/procedure2/ProcedureExecutor#executeProcedure",
}


def method_rule(site: str) -> str:
    return site.split("(", 1)[0]


def owner(site: str) -> str:
    return site.split("#", 1)[0]


def properties(site: dict) -> str:
    target_method = site["agent_method"]
    points = [target_method] + site["writer_methods"][:2]
    methods = {method_rule(method) for method in points} | TRANSPORT_METHODS
    classes = {owner(method) for method in methods}
    return "\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "io.rules=", "point.entries=" + ",".join(dict.fromkeys(points)),
        "trace.fields=true", "trace.branches=true",
        "target.guard=", "target.entry=" + target_method,
        "target.throw=" + site["target_site"],
        "adapter.hbase248.rpc=true", "",
    ])


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def verify_docker(command: list[str]) -> None:
    """Check daemon access before archiving any result from a prior attempt."""
    try:
        result = subprocess.run(command + ["info", "--format", "{{.ServerVersion}}"],
                                text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Docker preflight failed: {}".format(error)) from error
    if result.returncode:
        raise RuntimeError("Docker preflight failed: "
                           + (result.stderr or result.stdout).strip())


def trial_rows(directory: Path) -> list[dict]:
    rows = []
    for path in sorted((directory / "runs").glob("*/result.json")):
        row = json.loads(path.read_text())
        rows.append({"run_id": row["run_id"],
                     "triggered": row["triggered"],
                     "injected": len(row["injected"]),
                     "injection_modes": [injected.get("match_mode", "exact")
                                         for injected in row["injected"]],
                     "target_reached": row["target_reached"],
                     "target_fatal": row["target_fatal"],
                     "workload_returncode": row["workload"]["returncode"],
                     "checker_returncode": None if row["checker"] is None
                     else row["checker"]["returncode"],
                     "closure_nodes": row["closure_nodes"],
                     "closure_edges": row["closure_edges"]})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-per-target", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--retry-unmatched", action="store_true",
                        help="rerun completed targets whose fault trial never injected")
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 20 or arguments.runs_per_target < 2:
        raise ValueError("limit must be 1..20 and runs-per-target at least 2")
    selection_path = HERE / "selected20.json"
    selection_sha256 = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    selection = json.loads(selection_path.read_text())
    sites = selection["sites"]
    if len(sites) != 20:
        raise RuntimeError("selection has fewer than 20 reached candidates")
    root = HERE / "out_batch"
    root.mkdir(parents=True, exist_ok=True)
    configs = root / "configs"
    configs.mkdir(exist_ok=True)
    base = Settings.from_file(HERE / "campaign.json")
    progress_path = root / "progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {
        "source_revision": "da418afa6973bf4222231c1d233410d8c18ac7ec",
        "old_scan_sha256": json.loads((HERE / "out_selection/mapped.json").read_text())["old_sha256"],
        "new_scan_sha256": json.loads((HERE / "out_selection/mapped.json").read_text())["new_sha256"],
        "selection_sha256": selection_sha256,
        "targets": {},
    }
    if progress.get("selection_sha256", selection_sha256) != selection_sha256:
        raise RuntimeError("selected20.json changed after batch started")
    progress["selection_sha256"] = selection_sha256
    docker_checked = False
    for index, site in enumerate(sites[:arguments.limit], 1):
        name = "candidate-{:03d}".format(index)
        prior = progress["targets"].get(name, {})
        if prior.get("status") == "complete":
            unmatched = not any(t["run_id"].startswith("run-")
                                and t["injected"] > 0
                                for t in prior.get("trials", []))
            baseline_fatal = any(t["run_id"].startswith("seed-")
                                 and t["target_fatal"]
                                 for t in prior.get("trials", []))
            if (not arguments.retry_unmatched or not unmatched
                    or baseline_fatal):
                print(name, "already complete", flush=True)
                continue
        if not docker_checked:
            verify_docker(base.backend.docker_command)
            docker_checked = True
        previous_attempts = list(prior.get("previous_attempts", []))
        if prior.get("status") == "complete":
            previous_attempts.append({
                "summary": prior.get("summary"),
                "trials": prior.get("trials", []),
                "error": prior.get("error", ""),
            })
        directory = root / name
        if directory.exists():
            suffix = 1
            archived = name + "-previous-" + str(suffix)
            while (root / archived).exists():
                suffix += 1
                archived = name + "-previous-" + str(suffix)
            directory.rename(root / archived)
            if previous_attempts:
                previous_attempts[-1]["archived_dir"] = archived
        config = configs / (name + ".properties")
        config.write_text(properties(site))
        os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(config)
        settings = replace(base, target=TargetSpec(site["target_site"]),
                           output_dir=directory,
                           max_runs=arguments.runs_per_target,
                           max_faults=1, replay_count=1,
                           matched_trial_limit=(1 if arguments.retry_unmatched
                                                else 0),
                           random_seed=index)
        progress["targets"][name] = {
            "status": "running", "site_id": site["site_id"],
            "old_site_id": site["old_site_id"],
            "target_site": site["target_site"],
            "seed_nodes": site["seed_nodes"],
            "previous_attempts": previous_attempts,
        }
        save(progress_path, progress)
        print(name, "starting", site["target_site"], flush=True)
        error = ""
        try:
            result = Campaign(settings).run()
        except Exception:
            result = None
            error = traceback.format_exc()
        trials = trial_rows(directory)
        progress["targets"][name].update({
            "status": "complete" if result is not None else "error",
            "summary": result, "trials": trials, "error": error[-3000:],
        })
        save(progress_path, progress)
        print(name, progress["targets"][name]["status"],
              "trials", len(trials),
              "injected", sum(t["injected"] for t in trials), flush=True)
    print("processed", len(progress["targets"]), "selected targets", flush=True)


if __name__ == "__main__":
    main()
