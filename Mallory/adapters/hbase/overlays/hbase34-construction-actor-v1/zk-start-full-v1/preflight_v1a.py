#!/usr/bin/env python3
"""Single offline preflight for the HBASE-34 v1a runner."""

import json
from pathlib import Path

from preflight import main as case_preflight
from verify_legacy_release import verify


if __name__ == "__main__":
    case_preflight()
    release = Path(__file__).resolve().parents[6] / \
        "Mallory/dispatch/releases/815cba9b-target-absent-v1"
    print(json.dumps(verify(release), sort_keys=True))
