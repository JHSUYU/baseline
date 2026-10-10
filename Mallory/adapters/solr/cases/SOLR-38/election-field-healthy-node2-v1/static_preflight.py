#!/usr/bin/env python3
"""Verify the SOLR-38 healthy package without starting a JVM."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    completed = subprocess.run([sys.executable, str(HERE / "run_campaign.py"),
                                "--mode", "healthy", "--preflight-only"],
                               check=True, capture_output=True, text=True)
    response = json.loads(completed.stdout)
    if response.get("preflight") != "passed_static_only":
        raise ValueError("offline preflight did not finish")
    print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    main()
