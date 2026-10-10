#!/usr/bin/env python3
"""Offline-only package check; no JVM, JUnit, or fault trial."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
completed = subprocess.run(
    [sys.executable, str(HERE / "run_campaign.py"), "--mode",
     "bounded_fault_bootstrap", "--preflight-only"],
    check=True, capture_output=True, text=True)
receipt = json.loads(completed.stdout)
if receipt.get("preflight") != "passed_static_only" or receipt.get("go") is not False:
    raise ValueError("static preflight started a JVM")
print(json.dumps(receipt, sort_keys=True))
