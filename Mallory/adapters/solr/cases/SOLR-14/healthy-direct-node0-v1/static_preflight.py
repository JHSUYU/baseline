#!/usr/bin/env python3
"""Run SOLR-14 package verification without starting a JVM."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    prior = ROOT / "data/mallory/calibration_v30_lane1/SOLR-14"
    result = prior / "result.json"
    events = prior / "trials/r0000/events.jsonl.gz"
    if (sha(result) != "946f08c9e52241080288913d64526f3287b8ff8366e26e017c334c34eb35a03a"
            or sha(events) != "03da19cd79bf456099e70a44358849d318bc369afffcea3005e961f15ff1e333"):
        raise ValueError("prior healthy reference changed")
    earlier = json.loads(result.read_text(encoding="utf-8"))
    if (earlier.get("case_id") != "SOLR-14" or earlier.get("healthy_seed_valid") is not True
            or earlier.get("target_binding", {}).get("nodes") != ["node1"]):
        raise ValueError("prior target mapping no longer matches source review")
    with gzip.open(events, "rt", encoding="utf-8") as stream:
        if not any('"event":"TARGET_CHECK"' in line or '"type":"TARGET_CHECK"' in line
                   for line in stream):
            raise ValueError("prior trace has no target event")
    completed = subprocess.run([sys.executable, str(HERE / "run_campaign.py"),
                                "--mode", "healthy", "--preflight-only"],
                               check=True, capture_output=True, text=True)
    response = json.loads(completed.stdout)
    if response.get("preflight") != "passed_static_only" or response.get("go") is not False:
        raise ValueError("offline preflight did not remain healthy-only")
    print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    main()
