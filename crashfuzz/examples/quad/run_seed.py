"""Run one real cluster workload without faults for adapter reachability."""

from dataclasses import replace
import argparse
import json
import os
from pathlib import Path

from adhoc_crashfuzz.campaign import Campaign, Settings
from adhoc_crashfuzz.model import FaultSequence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("example", type=Path)
    parser.add_argument("--properties", default="agent.properties")
    parser.add_argument("--output", default="out_seed")
    args = parser.parse_args()
    directory = args.example.resolve()
    properties = (directory / args.properties).resolve()
    if not properties.is_file():
        raise RuntimeError("missing properties: " + str(properties))
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(properties)
    settings = replace(Settings.from_file(directory / "campaign.json"),
                       output_dir=directory / args.output)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    trial = Campaign(settings)._trial(FaultSequence(), "seed")
    result = json.loads((settings.output_dir / "runs" / trial.run_id
                         / "result.json").read_text())
    print(json.dumps({
        "run_id": trial.run_id,
        "workload_returncode": trial.workload.returncode,
        "checker_returncode": None if trial.checker is None
        else trial.checker.returncode,
        "target_reached": trial.closure.reached,
        "fault_points": len(trial.points),
        "global_blocks": result["global_blocks"],
        "global_branch_outcomes": result["global_branch_outcomes"],
    }, indent=2, sort_keys=True))
    if (trial.workload.returncode or trial.workload.timed_out
            or trial.checker is None or trial.checker.returncode
            or trial.checker.timed_out):
        raise SystemExit("seed workload or checker failed")


if __name__ == "__main__":
    main()
