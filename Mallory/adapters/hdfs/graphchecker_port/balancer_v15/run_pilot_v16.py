"""Resume V16 one strict fault at a time, sealing each local raw attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path("/dev/shm/mallory-hdfs-balancer-v16-node0")
CONFIG = ROOT / "campaign-config-v16.json"
OUTPUT = ROOT / "formal-b"
RAW = ROOT / "raw"
ARCHIVE = Path("/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-v16-pilot")
HEALTHY = ROOT / "guarded-healthy-v16b.json"
ARCHIVE_SCRIPT = Path("/users/ZhenyuLi/.mallory-worktrees/native-repeated-io-v1/"
                      "Mallory/adapters/hdfs/graphchecker_port/"
                      "balancer_short_lifetime_repeat_v1/archive_trial.py")
PINS = {
    CONFIG: "ed719939ba0c6e03bafaa100c1729a6a3a05ff6c3a9e947abecd34b10202f49d",
    Path(__file__).resolve().parents[4] / "native_graphchecker_campaign/campaign.py":
        "c08afcda3a22d5ea16847bbfd801d1800814a625cf4fe92d4f2d43b3edace9e1",
    ARCHIVE_SCRIPT: "9230fe731b3c6b1fcfe92e655d9c11371508ed75cf2d4c2a82b9f38b828c15a2",
}
ENGINE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/native-repeated-io-v1/"
                   "Mallory/static_scope_port/original_engine")


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def run_pilot(through: int) -> None:
    if not 1 <= through <= 16:
        raise ValueError("pilot bound must be within 1..16")
    for path, digest in PINS.items():
        if sha(path) != digest:
            raise ValueError(f"pinned input changed: {path}")
    healthy = json.loads(HEALTHY.read_text())
    if healthy.get("status") != "healthy_seed":
        raise ValueError("original GraphChecker K8 healthy seed did not pass")
    if not (ENGINE_ROOT / "target/native-original-engine-receipt.json").is_file():
        raise ValueError("source-built native original engine receipt absent")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archive = [sys.executable, str(ARCHIVE_SCRIPT), "--output", str(OUTPUT),
               "--raw-root", str(RAW), "--archive-root", str(ARCHIVE)]
    if not (ARCHIVE / "raw-r0000-receipt.json").exists():
        subprocess.run([*archive, "--index", "0"], check=True)
    while True:
        state = json.loads((OUTPUT / "checkpoint.json").read_text())
        done = state["completed_fault_trials"]
        if done >= through:
            break
        index = done + 1
        command = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
                   "--propagation", "private", "sh", "-c",
                   'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"',
                   "sh", "/proj/silentfailure-PG0", sys.executable, "-m",
                   "Mallory.native_graphchecker_campaign.guarded_one_fault",
                   "--pg0", "/proj/silentfailure-PG0", "--config", str(CONFIG),
                   "--output", str(OUTPUT), "--raw-root", str(RAW),
                   "--attempt-id", f"v16-r{index:04d}",
                   "--config-sha256", PINS[CONFIG],
                   "--campaign-source-sha256", PINS[Path(__file__).resolve().parents[4] /
                                                     "native_graphchecker_campaign/campaign.py"],
                   "--max-raw-bytes", "600000000", "--max-output-bytes", "3000000000",
                   "--min-raw-available-bytes", "5000000000",
                   "--min-output-available-bytes", "5000000000",
                   "--min-root-available-bytes", "1600000000",
                   "--min-memory-available-bytes", "10000000000",
                   "--max-wall-seconds", "900", "--poll-seconds", "1"]
        environment = dict(os.environ, MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
        print(f"starting r{index:04d}", flush=True)
        subprocess.run(command, check=True, cwd=Path(__file__).resolve().parents[5],
                       env=environment)
        state = json.loads((OUTPUT / "checkpoint.json").read_text())
        result = json.loads((OUTPUT / f"trials/r{index:04d}/result.json").read_text())
        if state["completed_fault_trials"] != index or result.get("strict_injection") is not True:
            raise RuntimeError(f"r{index:04d} not a strict accepted fault")
        summary = {"index": index, "status": result.get("status"),
                   "depth": len(result.get("faults", [])),
                   "raw_exact_target_throw_count": result.get("raw_exact_target_throw_count"),
                   "target_after_fault": result.get("post_fault_target_check_observed")}
        print(json.dumps(summary, sort_keys=True), flush=True)
        if result.get("raw_exact_target_throw_count", 0) > 0:
            print("candidate target throw: preserving raw and stopping", flush=True)
            break
        subprocess.run([*archive, "--index", str(index)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", type=int, required=True)
    run_pilot(parser.parse_args().through)
