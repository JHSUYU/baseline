"""Exercise storage-type quota accounting across replication changes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hdfs_random10"))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    rows = []

    def run(name, subcommand, args):
        result = workload.hdfs(subcommand, args, run_dir)
        result["name"] = name
        rows.append(result)
        (run_dir / "quota-steps.json").write_text(
            json.dumps(rows, indent=2) + "\n")

    run("set-disk-space-quota", "dfsadmin", [
        "-setSpaceQuota", "1g", "-storageType", "DISK", "/adhoc-random"])
    run("set-hot-policy", "storagepolicies", [
        "-setStoragePolicy", "-path", "/adhoc-random/blob", "-policy", "HOT"])
    run("reduce-replication", "dfs", ["-setrep", "2", "/adhoc-random/blob"])
    run("restore-replication", "dfs", ["-setrep", "3", "/adhoc-random/blob"])


if __name__ == "__main__":
    main()
