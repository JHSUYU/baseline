#!/usr/bin/env python3
"""GO-gated SOLR-15 same-parent fault bootstrap, then pinned Mallory search."""

from __future__ import annotations

import argparse
import copy
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V3 = HERE.parent / "path-aware-healthy-node0-v3"
OUT = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v1"
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402
sys.path.insert(0, str(HERE))
import seed_selector as seed  # noqa: E402

ORIGINAL_PICK = campaign.pick_next
ORIGINAL_APPLY = campaign._apply_result


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_config() -> dict:
    config = copy.deepcopy(read(V3 / "config-healthy-node0.json"))
    config["calibration_only"] = False
    config["auto_promote_if_healthy"] = True
    config["budget"] = {"trials": 12, "seconds": 2400,
                        "trial_timeout_seconds": 480, "max_faults_per_trial": 3}
    config["target_absent_bootstrap"] = {
        "door_sites": [seed.NATIVE], "max_doors_per_trial": 200,
        "max_faults_per_trial": 2, "max_trials": 12}
    config["revision"] = "SOLR-15-same-path-fault-bootstrap-node0-v1"
    config["candidate_replays"] = 1
    return config


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-15" or manifest.get("variant") != "fault-bootstrap-node0-v1":
        raise ValueError("wrong case-local bootstrap manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError("case-local bootstrap file changed: " + name)
    # A separate Python process avoids the v3 runner's generic module-name
    # import (`run_campaign`) resolving to this case-local runner.
    check = subprocess.run([sys.executable, "-B", str(V3 / "run_campaign.py"),
                            "--preflight-only"], capture_output=True, text=True)
    if check.returncode != 0:
        raise ValueError("pinned healthy package preflight failed: " + check.stderr[-1200:])
    pinned = json.loads(check.stdout.splitlines()[-1])
    config = read(HERE / "config-full-node0.json")
    if config != expected_config():
        raise ValueError("bootstrap config differs from audited healthy package")
    campaign.validate_config(config)
    gate = read(ROOT / "data/mallory/solr15_path_healthy_node0_v3/healthy/"
                "path-aware-healthy-gate.json")
    gate_path = (ROOT / "data/mallory/solr15_path_healthy_node0_v3/healthy/"
                 "path-aware-healthy-gate.json")
    if sha(gate_path) != manifest["prior_healthy_gate_sha256"]:
        raise ValueError("prior path-aware healthy gate changed")
    if (gate.get("status") != "passed" or
            gate.get("resource_path_attested") is not True or
            gate.get("resource_binding", {}).get("second_native_event_id") !=
            "SOLR-15-r0000:1899"):
        raise ValueError("prior same-parent path-aware healthy audit missing")
    original = ROOT / "data/mallory/solr15_path_healthy_node0_v3/healthy/trials/r0000"
    second = seed.second_lookup(original)
    if second.get("id") != gate["resource_binding"]["second_native_event_id"]:
        raise ValueError("original native event is not bound to the audited path")
    return {**pinned, "case_id": "SOLR-15", "mode": "full",
            "intended_output": str(OUT),
            "config_sha256": sha(HERE / "config-full-node0.json"),
            "runner_sha256": sha(HERE / "run_campaign.py"),
            "selector_sha256": sha(HERE / "seed_selector.py"),
            "healthy_gate_sha256": sha(ROOT / "data/mallory/solr15_path_healthy_node0_v3/"
                                        "healthy/path-aware-healthy-gate.json"),
            "core_release": config["core_release"]}


def _picked(queue: list[dict], next_trial: int,
            fault_trials_completed: int, config: dict) -> dict:
    if next_trial == 1:
        trial = OUT / "trials/r0000"
        healthy = read(trial / "result.json")
        if (healthy.get("feedback", {}).get("status") != "healthy_target_missing"
                or healthy.get("junit_validation", {}).get("status") != "passed"):
            raise ValueError("fresh healthy trial did not pass target-absent gate")
        door = seed.second_lookup(trial)
        return seed.pick_exact(queue, seed.point_of(door), faults=1)
    if next_trial == 2:
        first = read(OUT / "trials/r0001/result.json")
        if first.get("feedback", {}).get("target_check_reached"):
            return ORIGINAL_PICK(queue, next_trial, fault_trials_completed, config)
        plan = first.get("plan", [])
        if len(plan) != 1:
            raise ValueError("first bootstrap plan missing")
        door = seed.retry_after_fault(OUT / "trials/r0001", plan[0])
        return seed.pick_exact(queue, seed.point_of(door), faults=2)
    return ORIGINAL_PICK(queue, next_trial, fault_trials_completed, config)


def _applied(state: dict, config: dict, result: dict, item: dict | None) -> None:
    plan = result.get("plan", [])
    if any("expected_resource_role" in fault for fault in plan):
        trial = OUT / "trials" / f"r{result['trial_id']:04d}"
        try:
            seed.attest_fault_resources(trial, plan)
        except (ValueError, OSError, KeyError) as error:
            result["resource_attestation"] = {"valid": False, "reason": str(error)}
            result["feedback"]["all_faults_effective"] = False
            result["feedback"]["target_exception_candidate"] = False
            result["feedback"]["status"] = "fault_resource_mismatch"
        else:
            result["resource_attestation"] = {
                "valid": True, "role": "same-run parent-leader live znode"}
    ORIGINAL_APPLY(state, config, result, item)
    if result.get("resource_attestation", {}).get("valid") is False:
        state["status"] = "fault_resource_mismatch"
        state["queue"].clear()
    elif (result["trial_id"] == 2 and state.get("target_binding") is None):
        state["status"] = "queue_exhausted"
        state["bootstrap_stop_reason"] = "exact_target_absent_after_same_path_pair"
        state["queue"].clear()


def _seal_selection_gap(error: ValueError) -> dict:
    checkpoint = OUT / "checkpoint.json"
    if not checkpoint.exists():
        raise error
    state = read(checkpoint)
    if state.get("running") is not None:
        raise error
    state["status"] = "queue_exhausted"
    state["bootstrap_stop_reason"] = str(error)
    state["queue"] = []
    campaign.atomic_json(checkpoint, state)
    campaign._write_summary(OUT, state, read(HERE / "config-full-node0.json"))
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"status": "preflight_passed", **metadata}, sort_keys=True))
        return 0
    if socket.gethostname().split(".", 1)[0] != "node0":
        parser.error("node0 runtime required")
    if args.admission_receipt is None:
        parser.error("node0 steward GO receipt required before starting a JVM")
    if args.admission_receipt.resolve() != HERE / "admission-full-node0.json":
        parser.error("case-local node0 GO receipt required")
    receipt = read(args.admission_receipt)
    required = {"go": True, "host": "node0", "case_id": "SOLR-15",
                "mode": "full", "config_sha256": metadata["config_sha256"],
                "runner_sha256": metadata["runner_sha256"],
                "intended_output": str(OUT)}
    if any(receipt.get(key) != value for key, value in required.items()):
        parser.error("node0 steward GO receipt missing or mismatched")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = locks.enter_context((lock_root / name).open("a+"))
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"]
               for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        campaign.pick_next = _picked
        campaign._apply_result = _applied
        print(json.dumps({"status": "admitted", **metadata}, sort_keys=True), flush=True)
        try:
            state = campaign.run(HERE / "config-full-node0.json", OUT)
        except ValueError as error:
            if ("same-parent" not in str(error) and "native" not in str(error)
                    and "bootstrap" not in str(error) and "live-node" not in str(error)):
                raise
            state = _seal_selection_gap(error)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "target_discovered_trial": state.get("target_discovered_trial"),
                      "bootstrap_stop_reason": state.get("bootstrap_stop_reason")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
