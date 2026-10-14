"""Optional bounded local capacity gate for each GraphChecker trial.

The fuzzer checks this gate immediately before preparation and every JUnit
trial. A separate process-group monitor handles changes during a running JVM.
"""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CapacityGuardStop(RuntimeError):
    """A running JVM was stopped before the host reserve was exhausted."""

    def __init__(self, receipt: dict[str, Any]):
        self.receipt = receipt
        super().__init__(f"capacity guard stopped JVM: {receipt['reason']}")


def _nonnegative_int(raw: dict[str, Any], name: str) -> int:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"capacity_guard.{name} must be a nonnegative integer")
    return value


def _available(path: Path) -> int:
    filesystem = os.statvfs(path)
    return filesystem.f_bavail * filesystem.f_frsize


def _memory_available() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ValueError("/proc/meminfo has no MemAvailable")


def _allocated_tree(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            # Do not follow external evidence through a tree symlink.
            continue
        total += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(current) as entries:
                pending.extend(Path(item.path) for item in entries)
    return total


def load_capacity_guard(raw: Any, campaign_root: Path) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("capacity_guard must be an object")
    for name in ("pg0_path", "root_path", "scratch_path", "durable_path"):
        if not isinstance(raw.get(name), str) or not raw[name].startswith("/"):
            raise ValueError(f"capacity_guard.{name} must be an absolute path")
    paths = {name: Path(raw[name]).resolve() for name in
             ("pg0_path", "root_path", "scratch_path", "durable_path")}
    for name in ("pg0_path", "root_path", "scratch_path"):
        if not paths[name].is_dir():
            raise ValueError(f"capacity_guard.{name} must be an existing directory")
    if campaign_root.resolve().is_relative_to(paths["pg0_path"]):
        raise ValueError("campaign root must be local, outside capacity_guard.pg0_path")
    if paths["durable_path"] == paths["pg0_path"] or not paths[
            "durable_path"].is_relative_to(paths["pg0_path"]):
        raise ValueError("capacity_guard.durable_path must be a dedicated PG0 child")
    limits = {name: _nonnegative_int(raw, name) for name in (
        "pg0_start_min_bytes", "pg0_stop_max_bytes", "root_min_bytes",
        "scratch_min_bytes", "memory_min_bytes", "private_max_bytes",
        "durable_max_bytes")}
    if limits["pg0_start_min_bytes"] <= limits["pg0_stop_max_bytes"]:
        raise ValueError("capacity_guard PG0 start floor must exceed stop threshold")
    poll = raw.get("poll_seconds")
    if not isinstance(poll, (int, float)) or isinstance(poll, bool) or not 0 < poll <= 3:
        raise ValueError("capacity_guard.poll_seconds must be within (0, 3]")
    return {**paths, **limits, "poll_seconds": float(poll)}


def check_capacity(guard: dict[str, Any], campaign_root: Path,
                   phase: str) -> dict[str, Any]:
    sample = {"pg0_available_bytes": _available(guard["pg0_path"]),
              "root_available_bytes": _available(guard["root_path"]),
              "scratch_available_bytes": _available(guard["scratch_path"]),
              "memory_available_bytes": _memory_available(),
              "private_allocated_bytes": _allocated_tree(campaign_root),
              "durable_allocated_bytes": _allocated_tree(guard["durable_path"])}
    reason = None
    checks = [
        (sample["pg0_available_bytes"] <= guard["pg0_stop_max_bytes"],
         "pg0_stop_floor"),
        (sample["root_available_bytes"] <= guard["root_min_bytes"],
         "root_floor"),
        (sample["scratch_available_bytes"] <= guard["scratch_min_bytes"],
         "scratch_floor"),
        (sample["memory_available_bytes"] <= guard["memory_min_bytes"],
         "memory_floor"),
        (sample["private_allocated_bytes"] >= guard["private_max_bytes"],
         "private_cap"),
        (sample["durable_allocated_bytes"] >= guard["durable_max_bytes"],
         "durable_cap")]
    if phase != "running":
        checks.insert(1, (sample["pg0_available_bytes"] <
                          guard["pg0_start_min_bytes"], "pg0_start_floor"))
    for condition, label in checks:
        if condition:
            reason = label
            break
    return {"phase": phase, "checked_utc": datetime.now(timezone.utc).isoformat(),
            "reason": reason, "sample": sample}


def wait_with_capacity(process: subprocess.Popen, timeout_seconds: int,
                       guard: dict[str, Any], campaign_root: Path
                       ) -> tuple[int, bool]:
    """Poll a trial JVM, stopping its own process group on a reserve breach."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_process_group(process)
            return process.returncode, True
        try:
            return process.wait(timeout=min(guard["poll_seconds"], remaining)), False
        except subprocess.TimeoutExpired:
            receipt = check_capacity(guard, campaign_root, "running")
            if receipt["reason"] is not None:
                _stop_process_group(process)
                raise CapacityGuardStop(receipt)


def _stop_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
