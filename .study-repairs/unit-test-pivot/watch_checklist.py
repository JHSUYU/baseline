#!/usr/bin/env python3
"""Keep the 102-case table current as independently written results arrive."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent


def snapshot() -> tuple[tuple[str, int, int], ...]:
    paths = [HERE / "selection102.json", HERE / "checklist.py"]
    paths.extend(sorted((HERE / "cases").glob("*/result.json")))
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                 for path in paths if path.exists())


def render() -> bool:
    command = [sys.executable, str(HERE / "checklist.py"), "render"]
    completed = subprocess.run(command, cwd=HERE, capture_output=True,
                               text=True, check=False)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    detail = (completed.stdout if completed.returncode == 0
              else completed.stderr).strip()
    print(f"{stamp} {'ok' if completed.returncode == 0 else 'retry'} "
          f"{detail}", flush=True)
    return completed.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    last_success = None
    while True:
        current = snapshot()
        if current != last_success and render():
            last_success = current
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
