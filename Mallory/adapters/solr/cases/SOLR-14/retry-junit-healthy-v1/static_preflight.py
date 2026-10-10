#!/usr/bin/env python3
"""Validate the isolated SOLR-14 retry JUnit stage without starting Java."""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
result = subprocess.run(
    [sys.executable, str(HERE / "run_campaign.py"), "--mode", "healthy", "--preflight-only"],
    check=True, text=True, capture_output=True,
)
receipt = json.loads(result.stdout)
if receipt.get("preflight") != "passed_static_only" or receipt.get("go") is not False:
    raise ValueError("preflight did not remain offline and healthy-only")
print(json.dumps(receipt, sort_keys=True))
