"""Create edit logs, then restart the NameNode to exercise gap validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

import workload


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    restarted = subprocess.run(
        workload.DOCKER + ["restart", "--time", "10",
                           "adhocfuzz-hdfs-key-nn"],
        capture_output=True, text=True, timeout=45)
    observations = [{"operation": "namenode-restart",
                     "returncode": restarted.returncode,
                     "stderr": restarted.stderr[-1000:]}]
    if restarted.returncode:
        raise RuntimeError("NameNode restart failed: " + restarted.stderr)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        result = workload.hdfs("dfsadmin", ["-safemode", "get"], run_dir)
        observations.append({"operation": "namenode-ready",
                             "returncode": result["returncode"],
                             "stderr": result["stderr"]})
        if result["returncode"] == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError("NameNode did not restart within 120 seconds")
    (run_dir / "editlog-restart.json").write_text(
        json.dumps(observations, indent=2) + "\n")


if __name__ == "__main__":
    main()
