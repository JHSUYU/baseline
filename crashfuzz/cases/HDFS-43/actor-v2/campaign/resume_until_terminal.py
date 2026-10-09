#!/usr/bin/env python3
"""Keep the HDFS-43 checkpointed campaign alive across node2 gate pauses."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_campaign.py"
STATE = HERE / "checkpoint.json"
LOG = HERE / "campaign-driver.log"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    env = dict(os.environ)
    env.pop("HDFS43_STOP_AFTER", None)
    while True:
        with LOG.open("a") as stream:
            stream.write(f"{stamp()} resume checkpointed campaign\n")
            stream.flush()
            completed = subprocess.run([sys.executable, str(RUNNER)],
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       env=env)
            stream.write(f"{stamp()} runner exit={completed.returncode}\n")
            stream.flush()
        if completed.returncode:
            return completed.returncode
        if not STATE.is_file():
            raise RuntimeError("runner returned without a HDFS-43 checkpoint")
        state = json.loads(STATE.read_text())
        if state.get("stop_reason"):
            return 0
        if state.get("resource_gate_wait"):
            time.sleep(30)
            continue
        raise RuntimeError("runner stopped without terminal or resource-gate state")


if __name__ == "__main__":
    raise SystemExit(main())
