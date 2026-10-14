"""Run at most one accepted native fault trial in a private PG0-read-only mount.

Invoke this module *inside* a same-UID private mount namespace whose PG0 input
tree has been bind-remounted read-only. It refuses an unprotected namespace.
Each attempt ID has a durable absolute stop bound, so retrying an interrupted
wrapper cannot consume another accepted fault trial.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import campaign


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _allocated(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    device = path.stat().st_dev
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue  # A JVM may have just removed a temporary file.
        if stat.S_ISLNK(info.st_mode):
            continue
        if info.st_dev != device:
            continue  # A read-only frozen evidence bind is input, not local growth.
        total += info.st_blocks * 512
        if stat.S_ISDIR(info.st_mode):
            try:
                with os.scandir(current) as entries:
                    pending.extend(Path(entry.path) for entry in entries)
            except FileNotFoundError:
                continue
    return total


def _available(path: Path) -> int:
    info = os.statvfs(path)
    return info.f_bavail * info.f_frsize


def _memory_available() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ValueError("/proc/meminfo has no MemAvailable")


def _mount_points() -> set[Path]:
    points = set()
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, separator, _ = line.partition(" - ")
        fields = before.split()
        if separator and len(fields) >= 6:
            decoded = re.sub(r"\\([0-7]{3})",
                             lambda match: chr(int(match.group(1), 8)), fields[4])
            points.add(Path(decoded))
    return points


def _require_pg0_read_only(pg0: Path) -> None:
    pg0 = pg0.resolve(strict=True)
    if not pg0.is_dir():
        raise ValueError("PG0 input path is not a directory")
    points = _mount_points()
    if not any(point == pg0 or point in pg0.parents for point in points):
        raise ValueError("PG0 input mount is absent from mountinfo")
    # statvfs checks the effective visible mount, including nested bind mounts.
    for point in {pg0, *(point for point in points if point.is_relative_to(pg0))}:
        if not os.statvfs(point).f_flag & os.ST_RDONLY:
            raise ValueError(f"PG0 input tree has writable mount: {point}")


def _require_local(path: Path, pg0: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or resolved == pg0 or resolved.is_relative_to(pg0):
        raise ValueError(f"{label} must be a local directory outside PG0")
    mount, kind = campaign._filesystem_mount(resolved)
    if mount == Path("/") or kind.lower().startswith("nfs"):
        raise ValueError(f"{label} must be on a dedicated host-local filesystem")
    return resolved


def _checkpoint(output: Path) -> dict | None:
    path = output / "checkpoint.json"
    return campaign._load(path) if path.is_file() else None


def _sample(raw_namespace: Path, output: Path, baseline_raw: int) -> dict:
    return {"raw_added_bytes": max(0, _allocated(raw_namespace) - baseline_raw),
            "output_allocated_bytes": _allocated(output),
            "raw_available_bytes": _available(raw_namespace.parent),
            "output_available_bytes": _available(output),
            "memory_available_bytes": _memory_available()}


def _breach(sample: dict, args: argparse.Namespace) -> str | None:
    checks = ((sample["raw_added_bytes"] >= args.max_raw_bytes, "raw_cap"),
              (sample["output_allocated_bytes"] >= args.max_output_bytes,
               "output_cap"),
              (sample["raw_available_bytes"] <= args.min_raw_available_bytes,
               "raw_free_floor"),
              (sample["output_available_bytes"] <= args.min_output_available_bytes,
               "output_free_floor"),
              (sample["memory_available_bytes"] <= args.min_memory_available_bytes,
               "memory_floor"))
    return next((reason for exceeded, reason in checks if exceeded), None)


def _stop_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def run_one(args: argparse.Namespace) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.attempt_id):
        raise ValueError("attempt_id must be a short safe identifier")
    for name in ("max_raw_bytes", "max_output_bytes", "max_wall_seconds"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name} must be positive")
    for name in ("min_raw_available_bytes", "min_output_available_bytes",
                 "min_memory_available_bytes"):
        if getattr(args, name) < 0:
            raise ValueError(f"{name} must be nonnegative")
    if not 0 < args.poll_seconds <= 3:
        raise ValueError("poll_seconds must be within (0, 3]")
    pg0 = args.pg0.resolve(strict=True)
    _require_pg0_read_only(pg0)
    config_path = args.config.resolve(strict=True)
    config = campaign._load(config_path)
    campaign._validate_config(config)
    if _sha(config_path) != args.config_sha256:
        raise ValueError("campaign config SHA-256 changed")
    source = Path(campaign.__file__).resolve(strict=True)
    if _sha(source) != args.campaign_source_sha256:
        raise ValueError("campaign source SHA-256 changed")
    output = _require_local(args.output, pg0, "campaign output")
    raw_root = _require_local(args.raw_root, pg0, "raw artifact root")
    configured_raw = config["runner"].get("local_artifact_root")
    if configured_raw is None or Path(configured_raw).resolve() != raw_root:
        raise ValueError("raw root differs from pinned runner.local_artifact_root")
    for key in ("local_work_root",):
        if config["runner"].get(key):
            _require_local(Path(config["runner"][key]), pg0, key)
    if raw_root == output or raw_root.is_relative_to(output) or output.is_relative_to(raw_root):
        raise ValueError("raw root and campaign output must be separate")
    namespace = hashlib.sha256((str(output) + "\0" + config["case_id"])
                               .encode()).hexdigest()[:24]
    raw_namespace = raw_root / namespace
    intent_dir = output / "one-fault-intents"
    intent_dir.mkdir(exist_ok=True)
    with (output / ".one-fault.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        intent_path = intent_dir / f"{args.attempt_id}.json"
        state = _checkpoint(output)
        completed = state["completed_fault_trials"] if state else 0
        pins = {"attempt_id": args.attempt_id,
                "config_sha256": args.config_sha256,
                "campaign_source_sha256": args.campaign_source_sha256,
                "config": str(config_path), "output": str(output),
                "raw_root": str(raw_root), "pg0": str(pg0),
                "limits": {name: getattr(args, name) for name in (
                    "max_raw_bytes", "max_output_bytes", "max_wall_seconds",
                    "min_raw_available_bytes", "min_output_available_bytes",
                    "min_memory_available_bytes", "poll_seconds")}}
        if intent_path.exists():
            intent = campaign._load(intent_path)
            if any(intent.get(key) != value for key, value in pins.items()):
                raise ValueError("one-fault intent pins changed")
            if completed < intent["start_completed"] or completed > intent["stop_after"]:
                raise ValueError("checkpoint escaped one-fault intent bound")
            if (completed == intent["start_completed"] and
                    intent.get("starting_active_key") is not None and
                    (state is None or state.get("active") is None or
                     state["active"].get("key") != intent["starting_active_key"])):
                raise ValueError("pending fault plan changed during one-fault attempt")
        else:
            if state and state["terminal"]:
                raise ValueError("new one-fault intent requires a nonterminal checkpoint")
            if state and state["active"] is not None and (
                    not isinstance(state["active"].get("key"), str) or
                    not state["active"]["key"]):
                raise ValueError("pending fault plan needs a nonempty exact key")
            if completed >= config["budget"]["fault_trials"]:
                raise ValueError("formal fault budget exhausted")
            intent = {**pins, "start_completed": completed,
                      "stop_after": completed + 1,
                      "starting_active_key": (state["active"].get("key")
                                              if state and state["active"] else None),
                      "raw_baseline_bytes": _allocated(raw_namespace),
                      "created_utc": datetime.now(timezone.utc).isoformat()}
            campaign._atomic(intent_path, intent)
        if completed == intent["stop_after"]:
            return {"status": "already_completed", "intent": str(intent_path),
                    "completed_fault_trials": completed}
        preflight = _sample(raw_namespace, output, intent["raw_baseline_bytes"])
        reason = _breach(preflight, args)
        if reason:
            raise RuntimeError(f"capacity preflight refused: {reason}: {preflight}")
        command = [sys.executable, "-m", "Mallory.native_graphchecker_campaign",
                   "--config", str(config_path), "--output", str(output),
                   "--stop-after-fault-trials", str(intent["stop_after"])]
        source_root = Path(campaign.__file__).resolve().parents[2]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = (str(source_root) + os.pathsep +
                                     environment.get("PYTHONPATH", ""))
        log_path = intent_dir / f"{args.attempt_id}.log"
        deadline = time.monotonic() + args.max_wall_seconds
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, cwd=source_root,
                                       env=environment)
            reason = None
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    reason = "wall_timeout"
                    break
                sample = _sample(raw_namespace, output, intent["raw_baseline_bytes"])
                reason = _breach(sample, args)
                if reason:
                    break
                time.sleep(args.poll_seconds)
            if reason:
                _stop_group(process)
            exit_code = process.wait()
        result_state = _checkpoint(output)
        after = result_state["completed_fault_trials"] if result_state else 0
        if after > intent["stop_after"]:
            raise RuntimeError("campaign exceeded one-fault absolute stop bound")
        final_sample = _sample(raw_namespace, output, intent["raw_baseline_bytes"])
        reason = reason or _breach(final_sample, args)
        receipt = {"status": "guard_stop" if reason else
                   ("accepted_one" if after == intent["stop_after"] else "campaign_exit"),
                   "guard_reason": reason, "exit_code": exit_code,
                   "completed_fault_trials": after,
                   "expected_stop_after": intent["stop_after"],
                   "sample": final_sample,
                   "intent": str(intent_path), "log": str(log_path),
                   "checked_utc": datetime.now(timezone.utc).isoformat()}
        campaign._atomic(intent_dir / f"{args.attempt_id}.receipt.json", receipt)
        if exit_code != 0 and not reason:
            raise RuntimeError(f"native campaign exited {exit_code}; see {log_path}")
        return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pg0", "config", "output", "raw-root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--campaign-source-sha256", required=True)
    parser.add_argument("--max-raw-bytes", required=True, type=int)
    parser.add_argument("--max-output-bytes", required=True, type=int)
    parser.add_argument("--min-raw-available-bytes", required=True, type=int)
    parser.add_argument("--min-output-available-bytes", required=True, type=int)
    parser.add_argument("--min-memory-available-bytes", required=True, type=int)
    parser.add_argument("--max-wall-seconds", required=True, type=int)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    print(json.dumps(run_one(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
