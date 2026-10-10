#!/usr/bin/env python3
"""No-JVM immutable-input and prior healthy-role preflight for SOLR-09."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
HEALTHY = HERE.parent / "healthy-role-node1-v1"
PINNED = HERE.parent / "runtime-role-v1/work"
CHECK = ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd"
         "#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;Ljava/lang/String;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;"
         "Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V@277:branch:7")
DOOR = ("org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler"
        "#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1")
OUT = ROOT / "data/mallory/full_solr09_runtime_role_v1_node1/SOLR-09"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def main() -> dict:
    manifest = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "config.json").read_text())
    old = json.loads((HEALTHY / "config.json").read_text())
    require(manifest["schema_version"] == 1 and manifest["case_id"] == "SOLR-09",
            "wrong package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        require(path.is_file() and path.stat().st_size == record["bytes"] and
                sha(path) == record["sha256"], f"changed package member: {name}")
    require(sha(HEALTHY / "manifest.json") == manifest["healthy_manifest_sha256"],
            "healthy role package pin changed")
    sys.path.insert(0, str(HEALTHY))
    import preflight as healthy_preflight  # noqa: E402
    healthy_pins = healthy_preflight.main()
    require(config["case_id"] == "SOLR-09" and
            config["cluster_test"] == old["cluster_test"] and
            config["target"] == old["target"] and
            config["target"]["check_sites"] == [CHECK] and
            config["site_file"] == old["site_file"] and
            config["agent_jar"] == old["agent_jar"] and
            config["agent_properties"] == old["agent_properties"] and
            config["agent_include"] == old["agent_include"] and
            config["agent_transport"] == old["agent_transport"] and
            config["command"] == old["command"] and
            config["cwd"] == old["cwd"] and
            config["env"] == old["env"] and
            config["runtime_artifacts"] == old["runtime_artifacts"] and
            config["expected_target_class_sha256"] == old["expected_target_class_sha256"],
            "source, JUnit, target, or runtime changed from admitted healthy")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "trial_timeout_seconds": 480,
                                 "max_faults_per_trial": 3} and
            config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["fault_types"] == ["EXCEPTION"] and
            config["explore_outside_closure"] is False and
            config["require_event_time_paths"] is False and
            config["allow_local_timeline_doors"] is True and
            config["reject_coarse_roots"] is True and
            config["admission"]["host"] == "node1" and
            config["admission"]["output"] == str(OUT),
            "full campaign or graph-optional bounds changed")
    request = json.loads((HERE / "admission-request.json").read_text())
    require(request.get("go") is False and request.get("case_id") == "SOLR-09" and
            request.get("host") == "node1" and request.get("mode") == "full" and
            request.get("intended_output") == str(OUT) and
            request.get("config_sha256") == sha(HERE / "config.json") and
            request.get("runner_sha256") == sha(HERE / "run_campaign.py") and
            request.get("manifest_sha256") == sha(HERE / "manifest.json") and
            request.get("healthy_audit_sha256") == manifest["healthy_audit_sha256"] and
            request.get("lane_lock") == "/tmp/mallory-lanes/solr-node1-v1.lock" and
            request.get("source_lock") ==
            "/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock",
            "staged admission request changed or bypassed")
    sites = json.loads(Path(config["site_file"]).read_text())
    require(len(sites["doors"]) == 1 and sites["doors"][0] == manifest["door"] and
            sites["doors"][0]["exception_class"] ==
            "java.util.concurrent.TimeoutException" and
            DOOR.endswith("@434:door:1"), "exact typed door changed")
    sys.path.insert(0, str(PINNED))
    from Mallory.core import campaign  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(PINNED),
            "campaign core not from pinned case-local snapshot")
    campaign.validate_config(config)

    healthy_root = Path(manifest["healthy_output"])
    audit_path = healthy_root / "healthy-role-audit.json"
    result_path = healthy_root / "result.json"
    trial_result_path = healthy_root / "trials/r0000/result.json"
    require(audit_path.is_file() and sha(audit_path) == manifest["healthy_audit_sha256"],
            "admitted healthy audit missing or changed")
    require(result_path.is_file() and sha(result_path) == manifest["healthy_result_sha256"],
            "admitted healthy result missing or changed")
    require(trial_result_path.is_file() and
            sha(trial_result_path) == manifest["healthy_trial_result_sha256"],
            "admitted healthy trial result missing or changed")
    audit = json.loads(audit_path.read_text())
    result = json.loads(trial_result_path.read_text())
    matches = audit.get("same_occurrence_candidates", [])
    require(audit.get("case_id") == "SOLR-09" and
            audit.get("status") == "healthy_role_admitted" and
            audit.get("junit_passed_1_of_1") is True and
            audit.get("no_fault") is True and
            audit.get("no_target_throw") is True and
            audit.get("class_identity") is True and
            audit.get("exact_target_count") == 1 and
            audit.get("typed_door_count") == 1 and
            any(row.get("physical_registration") is True and
                row.get("unique_role_binding") is True and
                row.get("overseer_parent_handoff") is True and
                row.get("target_outcome") == "TAKEN" and
                row.get("door_event_id") and row.get("check_event_id") and
                row.get("node", "").startswith("node") and
                row.get("occurrence") for row in matches) and
            result.get("feedback", {}).get("status") == "observed" and
            result.get("feedback", {}).get("target_reached") is True and
            result.get("feedback", {}).get("target_threw") is False,
            "prior healthy-role evidence does not support full admission")
    for name, expected in audit["evidence_sha256"].items():
        path = healthy_root / "trials/r0000" / name
        require(path.is_file() and sha(path) == expected,
                f"healthy trace member changed: {name}")
    return {"status": "offline_full_preflight_passed", "case_id": "SOLR-09",
            "config_sha256": sha(HERE / "config.json"),
            "manifest_sha256": sha(HERE / "manifest.json"),
            "healthy_audit_sha256": sha(audit_path),
            "healthy_manifest_sha256": sha(HEALTHY / "manifest.json"),
            "healthy_config_sha256": healthy_pins["config_sha256"],
            "budget": config["budget"],
            "launch_gate": "independent_dispatch_go_and_fresh_healthy_role_audit"}


if __name__ == "__main__":
    print(json.dumps(main(), sort_keys=True))
