#!/usr/bin/env python3
"""Execute one prepared ZooKeeper seed, preserving the Maven log and exit status."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(path: Path) -> int:
    config = json.loads(path.read_text(encoding="utf-8"))
    timeout = int(config.get("timeout_seconds", 1200))
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = time.time()
    with (path.parent / "maven.log").open("wb") as log:
        process = subprocess.Popen(config["argv"], cwd=config["cwd"],
                                   stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            code = 124
    (path.parent / "exit.json").write_text(json.dumps({
        "case_id": config["case_id"], "exit_code": code,
        "started_at": started, "finished_at": time.time(),
        "duration_seconds": round(time.time() - started, 3),
    }, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_prepared.py COMMAND.json")
    raise SystemExit(main(Path(sys.argv[1])))
