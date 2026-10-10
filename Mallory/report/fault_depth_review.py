"""Bind a completed campaign's fault-plan depth distribution to raw trial results."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path


TERMINAL = {"budget_exhausted", "queue_exhausted"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def review(campaign: Path) -> dict:
    result_path = campaign / "result.json"
    config_path = campaign / "config.json"
    checkpoint_path = campaign / "checkpoint.json"
    result = json.loads(result_path.read_text())
    config = json.loads(config_path.read_text())
    checkpoint = json.loads(checkpoint_path.read_text())
    count = result["fault_trials_completed"]
    if (result.get("status") not in TERMINAL or
            checkpoint.get("status") != result["status"] or
            result.get("case_id") != config.get("case_id") or
            not isinstance(count, int) or not 0 < count <= config["budget"]["trials"] or
            len(checkpoint["completed_trials"]) != count + 1):
        raise ValueError("campaign has no consistent natural full terminal")

    release = config["core_release"]
    if isinstance(release, dict):
        if "path" in release:
            release_path = Path(release["path"])
        elif "release_id" in release:
            if release["release_id"] != Path(release["release_id"]).name:
                raise ValueError("controller release_id must be a basename")
            repository = Path(__file__).resolve().parents[2]
            release_path = repository / "Mallory/dispatch/releases" / release["release_id"]
        else:
            raise ValueError("controller release has no path or release_id")
    else:
        release_path = Path(release)
    release_manifest_path = release_path / "manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text())
    if (release_manifest.get("release_id") != release_path.name or
            (isinstance(release, dict) and release.get("release_id", release_path.name) !=
             release_path.name) or
            (isinstance(release, dict) and
             release.get("manifest_sha256") != digest(release_manifest_path)) or
            digest(release_path / "Mallory/core/scheduler.py") !=
            release_manifest["files"]["Mallory/core/scheduler.py"]):
        raise ValueError("controller release or scheduler SHA differs")

    distribution = collections.Counter()
    trials = []
    for number in range(1, count + 1):
        path = campaign / "trials" / f"r{number:04d}" / "result.json"
        trial = json.loads(path.read_text())
        plan = trial.get("plan")
        if trial.get("case_id") != result["case_id"] or not isinstance(plan, list) or not plan:
            raise ValueError(f"invalid fault plan: {path}")
        depth = len(plan)
        if depth > config["budget"]["max_faults_per_trial"]:
            raise ValueError(f"fault plan exceeds configured depth: {path}")
        distribution[depth] += 1
        trials.append({"trial_id": number, "depth": depth, "result_sha256": digest(path)})

    return {
        "schema_version": 1,
        "case_id": result["case_id"],
        "scope": "fault_plan_depth_and_controller_provenance",
        "status": result["status"],
        "fault_trials_completed": count,
        "campaign_result_sha256": digest(result_path),
        "campaign_config_sha256": digest(config_path),
        "campaign_checkpoint_sha256": digest(checkpoint_path),
        "controller_release_id": release_path.name,
        "controller_release_manifest_sha256": digest(release_manifest_path),
        "scheduler_sha256": digest(release_path / "Mallory/core/scheduler.py"),
        "scheduler_policy_commit": config.get("mapping", {}).get("scheduler_policy_commit"),
        "single_fault_breadth_interval": config.get("single_fault_breadth_interval"),
        "multi_fault_exploration_interval": config.get("multi_fault_exploration_interval"),
        "depth_distribution": {str(key): distribution[key] for key in sorted(distribution)},
        "trials": trials,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = review(args.campaign)
    target = args.out
    if target.exists():
        if json.loads(target.read_text()) != payload:
            raise ValueError("existing fault depth review differs")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        with temporary.open("w") as output:
            json.dump(payload, output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
    print(json.dumps({key: value for key, value in payload.items() if key != "trials"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
