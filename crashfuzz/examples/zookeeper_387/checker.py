"""Read the final value in a new session after fault injection."""

import os
from pathlib import Path
import sys
import time

from workload import client


def main() -> int:
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    deadline = time.monotonic() + 60
    last = ""
    while time.monotonic() < deadline:
        result = client("get /adhoc387\nquit\n", timeout=35)
        last = (result.stdout + result.stderr)[-1000:]
        if result.returncode == 0 and "sentinel387" in result.stdout:
            print("verified ZooKeeper value: sentinel387")
            return 0
        time.sleep(2)
    print("ZooKeeper value not observed:", last)
    return 1


if __name__ == "__main__":
    sys.exit(main())
