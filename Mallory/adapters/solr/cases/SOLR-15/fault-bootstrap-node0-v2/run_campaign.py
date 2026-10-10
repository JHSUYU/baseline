#!/usr/bin/env python3
"""GO-gated SOLR-15 runtime-qualified parent bootstrap, then pinned search."""

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
V1 = HERE.parent / "fault-bootstrap-node0-v1"
OUT = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v2"
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
AGENT = HERE / "agent/release/mallory-agent.jar"
AGENT_MANIFEST = HERE / "agent/release/manifest.json"
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
    config = copy.deepcopy(read(V1 / "config-full-node0.json"))
    old_agent = config["agent_jar"]
    config["agent_jar"] = str(AGENT)
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    config["mapping"]["agent_sha256"] = sha(AGENT)
    config["mapping"]["agent_build"] = {
        "artifact": str(AGENT), "source_root": str(HERE / "agent"),
        "release_manifest": str(AGENT_MANIFEST)}
    config["mapping"]["door_status"] = (
        "runtime_qualified_parent_lookup_selector_built_not_campaign_validated")
    config["mapping"]["status"] = "target_absent_runtime_selector_staged"
    config["mapping"]["runner_status"] = (
        "isolated_original_chaos_junit_staged_for_node0")
    config["revision"] = "SOLR-15-runtime-qualified-parent-bootstrap-node0-v2"
    for row in config["runtime_artifacts"]:
        if row["path"] == old_agent:
            row.update(path=str(AGENT), sha256=sha(AGENT))
        elif row["path"] == str(Path(old_agent).with_name("manifest.json")):
            row.update(path=str(AGENT_MANIFEST), sha256=sha(AGENT_MANIFEST))
    return config


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if (manifest.get("case_id") != "SOLR-15" or
            manifest.get("variant") != "fault-bootstrap-node0-v2" or
            manifest.get("prior_v1_manifest_sha256") !=
            sha(V1 / "sha-manifest.json")):
        raise ValueError("wrong case-local bootstrap manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError("case-local bootstrap file changed: " + name)
    agent_manifest = read(AGENT_MANIFEST)
    if (agent_manifest.get("agent_sha256") != sha(AGENT) or
            agent_manifest.get("selector_tests") !=
            {"tests": 4, "failures": 0, "errors": 0, "skipped": 0} or
            agent_manifest.get("selector_test_receipt_sha256") !=
            sha(HERE / "agent/release/selector-tests.txt") or
            "Tests run: 4, Failures: 0, Errors: 0, Skipped: 0" not in
            (HERE / "agent/release/selector-tests.txt").read_text()):
        raise ValueError("unsealed runtime selector agent")
    for name, digest in agent_manifest["source_sha256"].items():
        if sha(HERE / name) != digest:
            raise ValueError("runtime selector agent source changed: " + name)
    check = subprocess.run([sys.executable, "-B", str(V1 / "run_campaign.py"),
                            "--preflight-only"], capture_output=True, text=True)
    if check.returncode != 0:
        raise ValueError("pinned v1 package preflight failed: " + check.stderr[-1200:])
    pinned = json.loads(check.stdout.splitlines()[-1])
    prior = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v1/trials/r0001"
    old_plan = read(prior / "plan.json")["faults"]
    old_rows = seed.events(prior)
    wrong = [row for row in old_rows if row.get("type") == "FAULT_APPLIED"
             and row.get("fault_id") == old_plan[0]["fault_id"]]
    native = [row for row in old_rows if row.get("id") == "SOLR-15-r0001:1898"]
    if (len(wrong) != 1 or wrong[0].get("resource") != "/overseer/queue" or
            wrong[0].get("door_ordinal") != 42 or len(native) != 1 or
            native[0].get("door_ordinal") != 47 or
            native[0].get("resource") != seed.second_lookup(prior)["resource"]):
        raise ValueError("v1 terminal mismatch evidence changed")
    config = read(HERE / "config-full-node0.json")
    if config != expected_config():
        raise ValueError("bootstrap config differs from audited healthy package")
    campaign.validate_config(config)
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("stage_only") is not True or
            request.get("case_id") != "SOLR-15" or request.get("host") != "node0" or
            request.get("mode") != "full" or
            request.get("config_sha256") != sha(HERE / "config-full-node0.json") or
            request.get("runner_sha256") != sha(HERE / "run_campaign.py") or
            request.get("selector_sha256") != sha(HERE / "seed_selector.py") or
            request.get("agent_sha256") != sha(AGENT) or
            request.get("intended_output") != str(OUT)):
        raise ValueError("case-local node0 admission request changed")
    return {**pinned, "case_id": "SOLR-15", "mode": "full",
            "intended_output": str(OUT),
            "config_sha256": sha(HERE / "config-full-node0.json"),
            "runner_sha256": sha(HERE / "run_campaign.py"),
            "selector_sha256": sha(HERE / "seed_selector.py"),
            "agent_sha256": sha(AGENT),
            "agent_manifest_sha256": sha(AGENT_MANIFEST),
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
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
            target_after_fault = seed.attest_target_after_fault(trial, plan)
        except (ValueError, OSError, KeyError) as error:
            result["resource_attestation"] = {"valid": False, "reason": str(error)}
            result["feedback"]["all_faults_effective"] = False
            result["feedback"]["target_exception_candidate"] = False
            result["feedback"]["status"] = "fault_resource_mismatch"
        else:
            result["resource_attestation"] = {
                "valid": True, "role": "same-run parent-leader live znode",
                "target_after_fault": target_after_fault}
            if (not target_after_fault and any(result["feedback"].get(key) for key in
                                             ("target_reached", "target_check_reached",
                                              "target_exception_candidate"))):
                result["resource_attestation"] = {
                    "valid": False, "reason": "exact target not after qualified fault on same split"}
                result["feedback"].update(all_faults_effective=False,
                                          target_reached=False,
                                          target_check_reached=False,
                                          target_exception_candidate=False,
                                          status="target_after_fault_unattested")
    ORIGINAL_APPLY(state, config, result, item)
    if result.get("resource_attestation", {}).get("valid") is False:
        state["status"] = result["feedback"]["status"]
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
                "selector_sha256": metadata["selector_sha256"],
                "agent_sha256": metadata["agent_sha256"],
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
