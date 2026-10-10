#!/usr/bin/env python3
"""No-JVM preflight for the sealed SOLR-40 exact-reference full package."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import audit_v2
from seed_gate import validate_seed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V3 = HERE.parent / "healthy-watcher-handoff-node0-v3"
V3_RAW = ROOT / "data/mallory/calibration_solr40_reference_handoff_v3_node0/SOLR-40"
SEAL_ROOT = ROOT / "data/mallory/evidence_archives"
SEAL_NAME = "SOLR-40-reference-healthy-node0-v3"
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def main() -> dict:
    manifest = json.loads((HERE / "release-manifest.json").read_text())
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    jar = HERE / "releases/mallory-agent.jar"
    prior = subprocess.run([sys.executable, str(V3 / "run_healthy_v3.py"),
                            "--preflight-only"], cwd=ROOT, capture_output=True,
                           text=True, check=True)
    require(json.loads(prior.stdout.splitlines()[-1])["status"] ==
            "offline_v3_runner_recognized", "v3 source release preflight failed")
    receipt_path = SEAL_ROOT / f"{SEAL_NAME}.receipt.json"
    archive = SEAL_ROOT / f"{SEAL_NAME}.tar.gz"
    members = SEAL_ROOT / f"{SEAL_NAME}.members.json"
    require(sha(receipt_path) == manifest["v3_seal_receipt_sha256"] and
            sha(archive) == manifest["v3_archive_sha256"] and
            sha(members) == manifest["v3_members_sha256"],
            "v3 SHA seal changed")
    seal = json.loads(receipt_path.read_text())
    require(seal["case_id"] == "SOLR-40" and
            seal["status"] == "healthy_observation_passed" and
            seal["all_archive_members_verified"] is True and
            seal["eligible_for_full_review"] is True and
            seal["exact_reference_witness_count"] >= 1 and
            seal["named_exact_target_checks"] >= 1 and
            seal["named_watcher_doors"] >= 1 and
            seal["junit"] == "1/0/0/0" and
            seal["full_campaign_go"] is False and
            seal["fault_trials_completed"] == 0 and
            seal["archive_sha256"] == sha(archive) and
            seal["member_manifest_sha256"] == sha(members) and
            seal["config_sha256"] == sha(V3 / "config.json") and
            seal["result_sha256"] == sha(V3_RAW / "result.json") and
            seal["trace_sha256"] == sha(V3_RAW / "trials/r0000/events.jsonl.gz") and
            seal["handoff_audit_sha256"] == sha(V3_RAW / "handoff-audit.json") and
            seal["trial_result_sha256"] == sha(V3_RAW / "trials/r0000/result.json"),
            "v3 sealed healthy receipt is not an exact-reference source")
    require(sha(V3 / "release-manifest.json") == manifest["v3_release_manifest_sha256"] and
            sha(config_path) == manifest["config_sha256"] and
            sha(jar) == manifest["agent_jar_sha256"] ==
            sha(V3 / "releases/mallory-agent.jar") and
            sha(HERE / "sites.json") == manifest["sites_sha256"] and
            sha(HERE / "run_pilot.py") == manifest["pilot_runner_sha256"] and
            sha(HERE / "run_full.py") == manifest["full_runner_sha256"] and
            sha(HERE / "gate_v2.py") == manifest["gate_sha256"] and
            sha(HERE / "call_return.py") == manifest["call_return_sha256"] and
            sha(HERE / "audit_v2.py") == manifest["post_audit_sha256"] and
            sha(HERE / "seed_gate.py") == manifest["seed_gate_sha256"] and
            sha(HERE / "test_full_gate.py") == manifest["full_gate_test_sha256"],
            "full package digest changed")
    require(config["case_id"] == "SOLR-40" and
            config["revision"] == "SOLR-40-full-exact-reference-handoff-node0-v2" and
            config["cluster_test"] ==
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test" and
            config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["explore_outside_closure"] is False and
            config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 480} and
            config["fault_types"] == ["EXCEPTION"] and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["admission"]["full_promotion"] is True and
            config["agent_jar"] == str(jar) and
            config["env"]["MALLORY_SOLR_AGENT_JAR"] == str(jar) and
            config["command"][1] == str(HERE / "run_pilot.py") and
            config["site_file"] == str(HERE / "sites.json"),
            "full exact-reference campaign policy changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"full runtime artifact changed: {path}")
    request = json.loads((HERE / "admission-request.json").read_text())
    require(request.get("go") is False and
            request.get("case_id") == "SOLR-40" and
            request.get("host") == "node0" and request.get("mode") == "full" and
            request.get("config_sha256") == sha(config_path) and
            request.get("agent_jar_sha256") == sha(jar) and
            request.get("runner_sha256") == sha(HERE / "run_full.py") and
            request.get("intended_output") == str(
                ROOT / "data/mallory/solr40_reference_full_v2_node0/SOLR-40") and
            request.get("admission_receipt") == str(HERE / "admission-full-node0.json") and
            sha(HERE / "admission-request.json") == manifest["admission_request_sha256"],
            "full GO request changed")
    sys.path.insert(0, str(PINNED))
    from Mallory.core import campaign  # noqa: E402
    from Mallory.core.junit import runner_kind  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(PINNED) and
            runner_kind(config["command"]) == "solr_junit_wrapper",
            "pinned core or JUnit wrapper recognition changed")
    campaign.validate_config(config)
    raw_summary = json.loads((V3_RAW / "result.json").read_text())
    raw_trial = json.loads((V3_RAW / "trials/r0000/result.json").read_text())
    raw_audit = audit_v2.audit(V3_RAW)
    admitted = validate_seed(raw_summary, raw_trial, raw_audit)
    require(len(admitted["exact_reference_witnesses"]) ==
            seal["exact_reference_witness_count"] and
            sorted(admitted["exact_reference_witnesses"]) ==
            seal["exact_reference_witness_event_ids"],
            "recomputed v3 exact-reference witnesses disagree with seal")
    receipt = {"case_id": "SOLR-40", "status": "offline_full_stage_passed",
               "config_sha256": sha(config_path), "agent_jar_sha256": sha(jar),
               "v3_seal_receipt_sha256": sha(receipt_path),
               "source_healthy_witnesses": len(admitted["exact_reference_witnesses"]),
               "budget": config["budget"], "junit_launched": False,
               "fault_campaign_launched": False}
    print(json.dumps(receipt, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
