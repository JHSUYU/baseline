#!/usr/bin/env python3
"""Collect two clean original ShardSplitTest runs with the V2 agent."""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from run import run  # noqa: E402


def main() -> None:
    agent = HERE / "solrsubshard-actor-v2-agent.jar"
    if not agent.is_file():
        raise SystemExit("build V2 agent first")
    for number in (1, 2):
        out = HERE / f"healthy-{number:02d}"
        if (out / "run.json").is_file():
            metadata = json.loads((out / "run.json").read_text())
            if metadata["exit_code"] != 0:
                raise SystemExit(f"existing unhealthy seed: {out}")
            continue
        if run(out, agent_path=agent) != 0:
            raise SystemExit(f"healthy calibration failed: {out}")


if __name__ == "__main__":
    main()
