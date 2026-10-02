"""Wait for cache directives to produce a pending-cache selection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import workload


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    time.sleep(10)
    results = [
        workload.hdfs("cacheadmin", ["-listDirectives", "-stats"], run_dir),
        workload.hdfs("dfsadmin", ["-report"], run_dir),
    ]
    (run_dir / "cache-stats.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
