"""Run only the native no-fault seed under a private read-only PG0 mount.

The fault campaign has its own one-fault guard. This wrapper establishes a
fresh healthy checkpoint without consuming a fault trial, using the same
destination and resource checks as that guard.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import campaign
from .guarded_one_fault import (
    _breach, _checkpoint, _require_local, _require_pg0_read_only, _sample,
    _sha, _stop_group,
)


def _validate_imported_healthy_start(output: Path, config: dict,
                                     expected_receipt_sha256: str | None) -> str:
    """Permit only a verified, zero-local-trial bounded import as healthy input."""
    if not isinstance(expected_receipt_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_receipt_sha256):
        raise ValueError("imported healthy requires a pinned import receipt SHA-256")
    if config.get("predecessor_campaign") is None:
        raise ValueError("imported healthy requires a pinned predecessor")
    checkpoint_path = output / "checkpoint.json"
    receipt_path = output / "predecessor-import.json"
    if any(path.is_symlink() or not path.is_file()
           for path in (checkpoint_path, receipt_path)):
        raise ValueError("imported healthy requires regular checkpoint and receipt")
    if _sha(receipt_path) != expected_receipt_sha256:
        raise ValueError("imported healthy receipt SHA-256 changed")
    checkpoint = campaign._load(checkpoint_path)
    receipt = campaign._load(receipt_path)
    imported = receipt.get("source_completed_fault_trials")
    if (checkpoint.get("case_id") != config.get("case_id") or
            checkpoint.get("healthy") is not None or
            checkpoint.get("active") is not None or
            checkpoint.get("completed_fault_trials") != 0 or
            checkpoint.get("trials") != [] or
            checkpoint.get("terminal") is not False or
            checkpoint.get("predecessor_import") != receipt or
            receipt.get("source_kind") != "bounded_prefix_snapshot_v1" or
            not isinstance(imported, int) or isinstance(imported, bool) or
            imported <= 0 or
            checkpoint.get("imported_completed_fault_trials") != imported or
            not isinstance(checkpoint.get("next_trial_index"), int) or
            checkpoint["next_trial_index"] < imported + 1):
        raise ValueError("imported healthy checkpoint differs from pinned predecessor receipt")
    trials = output / "trials"
    if trials.exists() and (trials.is_symlink() or any(trials.iterdir())):
        raise ValueError("imported healthy already has local trial files")
    return expected_receipt_sha256


def run_healthy(args: argparse.Namespace) -> dict:
    pg0 = args.pg0.resolve(strict=True)
    _require_pg0_read_only(pg0)
    config_path = args.config.resolve(strict=True)
    config = campaign._load(config_path)
    campaign._validate_config(config)
    if _sha(config_path) != args.config_sha256:
        raise ValueError("healthy config SHA-256 changed")
    if _sha(Path(campaign.__file__).resolve(strict=True)) != args.campaign_source_sha256:
        raise ValueError("healthy campaign source SHA-256 changed")
    output = _require_local(args.output, pg0, "healthy campaign output")
    raw_root = _require_local(args.raw_root, pg0, "healthy raw root")
    if config["runner"].get("local_artifact_root") != str(raw_root):
        raise ValueError("healthy raw root differs from pinned config")
    if config["runner"].get("local_work_root"):
        _require_local(Path(config["runner"]["local_work_root"]), pg0,
                       "healthy work root")
    if output == raw_root or output.is_relative_to(raw_root) or raw_root.is_relative_to(output):
        raise ValueError("healthy output and raw roots must be separate")
    import_receipt_sha = None
    if getattr(args, "allow_imported_predecessor", False):
        import_receipt_sha = _validate_imported_healthy_start(
            output, config, getattr(args, "predecessor_import_sha256", None))
        if campaign._load(output / "checkpoint.json").get("config_sha256") != args.config_sha256:
            raise ValueError("imported healthy checkpoint config SHA-256 changed")
    elif (output / "checkpoint.json").exists() or any(output.iterdir()):
        raise ValueError("healthy output must be fresh and empty")
    for name in ("max_raw_bytes", "max_output_bytes", "max_wall_seconds"):
        if getattr(args, name) <= 0:
            raise ValueError(f"{name} must be positive")
    for name in ("min_raw_available_bytes", "min_output_available_bytes",
                 "min_root_available_bytes", "min_memory_available_bytes"):
        if getattr(args, name) < 0:
            raise ValueError(f"{name} must be nonnegative")
    if not 0 < args.poll_seconds <= 3:
        raise ValueError("poll_seconds must be within (0, 3]")
    raw_before = 0
    preflight = _sample(raw_root, output, raw_before)
    if reason := _breach(preflight, args):
        raise RuntimeError(f"healthy capacity preflight refused: {reason}: {preflight}")
    source_root = Path(campaign.__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root) + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "Mallory.native_graphchecker_campaign",
               "--config", str(config_path), "--output", str(output),
               "--stop-after-fault-trials", "0"]
    started = time.monotonic()
    reason = None
    log_path = args.receipt.with_suffix(".log")
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, cwd=source_root, env=env)
        while process.poll() is None:
            if time.monotonic() - started >= args.max_wall_seconds:
                reason = "wall_timeout"
                break
            reason = _breach(_sample(raw_root, output, raw_before), args)
            if reason:
                break
            time.sleep(args.poll_seconds)
        if reason:
            _stop_group(process)
        exit_code = process.wait()
    checkpoint = _checkpoint(output)
    completed = checkpoint.get("completed_fault_trials") if checkpoint else None
    if completed not in (None, 0):
        raise RuntimeError("healthy wrapper consumed a fault trial")
    result = output / "trials/r0000/result.json"
    healthy = campaign._load(result) if result.is_file() else None
    final = _sample(raw_root, output, raw_before)
    reason = reason or _breach(final, args)
    accepted = (reason is None and exit_code == 0 and
                checkpoint is not None and completed == 0 and
                checkpoint.get("healthy", {}).get("status") == "healthy_seed" and
                healthy is not None and healthy.get("status") == "healthy_seed")
    receipt = {"status": "healthy_seed" if accepted else "healthy_invalid",
               "guard_reason": reason, "exit_code": exit_code,
               "completed_fault_trials": completed,
               "config_sha256": args.config_sha256,
               "campaign_source_sha256": args.campaign_source_sha256,
               "checkpoint_sha256": _sha(output / "checkpoint.json") if checkpoint else None,
               "result_sha256": _sha(result) if healthy else None,
               "sample": final, "elapsed_seconds": round(time.monotonic() - started, 3),
               "checked_utc": datetime.now(timezone.utc).isoformat(),
               "log": str(log_path)}
    if import_receipt_sha is not None:
        receipt["predecessor_import_sha256"] = import_receipt_sha
    campaign._atomic(args.receipt, receipt)
    if not accepted:
        raise RuntimeError(f"native healthy gate failed; see {args.receipt}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pg0", "config", "output", "raw-root", "receipt"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("config-sha256", "campaign-source-sha256"):
        parser.add_argument("--" + name, required=True)
    for name in ("max-raw-bytes", "max-output-bytes", "min-raw-available-bytes",
                 "min-output-available-bytes", "min-root-available-bytes",
                 "min-memory-available-bytes", "max-wall-seconds"):
        parser.add_argument("--" + name, required=True, type=int)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--allow-imported-predecessor", action="store_true")
    parser.add_argument("--predecessor-import-sha256")
    print(json.dumps(run_healthy(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
