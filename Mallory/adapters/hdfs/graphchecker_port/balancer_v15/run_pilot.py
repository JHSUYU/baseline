"""Resume the pinned V15c campaign one accepted fault at a time."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
CONFIG = ROOT / "inputs/campaign-config-v15c.json"
CONFIG_SHA = "d672b5136f381b532345f8985b8dcbde831683e26b2a37cda2134b14d617537a"
SOURCE_SHA = "0ea4edf18980fc61ba0da22c190ce43a31046f0586290ffd53aff35d5e14c890"
OUTPUT = ROOT / "formal-v15c"
RAW = ROOT / "raw-v15c"
ARCHIVE = Path("/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-v15c-pilot")


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.through <= 16:
        raise ValueError("pilot must stop within trial 1..16")
    if sha(CONFIG) != CONFIG_SHA:
        raise ValueError("campaign config changed")
    if sha(Path(__file__).resolve().parents[4] / "native_graphchecker_campaign/campaign.py") != SOURCE_SHA:
        raise ValueError("campaign source changed")
    if not (ROOT / "guarded-healthy-v15c.json").is_file():
        raise ValueError("healthy gate receipt absent")
    healthy = json.loads((ROOT / "guarded-healthy-v15c.json").read_text())
    if healthy.get("status") != "healthy_seed":
        raise ValueError("healthy graph gate did not pass")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archive_script = Path(__file__).resolve().parents[1] / "balancer_short_lifetime_repeat_v1/archive_trial.py"
    if not (ARCHIVE / "raw-r0000-receipt.json").exists():
        subprocess.run([sys.executable, str(archive_script), "--output", str(OUTPUT),
                        "--raw-root", str(RAW), "--archive-root", str(ARCHIVE),
                        "--index", "0"], check=True)
    while True:
        state = json.loads((OUTPUT / "checkpoint.json").read_text())
        done = state["completed_fault_trials"]
        if done >= args.through:
            break
        index = done + 1
        command = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
                   "--propagation", "private", "sh", "-c",
                   'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"',
                   "sh", "/proj/silentfailure-PG0", sys.executable,
                   "-m", "Mallory.native_graphchecker_campaign.guarded_one_fault",
                   "--pg0", "/proj/silentfailure-PG0", "--config", str(CONFIG),
                   "--output", str(OUTPUT), "--raw-root", str(RAW),
                   "--attempt-id", f"v15c-r{index:04d}",
                   "--config-sha256", CONFIG_SHA,
                   "--campaign-source-sha256", SOURCE_SHA,
                   "--max-raw-bytes", "600000000", "--max-output-bytes", "3000000000",
                   "--min-raw-available-bytes", "5000000000",
                   "--min-output-available-bytes", "5000000000",
                   "--min-root-available-bytes", "1600000000",
                   "--min-memory-available-bytes", "10000000000",
                   "--max-wall-seconds", "900", "--poll-seconds", "1"]
        print(f"starting r{index:04d}", flush=True)
        subprocess.run(command, check=True, cwd=Path(__file__).resolve().parents[5])
        state = json.loads((OUTPUT / "checkpoint.json").read_text())
        result = json.loads((OUTPUT / f"trials/r{index:04d}/result.json").read_text())
        if state["completed_fault_trials"] != index or not result.get("strict_injection"):
            raise RuntimeError(f"r{index:04d} not a strict accepted fault")
        print(json.dumps({"index": index, "status": result.get("status"),
                          "depth": len(result.get("faults", [])),
                          "raw_exact_target_throw_count": result.get("raw_exact_target_throw_count"),
                          "target_after_fault": result.get("post_fault_target_check_observed")},
                         sort_keys=True), flush=True)
        if result.get("raw_exact_target_throw_count", 0) > 0:
            print("candidate target throw: preserving raw and stopping", flush=True)
            break
        subprocess.run([sys.executable, str(archive_script), "--output", str(OUTPUT),
                        "--raw-root", str(RAW), "--archive-root", str(ARCHIVE),
                        "--index", str(index)], check=True)


if __name__ == "__main__":
    main()
