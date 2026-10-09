#!/usr/bin/env python3
"""Build an immutable, source-only HBASE-23 selector revision.

The canonical 102-case inventory and source reference are read only.
"""

import copy
import hashlib
import json
import os
from pathlib import Path


BASE = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PREFIX = "HBASE-23-alternate-healthy-v1"
SELECTOR = "org.apache.hadoop.hbase.procedure.TestProcedureManager#testSimpleProcedureManager"
TEST_REL = "hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestProcedureManager.java"
SOURCE_ROOT = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return sha(path)


def main():
    base_inv_path = BASE / "Mallory/cases/inventory.json"
    base_ref_path = BASE / "Mallory/dispatch/source_reference.json"
    config_path = BASE / "Mallory/adapters/hbase/pilot/HBASE-23-lane9-next-healthy-only.json"
    triage_path = BASE / "Mallory/adapters/hbase/pilot/HBASE-02-10-11-12-23-source-triage-v1.json"
    inv = copy.deepcopy(json.loads(base_inv_path.read_text()))
    ref = copy.deepcopy(json.loads(base_ref_path.read_text()))
    config = json.loads(config_path.read_text())
    assert inv["count"] == 102 and len(inv["cases"]) == 102
    row = next(r for r in inv["cases"] if r["case_id"] == "HBASE-23")
    original = copy.deepcopy(row["workload"])
    assert row["workload"]["selected_selector"] == (
        "org.apache.hadoop.hbase.procedure.TestZKProcedureControllers"
        "#testZKCoordinatorControllerWithSingleMemberCohort"
    )
    assert config["cluster_test"] == SELECTOR and config["calibration_only"] is True
    assert sha(SOURCE_ROOT / TEST_REL) == "35dee7363efa0ade2a906fb1b75bc1ab1396ae48c02ff75db0b18f676d6cd135"
    candidate = {
        "raw": SELECTOR,
        "simple_class": "TestProcedureManager",
        "method": "testSimpleProcedureManager",
        "parameter_variant": None,
        "class": "org.apache.hadoop.hbase.procedure.TestProcedureManager",
        "selector": SELECTOR,
        "source_path": TEST_REL,
        "source_sha256": sha(SOURCE_ROOT / TEST_REL),
        "method_line": 60,
        "has_junit_annotation": True,
        "test_like": True,
        "cluster_fixture_markers_in_test_source": ["HBaseTestingUtility", "startMiniCluster(NUM_RS)"],
        "resolution": "source_candidate_only_exact_target_unverified",
    }
    row["workload"]["selected_selector"] = SELECTOR
    row["workload"]["test_class"] = candidate["class"]
    row["workload"]["test_method"] = candidate["method"]
    row["workload"]["test_source_path"] = TEST_REL
    row["workload"]["selector_source"] = "source_review_alternate_healthy_only"
    row["workload"]["recorded_selector"] = original["selected_selector"]
    row["workload"]["recorded_selector_status"] = "exact_inner_guard_not_reached_in_original_source_order"
    row["workload"]["source_oracle_warning"] = (
        "The reached child must already exist during the coordinator's synchronous scan; "
        "this is a timing-dependent possibility, not a verified target hit."
    )
    row["workload"]["mapping_evidence"] = (
        "TestProcedureManager#testSimpleProcedureManager starts a two-RS MiniHBaseCluster "
        "and calls Admin.execProcedureWithReturn (lines 37-66). The RS subprocedure "
        "returns nonempty SIMPLE_DATA and completion is written to ZooKeeper. "
        "ZKProcedureCoordinator.sendGlobalBarrierReached may see that child during its "
        "synchronous loop (lines 119-131). Exact branch reach requires healthy calibration."
    )
    row["workload"]["alternate_test_candidates"] = [candidate]
    row["workload"]["candidates"] = original["candidates"] + [candidate]
    row["workload"]["healthy_pilot_attestation"] = None
    row["eligibility"]["cluster_and_target_reach_verified_for_mallory"] = False
    row["eligibility"]["state"] = "ready_for_healthy_seed"
    row["eligibility"]["may_dispatch_healthy_seed"] = True
    row["build"]["argv"] = config["command"]
    row["build"]["cwd"] = config["cwd"]
    row["build"]["runtime_root"] = str(Path(config["agent_jar"]).parent)
    row["build"]["runner_validation_scope"] = "HBASE-23 selector has source support only; no healthy target attestation"
    row["build"]["validated_by_execution"] = False
    inv_path = OUT / (PREFIX + ".inventory.json")
    inv_sha = write(inv_path, inv)
    ref["inventory_sha256"] = inv_sha
    ref_path = OUT / (PREFIX + ".source-reference.json")
    ref_sha = write(ref_path, ref)
    manifest = {
        "schema_version": 1,
        "kind": "review_only_combined_inventory_source_reference_snapshot",
        "status": "healthy_calibration_only_not_runtime_verified",
        "base_inventory": "Mallory/cases/inventory.json",
        "base_inventory_sha256": sha(base_inv_path),
        "base_source_reference": "Mallory/dispatch/source_reference.json",
        "base_source_reference_sha256": sha(base_ref_path),
        "inventory_snapshot": {"path": str(inv_path.relative_to(BASE)), "sha256": inv_sha, "row_count": 102},
        "source_reference_snapshot": {"path": str(ref_path.relative_to(BASE)), "sha256": ref_sha,
                                      "root_fingerprints_unchanged": True},
        "changed_case_ids": ["HBASE-23"],
        "original_selector": original["selected_selector"],
        "alternate_selector": SELECTOR,
        "target_source": row["target"]["source_path"],
        "target_source_sha256": row["target"]["source_sha256"],
        "test_source": TEST_REL,
        "test_source_sha256": candidate["source_sha256"],
        "source_commit": row["provenance"]["source_commit"],
        "calibration_only_config": str(config_path.relative_to(BASE)),
        "calibration_only_config_sha256": sha(config_path),
        "source_triage": str(triage_path.relative_to(BASE)),
        "source_triage_sha256": sha(triage_path),
        "limitation": "No HBASE-23 healthy JVM evidence or exact selected-guard reach is claimed.",
    }
    man_path = OUT / (PREFIX + ".manifest.json")
    man_sha = write(man_path, manifest)
    print(f"{man_path.relative_to(BASE)} {man_sha}")
    print(f"{inv_path.relative_to(BASE)} {inv_sha}")
    print(f"{ref_path.relative_to(BASE)} {ref_sha}")


if __name__ == "__main__":
    main()
