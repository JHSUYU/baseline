#!/usr/bin/env python3
"""Publish SOLR-06 result to the 102-check table while fuzzing."""

import hashlib
import json
from pathlib import Path
import subprocess
import time


WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[1]
PIVOT = ROOT.parent
CASES = ("SOLR-06",)


def snapshot() -> tuple[str, bool]:
    contents = []
    statuses = []
    for cid in CASES:
        data = (ROOT / cid / "result.json").read_bytes()
        contents.append(data)
        statuses.append(json.loads(data).get("status"))
    return hashlib.sha256(b"\n".join(contents)).hexdigest(), all(
        status != "running" for status in statuses)


def main() -> None:
    previous = ""
    while True:
        current, done = snapshot()
        if current != previous:
            subprocess.run(["/usr/bin/python3", str(PIVOT / "checklist.py"), "render"],
                           check=True, stdout=subprocess.DEVNULL)
            previous = current
        if done:
            break
        time.sleep(15)


if __name__ == "__main__":
    main()
