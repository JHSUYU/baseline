#!/usr/bin/env python3
"""Validate the SOLR-14 node1 full package without starting Java."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
completed = subprocess.run(
    [sys.executable, str(HERE / "run_campaign.py"), "--mode", "full", "--preflight-only"],
    check=True, text=True, capture_output=True)
receipt = json.loads(completed.stdout)
if receipt.get("preflight") != "passed_static_only" or receipt.get("go") is not False:
    raise ValueError("static preflight started a campaign")
print(json.dumps(receipt, sort_keys=True))
