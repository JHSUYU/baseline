"""Continue a pinned V17 bounded import one tool-selected fault at a time."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path("/dev/shm/mallory-hdfs-balancer-v17-node0")
CONFIG = ROOT / "campaign-config-v17-pinned.json"
OUTPUT = ROOT / "formal"
RAW = ROOT / "raw"
ARCHIVE = Path("/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-v17-pilot")
HEALTHY = ROOT / "guarded-healthy-v17.json"
ARCHIVE_SCRIPT = Path(__file__).resolve().with_name("archive_trial_v17.py")
CAMPAIGN_SOURCE = Path(__file__).resolve().parents[4] / "native_graphchecker_campaign/campaign.py"
PINS = {
    CONFIG: "1603a8480c958a9cd443e0c739183a150399906c03e7724965a16076ac6500b6",
    CAMPAIGN_SOURCE: "fdfdfc88f3ade0531b43b8b584252f571b75b96a3bea2a21647d6a974fcc7855",
    ARCHIVE_SCRIPT: "ec382f22f2e7187bc9ee864779c51944ad85045397c80dab4b3ca23160814dcc",
}
ENGINE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/native-repeated-io-v1/"
                   "Mallory/static_scope_port/original_engine")
IMPORT_SHA = "cca74df5112f7b3018d3e5d8ec7cc4fe2664ea7734d6ab1c70258c82861e1168"
CASE_ID = "HDFS-11-TIMING-MONITOR-K8-DEPTH-V17"
IMPORTED_COUNT = 16


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _state() -> dict:
    return json.loads((OUTPUT / "checkpoint.json").read_text())


def run(through_local: int) -> None:
    if not 1 <= through_local <= 256:
        raise ValueError("local continuation bound must be within 1..256")
    for path, digest in PINS.items():
        if sha(path) != digest:
            raise ValueError(f"pinned V17 input changed: {path}")
    if sha(OUTPUT / "predecessor-import.json") != IMPORT_SHA:
        raise ValueError("V17 bounded predecessor import changed")
    if not (ENGINE_ROOT / "target/native-original-engine-receipt.json").is_file():
        raise ValueError("source-built native original engine receipt absent")
    gate = json.loads(HEALTHY.read_text())
    healthy = json.loads((OUTPUT / "trials/r0000/result.json").read_text())
    if (gate.get("status") != "healthy_seed" or
            gate.get("predecessor_import_sha256") != IMPORT_SHA or
            gate.get("config_sha256") != PINS[CONFIG] or
            healthy.get("case_id") != CASE_ID or
            healthy.get("status") != "healthy_seed" or
            healthy.get("junit_passed") is not True or
            healthy.get("raw_exact_target_throw_count") != 0 or
            len(healthy.get("multi_anchor_addresses", [])) != 8):
        raise ValueError("V17 original JUnit/K8/zero-throw healthy gate failed")
    state = _state()
    if (state.get("case_id") != CASE_ID or
            state.get("imported_completed_fault_trials") != IMPORTED_COUNT or
            state.get("predecessor_import", {}).get("source_completed_fault_trials") != IMPORTED_COUNT or
            state.get("healthy", {}).get("status") != "healthy_seed"):
        raise ValueError("V17 checkpoint is not the pinned bounded successor")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archive = [sys.executable, str(ARCHIVE_SCRIPT), "--output", str(OUTPUT),
               "--raw-root", str(RAW), "--archive-root", str(ARCHIVE)]
    if not (ARCHIVE / "raw-r0000-receipt.json").exists():
        subprocess.run([*archive, "--index", "0"], check=True)
    while True:
        state = _state()
        done = state["completed_fault_trials"]
        if done >= through_local:
            break
        index = state["next_trial_index"]
        if (index < IMPORTED_COUNT + 1 or state.get("active") is not None or
                index != IMPORTED_COUNT + done + 1):
            raise ValueError("V17 local count and absolute fault index diverged")
        command = ["unshare", "-U", "-c", "--keep-caps", "-m", "--fork",
                   "--propagation", "private", "sh", "-c",
                   'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"',
                   "sh", "/proj/silentfailure-PG0", sys.executable, "-m",
                   "Mallory.native_graphchecker_campaign.guarded_one_fault",
                   "--pg0", "/proj/silentfailure-PG0", "--config", str(CONFIG),
                   "--output", str(OUTPUT), "--raw-root", str(RAW),
                   "--attempt-id", f"v17-r{index:04d}",
                   "--config-sha256", PINS[CONFIG],
                   "--campaign-source-sha256", PINS[CAMPAIGN_SOURCE],
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
        state = _state()
        result = json.loads((OUTPUT / f"trials/r{index:04d}/result.json").read_text())
        if (state["completed_fault_trials"] != done + 1 or
                result.get("case_id") != CASE_ID or
                result.get("strict_injection") is not True):
            raise RuntimeError(f"r{index:04d} was not a strict accepted V17 fault")
        summary = {"index": index, "depth": len(result.get("faults", [])),
                   "status": result.get("status"),
                   "target_after_fault": result.get("post_fault_target_check_observed"),
                   "raw_exact_target_throw_count": result.get("raw_exact_target_throw_count")}
        print(json.dumps(summary, sort_keys=True), flush=True)
        if result.get("raw_exact_target_throw_count", 0) > 0:
            print("candidate exact target throw: preserving raw and stopping", flush=True)
            break
        subprocess.run([*archive, "--index", str(index)], check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--through-local", type=int, required=True)
    run(ap.parse_args().through_local)
