"""Run V17 admission/import phases under the same local resource guard."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign.guarded_one_fault import (
    _breach, _require_local, _require_pg0_read_only, _sample, _sha, _stop_group,
)


def _verified_frozen_healthy_seed(output: Path, state: dict,
                                  imported: dict, config: dict) -> bool:
    """Accept an imported healthy seed only when every graph root is byte-pinned."""
    pin = imported.get("frozen_healthy_seed")
    healthy = state.get("healthy")
    if (not isinstance(pin, dict) or healthy != {
            "name": "r0000", "status": "healthy_seed",
            "result": "trials/r0000/result.json"} or
            state.get("trials") != [] or state.get("active") is not None or
            state.get("completed_fault_trials") != 0):
        return False
    trial = output / "trials" / "r0000"
    trials_dir = output / "trials"
    if (not trials_dir.is_dir() or
            {p.name for p in trials_dir.iterdir()} != {"r0000"} or
            trial.is_symlink() or not trial.is_dir()):
        return False
    files = pin.get("source_healthy_files")
    graphs = pin.get("source_graph_summaries")
    anchor_count = config.get("recording", {}).get("multi_target_max_anchors")
    addresses = state.get("multi_anchor_addresses")
    if (not isinstance(files, dict) or not isinstance(graphs, dict) or
            not isinstance(anchor_count, int) or anchor_count <= 0 or
            len(graphs) != anchor_count or not isinstance(addresses, list) or
            len(addresses) != anchor_count or len(set(addresses)) != anchor_count or
            "trials/r0000/result.json" not in files or
            "trials/r0000/native-summary.json" not in files):
        return False
    expected_graphs = {f"original-graph/anchor-{i:02d}/summary.json"
                       for i in range(anchor_count)}
    if set(graphs) != expected_graphs:
        return False
    expected_files = {
        "trials/r0000/iteration-native/fault-events.jsonl",
        "trials/r0000/local-artifacts.json",
        "trials/r0000/native-summary.json",
        "trials/r0000/result.json",
    }
    if not expected_files.issubset(files):
        return False
    root = output.resolve(strict=True)
    for relative, digest in [*files.items(), *graphs.items()]:
        if (not isinstance(relative, str) or not isinstance(digest, str) or
                not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return False
        if relative in files:
            if not relative.startswith("trials/r0000/"):
                return False
            path = output / relative
        else:
            path = trial / relative
        if (path.is_symlink() or not path.is_file() or
                not path.resolve(strict=True).is_relative_to(root) or
                _sha(path) != digest):
            return False
    if (files["trials/r0000/result.json"] !=
            pin.get("source_healthy_result_sha256") or
            files["trials/r0000/native-summary.json"] !=
            pin.get("source_native_summary_sha256") or
            not re.fullmatch(r"[0-9a-f]{64}",
                             str(pin.get("source_raw_archive_sha256")))):
        return False
    try:
        result = campaign._load(trial / "result.json")
        summary = campaign._load(trial / "native-summary.json")
        anchors = summary["anchors"]
        if (result.get("status") != "healthy_seed" or
                result.get("junit_passed") is not True or
                result.get("raw_exact_target_throw_count") != 0 or
                result.get("multi_anchor_addresses") != addresses or
                len(anchors) != anchor_count or
                [row.get("occurrenceAddress") for row in anchors] != addresses):
            return False
        for i, row in enumerate(anchors):
            relative = f"original-graph/anchor-{i:02d}/summary.json"
            if (graphs[relative] != row.get("summarySha256") or
                    campaign._load(trial / relative) != row.get("summary")):
                return False
    except (KeyError, TypeError, ValueError, OSError):
        return False
    return True


def run(args: argparse.Namespace) -> dict:
    if args.allow_frozen_healthy_seed and args.mode != "import":
        raise ValueError("frozen healthy seed mode applies only to import")
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
        healthy_ok = False
        if isinstance(state, dict):
            if args.allow_frozen_healthy_seed:
                healthy_ok = _verified_frozen_healthy_seed(
                    output, state, imported or {}, config)
            else:
                healthy_ok = state.get("healthy") is None and state.get("trials") == []
        accepted = (exit_code == 0 and reason is None and state is not None and
                    state.get("case_id") == config["case_id"] and healthy_ok and
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
    ap.add_argument("--allow-frozen-healthy-seed", action="store_true")
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
