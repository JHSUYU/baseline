#!/usr/bin/env python3
"""Alert on low node0 root space while preserving all raw case evidence."""

import json
from pathlib import Path
import shutil
import time

from feedback import atomic_json


WORK = Path(__file__).resolve().parents[1]
STATE = WORK / "evidence/campaign/state.json"
WARNING = WORK / "evidence/disk-warning.json"
THRESHOLD = int(1.5 * 1024 ** 3)


def main() -> None:
    while True:
        free = shutil.disk_usage(WORK).free
        if free < THRESHOLD:
            row = {"case_id": "SOLR-09", "phase": "actor-v2",
                   "free_bytes": free, "threshold_bytes": THRESHOLD,
                   "at_unix_seconds": time.time(),
                   "action": "Notify owner; preserve raw events, JaCoCo, JUnit logs and checkpoint"}
            atomic_json(WARNING, row)
            print(json.dumps(row), flush=True)
        if STATE.exists() and "finished_at" in json.loads(STATE.read_text()):
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
