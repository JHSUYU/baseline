"""Run one isolated case attempt and leave a durable exit receipt.

The worker owns the per-case flock.  It can outlive the coordinator, which lets
the next coordinator observe an active attempt or recover its exit receipt.
"""

import fcntl
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, sort_keys=True, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    attempt = Path(spec["attempt_dir"])
    with open(spec["worker_lock"], "a+b") as lock, ExitStack() as resources:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 73
        lane_path = spec.get("lane_lock")
        if lane_path:
            lane = resources.enter_context(open(lane_path, "a+b"))
            # The worker, rather than the coordinator, holds this lock.  A
            # coordinator restart cannot admit another case to the same lane.
            fcntl.flock(lane, fcntl.LOCK_EX)
        started = time.time()
        environment = os.environ.copy()
        environment.update(spec["environment"])
        exit_code = None
        error = None
        with (attempt / "stdout.log").open("ab") as stdout, (attempt / "stderr.log").open("ab") as stderr:
            try:
                if spec.get("core_release_manifest"):
                    try:
                        from .core_release import verify as verify_core_release
                    except ImportError:
                        from core_release import verify as verify_core_release
                    release = verify_core_release(Path(spec["core_release_manifest"]))
                    if release["release_id"] != spec.get("core_release_id"):
                        raise ValueError("worker core release ID differs from dispatch receipt")
                process = subprocess.Popen(
                    spec["command"], cwd=spec["cwd"], env=environment,
                    stdout=stdout, stderr=stderr, start_new_session=True,
                )
                atomic_json(attempt / "process.json", {
                    "pid": process.pid, "started_at": started,
                    "attempt_id": spec["attempt_id"],
                    "lane_id": spec.get("lane_id"),
                })
                try:
                    exit_code = process.wait(timeout=spec["timeout_seconds"])
                except subprocess.TimeoutExpired:
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    exit_code = 124
                    error = "timeout"
            except Exception as exc:
                exit_code = 125
                error = f"{type(exc).__name__}: {exc}"
                print(error, file=stderr)
        atomic_json(attempt / "exit.json", {
            "attempt_id": spec["attempt_id"],
            "case_id": spec["case_id"],
            "host": spec["host"],
            "exit_code": exit_code,
            "error": error,
            "started_at": started,
            "finished_at": time.time(),
            "duration_seconds": round(time.time() - started, 3),
            "lane_id": spec.get("lane_id"),
            "status": "command_succeeded" if exit_code == 0 else "command_failed",
        })
        return exit_code


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: worker.py SPEC.json")
    raise SystemExit(run(Path(sys.argv[1])))
