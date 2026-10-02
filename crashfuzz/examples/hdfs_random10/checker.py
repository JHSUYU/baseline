"""Verify the required write/read workload and its data hash."""

import json
import os
from pathlib import Path
import sys


run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"])
steps = json.loads((run_dir / "workload-steps.json").read_text())
by_name = {row["name"]: row for row in steps}
for name in ("mkdir", "put", "get"):
    if by_name.get(name, {}).get("returncode") != 0:
        print(name + " did not complete")
        sys.exit(1)
hashes = (run_dir / "hashes.txt").read_text().splitlines()
if len(hashes) != 2 or hashes[0] != hashes[1]:
    print("HDFS file hash mismatch")
    sys.exit(1)
print("HDFS readback matched " + hashes[0])
