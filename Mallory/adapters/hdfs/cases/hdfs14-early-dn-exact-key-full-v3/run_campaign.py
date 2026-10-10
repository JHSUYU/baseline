#!/usr/bin/env python3
"""Run the pinned campaign with a strict gate on its own fresh healthy trace."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path[:0] = [str(CORE), str(BASE)]
from Mallory.core import campaign  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    expected_config = HERE / "HDFS-14-early-dn-exact-key-full-v3.json"
    if args.config.resolve() != expected_config or args.out != Path(
            "/tmp/mallory-hdfs14-early-dn-exact-key-v3-node2-full"):
        raise ValueError("unexpected HDFS-14 full campaign paths")

    original_apply = campaign._apply_result

    def gated_apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        if result["trial_id"] == 0 and 0 not in state["completed_trials"]:
            trial = Path(state["out"]) / "trials/r0000"
            reports = list((trial / "junit-reports").glob("*.xml"))
            if len(reports) != 1:
                raise RuntimeError("fresh HDFS-14 r0000 must have one exact JUnit report")
            subprocess.run(
                [sys.executable, str(HERE / "audit_healthy.py"),
                 "--events", str(trial / "events.jsonl.gz"),
                 "--junit", str(reports[0]), "--config", str(args.config),
                 "--out", str(trial / "hdfs14-observed-path-gate.json")],
                check=True,
            )
        original_apply(state, config, result, item)

    campaign._apply_result = gated_apply
    campaign.run(args.config, args.out)


if __name__ == "__main__":
    main()
