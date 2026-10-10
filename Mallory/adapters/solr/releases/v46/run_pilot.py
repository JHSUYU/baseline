#!/usr/bin/env python3
"""Immutable SOLR-31 watcher diagnostic direct-JUnit entry point."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_pilot_v46 import main

if __name__ == "__main__":
    raise SystemExit(main())
