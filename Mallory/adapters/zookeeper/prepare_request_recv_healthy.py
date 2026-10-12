#!/usr/bin/env python3
"""Pin a fresh ZK02/03 graph-path healthy seed to the REQUEST receive overlay."""

import argparse
from pathlib import Path

from Mallory.adapters.zookeeper.prepare_zk11_scoped_healthy import prepare


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=("ZOOKEEPER-02", "ZOOKEEPER-03"))
    for name in ("base_config", "overlay_receipt", "agent_jar",
                 "core_release", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    prepare(*(getattr(args, name).resolve() for name in
              ("base_config", "overlay_receipt", "agent_jar",
               "core_release", "output")),
            allowed_cases=(args.case_id,), local_timeline=False)
