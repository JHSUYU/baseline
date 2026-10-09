#!/usr/bin/env python3
"""Start one original JUnit under the host's shared JVM capacity lock."""

import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


LOCK = Path("/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock")
MAX_JAVA_BEFORE_START = 3
MIN_FREE_GIB = 3


def java_pids():
    result = subprocess.run(["pgrep", "-x", "java"], capture_output=True,
                            text=True, check=False)
    return set(result.stdout.split())


def descendants(pid):
    found = set()
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        result = subprocess.run(["pgrep", "-P", str(parent)], capture_output=True,
                                text=True, check=False)
        for raw in result.stdout.split():
            child = int(raw)
            if child not in found:
                found.add(child)
                frontier.append(child)
    return found


def has_java_descendant(pid):
    for child in descendants(pid):
        try:
            if (Path("/proc") / str(child) / "comm").read_text().strip() == "java":
                return True
        except OSError:
            continue
    return False


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: jvm_gate.py LOG COMMAND [ARGS...]")
    log_path = Path(sys.argv[1])
    command = sys.argv[2:]
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a") as gate, log_path.open("w") as log:
        while True:
            fcntl.flock(gate, fcntl.LOCK_EX)
            before = java_pids()
            free_gib = shutil.disk_usage(log_path.parent).free / 1024 ** 3
            if len(before) <= MAX_JAVA_BEFORE_START and free_gib >= MIN_FREE_GIB:
                process = subprocess.Popen(command, stdout=log,
                                           stderr=subprocess.STDOUT)
                # Keep the lock until this invocation's Java process appears
                # (or the command exits), so another lock holder sees it.
                for _ in range(50):
                    if process.poll() is not None:
                        break
                    if has_java_descendant(process.pid):
                        break
                    time.sleep(0.1)
                fcntl.flock(gate, fcntl.LOCK_UN)
                return process.wait()
            fcntl.flock(gate, fcntl.LOCK_UN)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
