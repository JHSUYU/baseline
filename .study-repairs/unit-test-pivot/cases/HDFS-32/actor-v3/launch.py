#!/usr/bin/env python3
"""Shared, bounded JVM gate for the case-local original JUnit runner."""
from __future__ import annotations
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
START_LOCK = HERE.parents[2] / "jvm-start.lock"
MIN_FREE_BYTES = 10 * 1024**3
MAX_JAVA_BEFORE_START = 4


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or "0")


def child_java_started(directory: Path) -> bool:
    needle = str(directory).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if b"/java\0" in cmd and needle in cmd:
            return True
    return False


def previous_runner_alive(directory: Path) -> bool:
    needle = str(directory).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if b"runner.py" in cmd and needle in cmd:
            return True
    return False


def launch(directory: Path, plan: Path | None = None, timeout: int = 180) -> bool:
    if (directory / "manifest.json").is_file():
        return True
    if previous_runner_alive(directory):
        return False
    directory.mkdir(parents=True, exist_ok=True)
    errors: list[BaseException] = []
    with START_LOCK.open("a+") as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        if java_count() > MAX_JAVA_BEFORE_START or shutil.disk_usage(HERE).free < MIN_FREE_BYTES:
            return False
        command = [sys.executable, str(HERE / "runner.py"), "--output", str(directory),
                   "--timeout", str(timeout)]
        if plan is not None:
            command += ["--plan", str(plan)]

        def run() -> None:
            try:
                with (directory / "driver.log").open("w") as log:
                    subprocess.run(command, cwd=HERE, stdout=log,
                                   stderr=subprocess.STDOUT, check=False)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=run)
        worker.start()
        while worker.is_alive() and not child_java_started(directory):
            time.sleep(0.2)
    worker.join()
    if errors:
        raise errors[0]
    if not (directory / "manifest.json").is_file():
        raise RuntimeError("original JUnit ended without manifest: " + str(directory))
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    result = launch(args.output.resolve(), args.plan.resolve() if args.plan else None,
                    args.timeout)
    print(json.dumps({"launched": result, "output": str(args.output.resolve())}))
    if not result:
        raise SystemExit(75)


if __name__ == "__main__":
    main()
