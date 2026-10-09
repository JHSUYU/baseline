#!/usr/bin/env python3
"""Promote a single runtime-bound SOLR-22 actor after observed request proof."""

import hashlib
import json
import sys
from pathlib import Path

BASE = Path("/users/ZhenyuLi/baseline")
sys.path.insert(0, str(BASE / "Mallory/dispatch"))
sys.path.insert(0, str(BASE / "Mallory/adapters/solr/releases/v23"))
from promote_v23 import promote

CASE = BASE / "Mallory/adapters/solr/cases/SOLR-22"
CAL = BASE / "data/mallory/calibration_v33g1_lane4/SOLR-22"
PROOF = BASE / "data/mallory/audit_sidecars/SOLR-22-v33g1-dynamic-healthy.json"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG = CASE / "config-v33g1-lane4-fa5f-dynamic-actor-healthy.json"
OUT = CASE / "config-v33g1p-lane4-fa5f-dynamic-actor-promoted-base.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert digest(CONFIG) == "009cb27984d1d6c36e419fb4e134aafb3d9a4352b0ebc57202291100e082c737"
    assert digest(PROOF) == "37b41e0e380ef4ec49dc238301fa28264af5420a704d5edb653321edc18067bf"
    proof = json.loads(PROOF.read_text())
    assert proof["classification"] == "healthy_dynamic_single_actor_request_path_proven"
    assert proof["result_sha256"] == digest(CAL / "result.json")
    assert proof["offline_audit_sha256"] == digest(CAL / "offline-causal-audit.json")
    actor = proof["resolved_physical_target_node"]
    assert actor in {"node1", "node2"}
    inventory = json.loads((BASE / "Mallory/adapters/solr/releases/v20/inventory.json").read_text())
    row = next(item for item in inventory["cases"] if item.get("case_id") == "SOLR-22")
    reference = json.loads((BASE / "Mallory/adapters/solr/releases/v20/source_reference.json").read_text())
    promoted = promote(CONFIG, CAL, OUT, row, reference, RELEASE / "manifest.json")
    promoted_config = json.loads(promoted.read_text())
    assert "nodes" not in promoted_config["target"]
    assert promoted_config["calibration_attestation"]["target_nodes"] == [actor]
    print(json.dumps({"promoted": str(promoted), "sha256": digest(promoted),
                      "calibrated_physical_node": actor,
                      "runtime_binding_in_fault_run": True}, sort_keys=True))


if __name__ == "__main__":
    main()
