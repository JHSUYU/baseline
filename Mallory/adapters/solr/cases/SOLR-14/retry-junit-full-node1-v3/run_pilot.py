#!/usr/bin/env python3
"""Run the unchanged retrying Solr JUnit with a case-local selector inventory."""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SOLR_ADAPTER = HERE.parents[2]
sys.path.insert(0, str(SOLR_ADAPTER))

import run_pilot_v38  # noqa: E402

run_pilot_v38.INVENTORY = HERE / "inventory-selector.json"

if __name__ == "__main__":
    raise SystemExit(run_pilot_v38.main())
