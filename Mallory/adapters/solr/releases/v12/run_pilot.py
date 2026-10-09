#!/usr/bin/env python3
"""Pinned Solr v12 JUnit entry point recognized by the Mallory JUnit gate."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_pilot_v12 import main

if __name__ == "__main__":
    raise SystemExit(main())
