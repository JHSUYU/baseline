#!/usr/bin/env python3
"""Run exactly one pinned SOLR-09 fault plan through the original JUnit runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from Mallory.core.campaign import _run_trial, atomic_json, validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


HERE = Path(__file__).resolve().parent
CONFIG = HERE / "pilot-node2-lane3.json"
PLAN = HERE / "pilot-plan-node2-lane3.json"
CHECK = "org.apache.solr.cloud.api.collections.DeleteReplicaCmd#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;Ljava/lang/String;Lorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V@277:branch:7"
DOOR = "org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    config = json.loads(CONFIG.read_text())
    plan_file = json.loads(PLAN.read_text())
    out = Path(config["admission"]["output"])
    assert not out.exists(), f"refusing to reuse pilot output: {out}"
    assert config["case_id"] == "SOLR-09"
    assert config["budget"]["trials"] == 1
    assert config["budget"]["max_faults_per_trial"] == 1
    assert config["calibration_only"] is False
    assert config["auto_promote_if_healthy"] is False
    assert config["require_event_time_paths"] is True
    assert config["reject_coarse_roots"] is True
    assert config["target"]["check_sites"] == [CHECK]
    assert config["site_file"] == str(HERE / "sites.json")
    assert plan_file["schema_version"] == 1 and len(plan_file["faults"]) == 1
    fault = plan_file["faults"][0]
    assert fault["fault_type"] == "EXCEPTION"
    assert fault["exception_class"] == "java.util.concurrent.TimeoutException"
    assert fault["point"] == {"site": DOOR, "node": "node4", "epoch": 0,
                              "door_ordinal": 1}
    validate_config(config)
    verify_runtime_artifacts(config)
    healthy = json.loads((HERE / "healthy-audit-node2-lane3.json").read_text())
    assert healthy["status"] == "healthy_exact_target_with_typed_local_timeline_graph_gap"
    assert healthy["target"]["node"] == "node4" and healthy["target"]["epoch"] == 0
    assert healthy["target"]["outcome"] == "TAKEN"
    assert healthy["typed_door"]["site"] == DOOR
    assert healthy["typed_door"]["ordinal"] == 1
    assert healthy["door_to_target"]["nonempty_event_time_graph_path"] is False
    assert sha(HERE / "evidence/node2-lane3-r0000/result.json") == \
        healthy["evidence_sha256"]["result.json"]

    out.mkdir(parents=True)
    result = _run_trial(config, out, 1, [fault], lambda pid: None,
                        {"nodes": ["node4"]})
    terminal = {"case_id": "SOLR-09", "scope": "one_diagnostic_single_fault_junit",
                "trial_result": str(out / "trials/r0001/result.json"),
                "trial_result_sha256": sha(out / "trials/r0001/result.json"),
                "plan_sha256": sha(PLAN), "config_sha256": sha(CONFIG),
                "junit_status": result["junit_validation"]["status"],
                "feedback_status": result["feedback"]["status"],
                "fault_identity_valid": result["feedback"].get("fault_identity_valid"),
                "target_reached": result["feedback"].get("target_reached"),
                "target_threw": result["feedback"].get("target_threw"),
                "graph_limit": "postfault raw event audit required; no full promotion"}
    atomic_json(out / "pilot-terminal.json", terminal)
    print(json.dumps(terminal, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
