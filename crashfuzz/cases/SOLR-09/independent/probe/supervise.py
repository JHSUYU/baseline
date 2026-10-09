#!/usr/bin/env python3
"""Resume the shared campaign after transient process failures."""

import json
from pathlib import Path
import subprocess
import sys
import time


WORK = Path(__file__).resolve().parents[1]
STATE = WORK / "evidence/campaign/state.json"
LOG = WORK / "evidence/campaign.log"


def completed() -> int:
    if not STATE.exists():
        return 0
    return len(json.loads(STATE.read_text()).get("trials", []))


def main() -> int:
    failures_without_progress = 0
    while True:
        before = completed()
        with LOG.open("a") as output:
            result = subprocess.run([sys.executable, "-u", str(WORK / "probe/campaign.py")],
                                    cwd=WORK, stdout=output, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return 0
        after = completed()
        failures_without_progress = 0 if after > before else failures_without_progress + 1
        with LOG.open("a") as output:
            output.write(f"supervisor restart after exit={result.returncode}, "
                         f"completed={after}, no_progress={failures_without_progress}\n")
        if failures_without_progress >= 5:
            return result.returncode
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
