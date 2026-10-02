"""Check completion and data correctness for the encrypted HDFS workload."""

import os
from pathlib import Path
import sys


run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"])
for name in ("mkdir", "put", "get"):
    marker = run_dir / (name + ".exit")
    if not marker.is_file() or marker.read_text().strip() != "0":
        print(name + " did not complete successfully")
        sys.exit(1)
hashes = run_dir / "hashes.txt"
if not hashes.is_file():
    print("missing data comparison")
    sys.exit(1)
source, destination = hashes.read_text().splitlines()
if source != destination:
    print("HDFS returned different bytes")
    sys.exit(1)
print("HDFS data matched sha256=" + source)
