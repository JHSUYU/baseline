"""Set a finite cache pool TTL so its validation guard executes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import workload


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    result = workload.hdfs("cacheadmin", [
        "-modifyPool", "adhoc-random-pool", "-maxTtl", "1h"], run_dir)
    (run_dir / "cachepool-modify.json").write_text(
        json.dumps(result, indent=2) + "\n")
    if result["returncode"]:
        raise RuntimeError("cache pool TTL modification failed: " + result["stderr"])


if __name__ == "__main__":
    main()
