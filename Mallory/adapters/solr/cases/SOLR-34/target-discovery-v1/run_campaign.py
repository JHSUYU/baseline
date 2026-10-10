#!/usr/bin/env python3
"""Case-local SOLR-34 target-discovery campaign entry point."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from fault_discovery_runner import main
if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent, Path(__file__).resolve()))
