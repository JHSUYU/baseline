#!/usr/bin/env python3
"""GO-gated SOLR-15 v3 continuation from a verified v2 checkpoint replay."""

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
V2 = HERE.parent / "fault-bootstrap-node0-v2"
OUT = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v3"
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
AGENT = HERE / "agent/release/mallory-agent.jar"
AGENT_MANIFEST = HERE / "agent/release/manifest.json"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402
import audit_trial  # noqa: E402
import prepare_checkpoint as seed  # noqa: E402

ORIGINAL_PICK = campaign.pick_next
ORIGINAL_APPLY = campaign._apply_result


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_config() -> dict:
    config = copy.deepcopy(read(V2 / "config-full-node0.json"))
    old_agent = config["agent_jar"]
    config["agent_jar"] = str(AGENT)
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    config["mapping"]["agent_sha256"] = sha(AGENT)
    config["mapping"]["agent_build"] = {
        "artifact": str(AGENT), "source_root": str(HERE / "agent"),
        "release_manifest": str(AGENT_MANIFEST)}
    config["mapping"]["door_status"] = (
        "runtime_resource_qualified_depth_three_continuation_staged")
    config["mapping"]["status"] = "v2_replay_seeded_v3_pending_node0"
    config["mapping"]["runner_status"] = (
        "checkpoint_safe_original_junit_continuation_staged")
    config["revision"] = "SOLR-15-resource-qualified-depth-three-continuation-node0-v3"
    for row in config["runtime_artifacts"]:
        if row["path"] == old_agent:
            row.update(path=str(AGENT), sha256=sha(AGENT))
        elif row["path"] == str(Path(old_agent).with_name("manifest.json")):
            row.update(path=str(AGENT_MANIFEST), sha256=sha(AGENT_MANIFEST))
    return config


def preflight() -> dict:
    package = read(HERE / "sha-manifest.json")
    if (package.get("case_id") != "SOLR-15" or
            package.get("variant") != "fault-bootstrap-node0-v3" or
            package.get("v2_manifest_sha256") != sha(V2 / "sha-manifest.json")):
        raise ValueError("wrong case-local v3 package")
    for name, record in package["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"] or
                sha(path) != record["sha256"]):
            raise ValueError("v3 package file changed: " + name)
    agent_manifest = read(AGENT_MANIFEST)
    if (agent_manifest.get("agent_sha256") != sha(AGENT) or
            agent_manifest.get("selector_tests") !=
            {"tests": 7, "failures": 0, "errors": 0, "skipped": 0} or
            agent_manifest.get("selector_test_receipt_sha256") !=
            sha(HERE / "agent/release/selector-tests.txt") or
            "Tests run: 7, Failures: 0, Errors: 0, Skipped: 0" not in
            (HERE / "agent/release/selector-tests.txt").read_text()):
        raise ValueError("unsealed v3 resource-qualified agent")
    for name, digest in agent_manifest["source_sha256"].items():
        if sha(HERE / name) != digest:
            raise ValueError("v3 agent source changed: " + name)
    check = subprocess.run([sys.executable, "-B", str(V2 / "run_campaign.py"),
                            "--preflight-only"], capture_output=True, text=True)
    if check.returncode != 0:
        raise ValueError("sealed v2 package preflight failed: " + check.stderr[-1200:])
    config = read(HERE / "config-full-node0.json")
    if config != expected_config() or config["budget"] != {
            "trials": 12, "seconds": 2400,
            "trial_timeout_seconds": 480, "max_faults_per_trial": 3}:
        raise ValueError("v3 config changes the pinned 12-trial search")
    campaign.validate_config(config)
    _, receipt = seed.reconstruct(config)
    if receipt != read(HERE / "reconstruction-receipt.json"):
        raise ValueError("v3 checkpoint replay receipt changed")
    request = read(HERE / "admission-request.json")
    required = {"go": False, "stage_only": True, "case_id": "SOLR-15",
                "variant": "fault-bootstrap-node0-v3", "host": "node0", "mode": "full",
                "config_sha256": sha(HERE / "config-full-node0.json"),
                "runner_sha256": sha(HERE / "run_campaign.py"),
                "agent_sha256": sha(AGENT), "intended_output": str(OUT)}
    if any(request.get(key) != value for key, value in required.items()):
        raise ValueError("v3 admission request changed")
    return {"status": "preflight_passed", "case_id": "SOLR-15",
            "variant": "fault-bootstrap-node0-v3", "intended_output": str(OUT),
            "config_sha256": required["config_sha256"],
            "runner_sha256": required["runner_sha256"],
            "agent_sha256": required["agent_sha256"],
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "source_checkpoint_sha256": receipt["source_checkpoint_sha256"],
            "next_trial": receipt["next_trial"],
            "remaining_queue": receipt["remaining_queue"]}


