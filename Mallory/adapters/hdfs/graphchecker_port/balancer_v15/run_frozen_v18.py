"""Continue the exact frozen V16 healthy graph under bounded V18 guards.

Every fault is selected by the native GraphChecker campaign.  This launcher
only pins inputs, runs one accepted trial at a time, and archives its evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .archive_trial_v17 import archive
from Mallory.native_graphchecker_campaign import campaign


ROOT = Path("/dev/shm/mallory-hdfs-balancer-v18-frozen-node0")
CONFIG = ROOT / "campaign-config-v18-frozen.json"
OUTPUT = ROOT / "formal"
RAW = ROOT / "raw"
ARCHIVE = Path("/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-v18-frozen")
CAMPAIGN_SOURCE = Path(__file__).resolve().parents[4] / "native_graphchecker_campaign/campaign.py"
ENGINE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/native-repeated-io-v1/"
                   "Mallory/static_scope_port/original_engine")
CONFIG_SHA = "a12fa2a0a2d67def741ac964c252cdd710d7a0349a45da944c234baf39a75258"
SOURCE_SHA = "fff7ef2df0ee723de4f1c57d73ba714a757fdcce383f36976844791257827eb0"
IMPORT_SHA = "68fd65fcf94124666a2dde418404c28a7c3ea26efc6b4dc6e82b8413563da01d"
CASE_ID = "HDFS-11-TIMING-MONITOR-K8-DEPTH-V16"
IMPORTED = 16


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def state() -> dict:
    return json.loads((OUTPUT / "checkpoint.json").read_text())


def _pins() -> dict:
    if sha(CONFIG) != CONFIG_SHA or sha(CAMPAIGN_SOURCE) != SOURCE_SHA:
        raise ValueError("frozen successor config or campaign source changed")
    if sha(OUTPUT / "predecessor-import.json") != IMPORT_SHA:
        raise ValueError("frozen predecessor receipt changed")
    if not (ENGINE_ROOT / "target/native-original-engine-receipt.json").is_file():
        raise ValueError("source-built original GraphChecker engine receipt missing")
    config = json.loads(CONFIG.read_text())
    current = state()
    imported = json.loads((OUTPUT / "predecessor-import.json").read_text())
    if (current.get("case_id") != CASE_ID or
            current.get("imported_completed_fault_trials") != IMPORTED or
            current.get("predecessor_import") != imported or
            current.get("healthy", {}).get("status") != "healthy_seed" or
            current.get("multi_anchor_addresses") !=
            current.get("imported_multi_anchor_addresses") or
            config.get("predecessor_campaign", {}).get(
                "frozen_healthy_seed") is not True):
        raise ValueError("frozen r0000/8-graph predecessor identity changed")
    campaign._verify_frozen_healthy_materialized(OUTPUT, imported)
    return config


def _record(index: int, result: dict, receipt: dict) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    record = {"case_id": CASE_ID, "absolute_trial_index": index,
              "local_completed_fault_trials": index - IMPORTED,
              "fault_depth": len(result.get("faults", [])),
              "status": result.get("status"),
              "strict_injection": result.get("strict_injection"),
              "post_fault_target_check_observed": result.get(
                  "post_fault_target_check_observed"),
              "raw_exact_target_throw_count": result.get(
                  "raw_exact_target_throw_count"),
              "elapsed_seconds": result.get("elapsed_seconds"),
              "analysis_elapsed_seconds": result.get("analysis_elapsed_seconds"),
              "result_sha256": sha(OUTPUT / f"trials/r{index:04d}/result.json"),
              "archive_sha256": receipt["archive_sha256"],
              "archive_receipt_sha256": sha(
                  ARCHIVE / f"raw-r{index:04d}-receipt.json")}
    target = ARCHIVE / f"trial-r{index:04d}-progress.json"
    if target.exists():
        if json.loads(target.read_text()) != record:
            raise ValueError("existing progress row changed")
        return
    temporary = target.with_suffix(".partial")
    if temporary.exists():
        raise ValueError("partial progress row exists")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    temporary.replace(target)


def _archive_completed(*, verify_existing: bool) -> bool:
    """Return true and preserve raw if an exact throw needs immediate triage."""
    current = state()
    if current.get("active") is not None:
        return False
    for entry in current.get("trials", []):
        index = int(entry["name"][1:])
        if index < IMPORTED + 1:
            raise ValueError("local trial index overlaps frozen predecessor")
        result = json.loads((OUTPUT / entry["result"]).read_text())
        if result.get("raw_exact_target_throw_count", 0) > 0:
            print(f"candidate raw exact target throw at r{index:04d}; preserving raw", flush=True)
            return True
        if not verify_existing and (ARCHIVE / f"trial-r{index:04d}-progress.json").is_file():
            continue
        receipt = archive(OUTPUT, RAW, ARCHIVE, index, allow_unmatched=True)
        _record(index, result, receipt)
    return False


def _one(index: int) -> None:
    command = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
               "--propagation", "private", "sh", "-c",
               'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"',
               "sh", "/proj/silentfailure-PG0", sys.executable, "-m",
               "Mallory.native_graphchecker_campaign.guarded_one_fault",
               "--pg0", "/proj/silentfailure-PG0", "--config", str(CONFIG),
               "--output", str(OUTPUT), "--raw-root", str(RAW),
               "--attempt-id", f"v18-r{index:04d}",
               "--config-sha256", CONFIG_SHA,
               "--campaign-source-sha256", SOURCE_SHA,
               "--max-raw-bytes", "1500000000", "--max-output-bytes", "3000000000",
               "--min-raw-available-bytes", "5000000000",
               "--min-output-available-bytes", "5000000000",
               "--min-root-available-bytes", "1600000000",
               "--min-memory-available-bytes", "10000000000",
               "--max-wall-seconds", "1800", "--poll-seconds", "1"]
    environment = dict(os.environ, MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
    print(f"starting tool-selected r{index:04d}", flush=True)
    subprocess.run(command, check=True, cwd=Path(__file__).resolve().parents[5],
                   env=environment)


def run(through_local: int) -> None:
    if not 1 <= through_local <= 256:
        raise ValueError("local bound must be in 1..256")
    _pins()
    if _archive_completed(verify_existing=True):
        return
    while True:
        current = state()
        done = current["completed_fault_trials"]
        if done >= through_local or current.get("terminal") is True:
            print(json.dumps({"status": current.get("status"), "local_done": done,
                              "imported_done": IMPORTED}, sort_keys=True), flush=True)
            return
        index = current["next_trial_index"]
        if index != IMPORTED + done + 1:
            raise ValueError("local count/absolute fault index diverged")
        active = current.get("active")
        if active is not None and (active.get("index") != index or
                                   active.get("name") != f"r{index:04d}"):
            raise ValueError("unexpected active fault plan")
        _one(index)
        after = state()
        if after["completed_fault_trials"] != done + 1:
            raise RuntimeError("guarded attempt did not accept exactly one trial")
        if _archive_completed(verify_existing=False):
            return
        result = json.loads((OUTPUT / f"trials/r{index:04d}/result.json").read_text())
        print(json.dumps({"index": index, "depth": len(result.get("faults", [])),
                          "strict": result.get("strict_injection"),
                          "postfault_target": result.get(
                              "post_fault_target_check_observed"),
                          "exact_throws": result.get("raw_exact_target_throw_count"),
                          "elapsed_seconds": result.get("elapsed_seconds")},
                         sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--through-local", type=int, required=True)
    run(parser.parse_args().through_local)
