"""Verify the final HBase row independently after the faulted workload."""

import os
from pathlib import Path
import sys
import time

from workload import client


def main() -> int:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    status_file = run_dir / "hbase-client.exit"
    if not status_file.is_file() or status_file.read_text().strip() != "0":
        print("workload client did not finish successfully")
        return 1
    script = run_dir / "check.hbase"
    script.write_text("get 'adhoc_cf', 'r2', 'f:q'\n", encoding="utf-8")
    deadline = time.monotonic() + 90
    last = ""
    while time.monotonic() < deadline:
        result = client(script, run_dir / "conf", timeout=35)
        last = result.stdout[-1200:] + result.stderr[-1200:]
        if result.returncode == 0 and "sentinel266" in result.stdout:
            print("verified final HBase row: sentinel266")
            return 0
        time.sleep(3)
    print("final HBase row not observed:", last)
    return 1


if __name__ == "__main__":
    sys.exit(main())
