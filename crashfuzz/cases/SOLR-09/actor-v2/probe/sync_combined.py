#!/usr/bin/env python3
"""Merge each completed actor-aware V2 trial into the SOLR-09 row."""

import json
from pathlib import Path
import subprocess
import sys
import time


WORK = Path(__file__).resolve().parents[1]
RESULT = WORK / "result.json"
STATE = WORK / "evidence/campaign/state.json"
MERGE = WORK.parent / "http-stage2/probe/merge_results.py"


def main() -> None:
    last_mtime = -1
    while True:
        if RESULT.exists():
            mtime = RESULT.stat().st_mtime_ns
            if mtime != last_mtime:
                subprocess.run([sys.executable, str(MERGE)], check=True)
                last_mtime = mtime
        if STATE.exists():
            state = json.loads(STATE.read_text())
            if "finished_at" in state and RESULT.exists():
                subprocess.run([sys.executable, str(MERGE)], check=True)
                return
        time.sleep(3)


if __name__ == "__main__":
    main()
