"""Run the broad workload, then attempt a local short-circuit read on dn1."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import workload


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    result = subprocess.run(
        workload.DOCKER + ["exec", "adhocfuzz-hdfs-key-dn1",
                           "/opt/hadoop/bin/hdfs", "dfs", "-get", "-f",
                           "/adhoc-random/blob", "/data/local-read.bin"],
        capture_output=True, text=True, timeout=120)
    (run_dir / "short-circuit-read.json").write_text(json.dumps({
        "returncode": result.returncode, "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }, indent=2) + "\n")
    print("local read return code", result.returncode)


if __name__ == "__main__":
    main()
