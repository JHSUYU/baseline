"""Generate and submit a disk balancer plan on a two-volume DataNode."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    results = []
    # The initial 8 MiB replicated block leaves an odd number of blocks on
    # each DataNode's two volumes. A small positive threshold exposes it.
    plan = workload.hdfs("diskbalancer", [
        "-plan", "adhocfuzz-hdfs-key-dn1",
        "-thresholdPercentage", "0.0001",
        "-out", "/work/diskbalancer"], run_dir)
    plan["name"] = "plan"
    results.append(plan)
    match = re.search(r"(?m)^(/work/[^\s]+\.plan\.json)\s*$", plan["stdout"])
    if plan["returncode"] == 0 and match:
        submit = workload.hdfs("diskbalancer", ["-execute", match.group(1)],
                               run_dir)
        submit["name"] = "execute"
        results.append(submit)
    (run_dir / "diskbalancer-steps.json").write_text(
        json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
