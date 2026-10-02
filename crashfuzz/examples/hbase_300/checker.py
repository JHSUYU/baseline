"""Independent workload completion check for the HBase smoke campaign."""

import os
from pathlib import Path
import sys


run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"])
exit_file = run_dir / "hbase-client.exit"
if not exit_file.is_file():
    print("HBase client did not finish")
    sys.exit(1)
status = int(exit_file.read_text(encoding="utf-8").strip())
output = (run_dir / "hbase-client.stdout").read_text(encoding="utf-8")
print("client exit:", status)
print(output[-1000:])
sys.exit(0 if status == 0 else 1)