def _validate_item(item: dict) -> None:
    faults = item.get("faults", [])
    if (len(faults) != 3 or
            [f.get("point", {}).get("solr15_parent_lookup") for f in faults[:2]] !=
            ["second", "retry"]):
        raise ValueError("v3 queue contains a noncontinuation plan")
    third = faults[2]["point"]
    if third.get("site") == audit_trial.seed.NATIVE:
        phase = third.get("solr15_parent_lookup")
        if phase == "after_pair":
            if (third.get("resource_role") == "bound_parent") == bool(third.get("resource")):
                raise ValueError("native third lacks one pre-injection resource")
        elif phase == "explicit_resource":
            if (not third.get("resource") or not third.get("occurrence") or
                    not isinstance(third.get("door_ordinal"), int)):
                raise ValueError("outside native third lacks strict path identity")
        else:
            raise ValueError("native third lacks runtime path selector")
    elif (not third.get("occurrence") or
          not isinstance(third.get("door_ordinal"), int) or
          not third.get("node") or third.get("epoch") is None):
        raise ValueError("nonnative third lacks actor/epoch/occurrence/ordinal")


def _picked(queue: list[dict], next_trial: int,
            fault_trials_completed: int, config: dict) -> dict:
    item = ORIGINAL_PICK(queue, next_trial, fault_trials_completed, config)
    _validate_item(item)
    if "scope_tier" not in item:
        item["scope_tier"] = ("dynamic_closure" if item["faults"][-1]["point"].get(
            "resource_role") == "bound_parent" else "outside_closure")
    return item


def _drop_feedback(feedback: dict) -> None:
    feedback.update(coverage_ids=[], closure_coverage_ids=[], closure_edges=[],
                    doors=[], target_reached=False, target_check_reached=False,
                    target_threw=False, target_exception_candidate=False,
                    target_check_actors=[], target_instances=[], target_closures=[],
                    all_faults_matched=False, all_faults_applied=False,
                    all_faults_effective=False, status="dropped_invalid_depth_three")


def _applied(state: dict, config: dict, result: dict, item: dict | None) -> None:
    trial_id = result["trial_id"]
    if trial_id < 5:
        raise ValueError("v3 must never replay a v2 completed trial")
    if item is None:
        raise ValueError("v3 trial lacks its selected queue item")
    _validate_item(item)
    if result.get("plan") != item["faults"]:
        raise ValueError("trial plan differs from the selected qualified queue item")
    trial = OUT / "trials" / f"r{trial_id:04d}"
    raw_path = trial / "raw-result.json"
    if raw_path.exists():
        result = read(raw_path)
    else:
        shutil.copyfile(trial / "result.json", raw_path)
    if result.get("plan") != item["faults"]:
        raise ValueError("archived raw trial plan differs from selected item")
    feedback = result["feedback"]
    reason = None
    try:
        attestation = audit_trial.attest(trial, result["plan"])
        if feedback.get("all_faults_effective") is not True:
            raise ValueError("core did not attest all planned faults effective")
        if not attestation["target_after_all_faults"]:
            raise ValueError("target check did not follow all three applied faults")
        if bool(feedback.get("target_check_reached")) != attestation["target_after_all_faults"]:
            raise ValueError("target observation differs from after-all-faults gate")
        if (feedback.get("target_exception_candidate") and
                not attestation["target_throw_after_all_faults"]):
            raise ValueError("target throw did not follow all three applied faults")
    except (ValueError, OSError, KeyError) as error:
        reason = str(error)
        _drop_feedback(feedback)
        result["resource_attestation"] = {"valid": False, "reason": reason}
        result["dropped_no_credit"] = {"reason": reason,
                                       "raw_result_sha256": sha(raw_path),
                                       "scope_tier": item.get("scope_tier", "outside_closure")}
    else:
        if not attestation["target_throw_after_all_faults"]:
            feedback["target_threw"] = False
            feedback["qualified_target_throw_evidence"] = []
        result["resource_attestation"] = attestation
    result["scope_tier"] = item.get("scope_tier", "outside_closure")
    ORIGINAL_APPLY(state, config, result, item)
    if reason is not None:
        state.setdefault("dropped_trials", []).append({"trial_id": trial_id,
            "reason": reason, "raw_result_sha256": sha(raw_path),
            "scope_tier": result["scope_tier"]})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps(metadata, sort_keys=True))
        return 0
    if socket.gethostname().split(".", 1)[0] != "node0":
        parser.error("node0 runtime required")
    if args.admission_receipt is None or args.admission_receipt.resolve() != \
            HERE / "admission-full-node0.json":
        parser.error("case-local node0 steward GO receipt required before a JVM")
    receipt = read(args.admission_receipt)
    required = {"go": True, "host": "node0", "case_id": "SOLR-15",
                "mode": "full", "variant": "fault-bootstrap-node0-v3",
                "config_sha256": metadata["config_sha256"],
                "runner_sha256": metadata["runner_sha256"],
                "agent_sha256": metadata["agent_sha256"],
                "source_checkpoint_sha256": metadata["source_checkpoint_sha256"],
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
        seed.prepare(read(HERE / "config-full-node0.json"))
        campaign.pick_next = _picked
        campaign._apply_result = _applied
        print(json.dumps({"status": "admitted", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(HERE / "config-full-node0.json", OUT)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "dropped_trials": state.get("dropped_trials", []),
                      "target_discovered_trial": state.get("target_discovered_trial")},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
