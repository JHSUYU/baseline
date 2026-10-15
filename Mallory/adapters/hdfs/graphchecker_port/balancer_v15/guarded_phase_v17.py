"""Run V17 admission/import phases under the same local resource guard."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign.guarded_one_fault import (
    _breach, _require_local, _require_pg0_read_only, _sample, _sha, _stop_group,
)


def run(args: argparse.Namespace) -> dict:
    pg0 = args.pg0.resolve(strict=True)
    _require_pg0_read_only(pg0)
    config_path = args.config.resolve(strict=True)
    if _sha(config_path) != args.config_sha256 or _sha(Path(campaign.__file__)) != args.campaign_source_sha256:
        raise ValueError("native phase source/config pin changed")
    config = campaign._load(config_path)
    campaign._validate_config(config)
    output = _require_local(args.output, pg0, "phase output")
    raw = _require_local(args.raw_root, pg0, "phase raw root")
    if config["runner"].get("local_artifact_root") != str(raw):
        raise ValueError("phase raw root differs from config")
    if config["runner"].get("local_work_root"):
        _require_local(Path(config["runner"]["local_work_root"]), pg0, "phase work root")
    if output == raw or output.is_relative_to(raw) or raw.is_relative_to(output):
        raise ValueError("phase output and raw roots overlap")
    if (output / "checkpoint.json").exists():
        raise ValueError("phase requires no prior checkpoint")
    if args.mode == "admit" and any(output.iterdir()):
        raise ValueError("admission requires an empty output root")
    if args.mode == "import" and not (output / "recording-admission.json").is_file():
        raise ValueError("import requires sealed recording admission")
    baseline = _sample(raw, output, 0)
    if reason := _breach(baseline, args):
        raise RuntimeError(f"phase capacity preflight refused: {reason}: {baseline}")
    command = [sys.executable, "-m", "Mallory.native_graphchecker_campaign",
               "--config", str(config_path), "--output", str(output),
               "--admit-only" if args.mode == "admit" else "--import-only"]
    source_root = Path(campaign.__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root) + os.pathsep + environment.get("PYTHONPATH", "")
    log_path = args.receipt.with_suffix(".log")
    started = time.monotonic()
    reason = None
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, cwd=source_root, env=environment)
        while process.poll() is None:
            if time.monotonic() - started >= args.max_wall_seconds:
                reason = "wall_timeout"
                break
            reason = _breach(_sample(raw, output, 0), args)
            if reason:
                break
            time.sleep(args.poll_seconds)
        if reason:
            _stop_group(process)
        exit_code = process.wait()
    state_path = output / "checkpoint.json"
    state = campaign._load(state_path) if state_path.is_file() else None
    if args.mode == "admit":
        accepted = (exit_code == 0 and reason is None and state is None and
                    (output / "recording-admission.json").is_file())
    else:
        imported = state.get("predecessor_import") if isinstance(state, dict) else None
        accepted = (exit_code == 0 and reason is None and state is not None and
                    state.get("case_id") == config["case_id"] and
                    state.get("healthy") is None and state.get("trials") == [] and
                    state.get("active") is None and state.get("completed_fault_trials") == 0 and
                    isinstance(imported, dict) and
                    imported.get("source_kind") == "bounded_prefix_snapshot_v1" and
                    state.get("imported_completed_fault_trials") ==
                    imported.get("source_completed_fault_trials") and
                    (output / "predecessor-import.json").is_file() and
                    campaign._load(output / "predecessor-import.json") == imported)
    receipt = {"mode": args.mode, "status": "accepted" if accepted else "invalid",
               "exit_code": exit_code, "guard_reason": reason,
               "config_sha256": args.config_sha256,
               "campaign_source_sha256": args.campaign_source_sha256,
               "checkpoint_sha256": _sha(state_path) if state is not None else None,
               "predecessor_import_sha256": _sha(output / "predecessor-import.json")
               if args.mode == "import" and (output / "predecessor-import.json").is_file()
               else None,
               "elapsed_seconds": round(time.monotonic() - started, 3),
               "checked_utc": datetime.now(timezone.utc).isoformat(),
               "sample": _sample(raw, output, 0), "log": str(log_path)}
    campaign._atomic(args.receipt, receipt)
    if not accepted:
        raise RuntimeError(f"native {args.mode} phase failed; see {args.receipt}")
    return receipt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("admit", "import"), required=True)
    for name in ("pg0", "config", "output", "raw-root", "receipt"):
        ap.add_argument("--" + name, type=Path, required=True)
    for name in ("config-sha256", "campaign-source-sha256"):
        ap.add_argument("--" + name, required=True)
    for name in ("max-raw-bytes", "max-output-bytes", "min-raw-available-bytes",
                 "min-output-available-bytes", "min-root-available-bytes",
                 "min-memory-available-bytes", "max-wall-seconds"):
        ap.add_argument("--" + name, type=int, required=True)
    ap.add_argument("--poll-seconds", type=float, default=1.0)
    args = ap.parse_args()
    if not 0 < args.poll_seconds <= 3 or args.max_wall_seconds <= 0:
        raise ValueError("invalid guard sampling/wall bound")
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
