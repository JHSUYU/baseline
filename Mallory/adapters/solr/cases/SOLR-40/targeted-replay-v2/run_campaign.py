#!/usr/bin/env python3
"""Bounded SOLR-40 alias watcher replay using the current Mallory graph."""

from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from Mallory.core import campaign  # noqa: E402

OUT = ROOT / "data/mallory/solr40_targeted_replay_v2_node0/SOLR-40"
LOCKS = ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock")


def main() -> int:
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        state = campaign.run(HERE / "config.json", OUT)
        print(json.dumps({key: state[key] for key in
                          ("case_id", "status", "completed_trials",
                           "target_exception_candidates", "elapsed_seconds")},
                         sort_keys=True))
        return 0
    finally:
        for handle in reversed(handles):
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
