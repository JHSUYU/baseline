"""Pin source-reviewed HDFS healthy-only probes without launching a JVM.

The generated configs are proposals for dispatch admission. They intentionally
cannot auto-promote to a fault campaign from a passing JUnit alone.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
AGENT = ROOT / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
CORE = ROOT / ("Mallory/dispatch/releases/"
               "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f/"
               "manifest.json")
ADAPTER_V10 = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-adapter-next/"
                   "mallory-hdfs-adapter-v10-handshake-storage-task.jar")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def from_repo(path: str) -> dict:
    p = ROOT / path
    return {"path": str(p), "sha256": sha(p)}


def src(path: str, lines: str) -> dict:
    p = SOURCE / path
    return {"path": str(p), "sha256": sha(p), "lines": lines}


def first_result(case: str) -> dict:
    p = ROOT / f"data/mallory/calibration/{case}/trials/r0000/result.json"
    d = json.loads(p.read_text())
    f = d["feedback"]
    return {
        "path": str(p), "sha256": sha(p),
        "junit_process_return_code": d["return_code"],
        "target_reached": f["target_reached"],
        "target_threw": f["target_threw"],
        "target_instances": len(f["target_instances"]),
        "target_nodes": sorted({i["node"] for i in f["target_instances"]}),
    }


ROWS = {
    "HDFS-24": {
        "template": "Mallory/adapters/hdfs/cases/old-image-v1/HDFS-24-healthy.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java",
        "source_lines": "385-425",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSUpgradeFromImage.java",
        "test_lines": "296-300,598-625",
        "assessment": "Old-image four-DataNode upgrade is the best existing JUnit candidate. Original TestDFSUpgrade expected the selected exception and cannot serve as a nonthrowing seed. The old-image selector is staged elsewhere and has not run.",
        "remaining_gate": "Require passing JUnit, exact @414 guard on named DN, zero selected @424 throw, and a pretarget VERSION read path. Reserve about 1 GiB transient disk; run only on admitted idle lane.",
        "resource": "hadoop-hdfs-project/hadoop-hdfs/src/test/resources/hadoop-22-dfs-dir.tgz",
        "resource_sha256": "eaddf228d286f54fb431a12342550a9b473b189dc3a36cbf3eec668ce9000380",
        "resource_transient_bytes_estimate": 1073741824,
    },
    "HDFS-26": {
        "template": "Mallory/adapters/hdfs/cases/next-v13/HDFS-26-v10-calibration.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java",
        "source_lines": "605-635",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollback.java",
        "test_lines": "139-225",
        "assessment": "Original rollback JUnit already reached the exact nonthrowing block-pool guard three times. The remaining gap is DN ownership and a causal path from the local VERSION read; the test need not change.",
        "remaining_gate": "Require passing JUnit, exact @619/@620 on named DN, zero @626 throw, and root-free local file-I/O ancestry.",
    },
    "HDFS-29": {
        "template": "Mallory/adapters/hdfs/cases/next-v16/HDFS-29-lease-recovery-healthy-v16.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.java",
        "source_lines": "574-584",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java",
        "test_lines": "276-327",
        "assessment": "Lease-recovery-after-failover is a shorter three-DN HA alternate to the exact-target original test, whose instrumented JUnit timed out. It invokes recovery and syncBlock; target entry remains to be proven on this alternate.",
        "remaining_gate": "Require passing JUnit, exact @577 on named DN, no @578 throw, and a task/RPC ancestry to the selected recovery occurrence.",
    },
    "HDFS-30": {
        "template": "Mallory/adapters/hdfs/cases/next-v13/HDFS-30-v11-calibration.json",
        "selector_template": "Mallory/adapters/hdfs/cases/next-v16/HDFS-29-lease-recovery-healthy-v16.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.java",
        "source_lines": "574-586",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java",
        "test_lines": "276-327",
        "assessment": "Use the same shorter HA lease-recovery alternate as HDFS-29. The original test reached exact @582 twice without throwing but lacked DN identity; alternate target reach remains unverified.",
        "remaining_gate": "Require passing JUnit, exact @582 on named DN, no @583 throw, and task/RPC ancestry to the same recovery occurrence.",
    },
    "HDFS-33": {
        "template": "Mallory/adapters/hdfs/cases/next-v13/HDFS-33-v10-calibration.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java",
        "source_lines": "226-263,324-343",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDataNodeHotSwapVolumes.java",
        "test_lines": "315-350,403-420",
        "assessment": "Original one-DN hot-volume JUnit already reached the exact nonthrowing assertion. Binding VolumeBuilder.storage to its registered DataNode and preserving prepareVolume-to-build context is the remaining gap.",
        "remaining_gate": "Require passing JUnit with assertions enabled, exact @259 on named DN, zero selected AssertionError, and pretarget volume file-I/O ancestry.",
    },
    "HDFS-34": {
        "template": "Mallory/adapters/hdfs/cases/old-image-v1/HDFS-34-healthy.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java",
        "source_lines": "730-751",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSUpgradeFromImage.java",
        "test_lines": "296-300,598-625",
        "assessment": "Checked-in pre-federation image should exercise the namespace guard in a matching four-DN upgrade. Original TestDFSStartupVersions intentionally raises the selected exception in some matrix rows.",
        "remaining_gate": "Require passing JUnit, exact @739 on named DN, zero @744 selected throw, and pretarget VERSION read path. Reserve about 1 GiB transient disk; run only on admitted idle lane.",
        "resource": "hadoop-hdfs-project/hadoop-hdfs/src/test/resources/hadoop-22-dfs-dir.tgz",
        "resource_sha256": "eaddf228d286f54fb431a12342550a9b473b189dc3a36cbf3eec668ce9000380",
        "resource_transient_bytes_estimate": 1073741824,
    },
    "HDFS-37": {
        "template": "Mallory/adapters/hdfs/cases/alternate-v10/HDFS-37-healthy.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java",
        "source_lines": "920-955",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/TestFileTruncate.java",
        "test_lines": "987-1053,1343-1355",
        "assessment": "Truncate JUnit upgrades a cluster then restarts the DataNodes with ROLLBACK against a valid previous state. Original TestDFSRollback includes deliberately invalid previous states and raises the selected exception.",
        "remaining_gate": "Require passing JUnit, both @940/@941 guard sites on named DN, zero @947 throw, and pretarget local VERSION read path.",
        "adapter_override": str(ADAPTER_V10),
    },
    "HDFS-48": {
        "template": "Mallory/adapters/hdfs/cases/next-v14/HDFS-48-nn-calibration.json",
        "source": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/INodeDirectory.java",
        "source_lines": "349-361",
        "test": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java",
        "test_lines": "1339-1363",
        "assessment": "NN-only v14 calibration already passed JUnit, named exact target, no selected throw, and offline causal audit. Do not rerun its healthy seed merely to inflate counts. Its 10/10 effective RpcCall faults all prevented postfault target; a future fault strategy must preserve rename execution.",
        "remaining_gate": "Hold any full campaign. A new source-backed fault door must reach NN replaceChild after injection; repeat healthy only if changing instrumentation or selector.",
        "existing_healthy_result": "data/mallory/calibration_v14_node0/HDFS-48/result.json",
        "existing_pilot_decision": "Mallory/cases/revisions/HDFS-48-nn-v14.pilot-decision-v2.json",
    },
}


def prepare() -> None:
    assert sha(AGENT) == AGENT.parent.name
    assert sha(CORE) == "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
    cases = []
    for case_id, row in ROWS.items():
        template = ROOT / row["template"]
        d = json.loads(template.read_text())
        template_runtime_artifacts = copy.deepcopy(d.get("runtime_artifacts", []))
        if "selector_template" in row:
            selector = json.loads((ROOT / row["selector_template"]).read_text())
            for key in ("cluster_test", "command", "cwd", "source_equivalent_root",
                        "source_equivalence"):
                d[key] = copy.deepcopy(selector[key])
            d["mapping"]["test_source_sha256"] = selector["mapping"]["test_source_sha256"]
            d["mapping"]["alternate_test_selector"] = d["cluster_test"]
            d["mapping"]["alternate_test_source"] = str(SOURCE / row["test"])
        d["agent_jar"] = str(AGENT)
        d["core_release"] = str(CORE.parent)
        d["reject_coarse_roots"] = True
        d["require_event_time_paths"] = True
        d["calibration_only"] = True
        d["auto_promote_if_healthy"] = False
        d["budget"] = {
            "trials": 1, "seconds": 900 if case_id in {"HDFS-24", "HDFS-34", "HDFS-37"} else 300,
            "max_faults_per_trial": 1,
            "trial_timeout_seconds": 720 if case_id in {"HDFS-24", "HDFS-34", "HDFS-37"} else 240,
            "trial_timeout_basis": "source_only_preflight_one_healthy_run_no_faults",
        }
        d["healthy_gate"] = {
            "required_junit_tests": 1, "required_junit_errors": 0,
            "required_junit_failures": 0, "require_exact_target_reached": True,
            "require_named_target_node": True, "require_target_exception_absent": True,
            "require_nonempty_observed_graph_path": True,
            "require_offline_audit_report_gate": True,
            "minimum_healthy_observed_path_doors": 1,
            "allow_local_timeline_doors": False,
        }
        if "adapter_override" in row:
            d["agent_properties"]["adapter.jar"] = row["adapter_override"]
        d.setdefault("mapping", {})["status"] = "source_only_pending_dispatch_healthy_admission"
        d["mapping"]["healthy_seed_verified"] = False
        d["mapping"]["agent_sha256"] = sha(AGENT)
        d["mapping"]["agent_build"] = {
            "artifact": str(AGENT), "sha256": sha(AGENT),
            "release_manifest": str(AGENT.parent / "manifest.json"),
        }
        d["mapping"]["agent_release_manifest"] = str(AGENT.parent / "manifest.json")
        d["mapping"]["agent_release_manifest_sha256"] = sha(AGENT.parent / "manifest.json")
        d["mapping"]["core_release_id"] = CORE.parent.name
        d["mapping"]["core_release_manifest_sha256"] = sha(CORE)
        d["mapping"]["calibration_revision"] = "pending_triage_v1_healthy_only"
        d["mapping"]["source_root"] = d["cwd"]
        d["mapping"]["compiled_artifact"] = str(Path(d["cwd"]) /
                                                    "hadoop-hdfs-project/hadoop-hdfs/target/classes")
        d["mapping"]["node_identity_binding_verified"] = False
        d["mapping"].pop("verified_healthy_probe", None)
        d["runtime_artifacts"] = [
            {"path": str(AGENT), "sha256": sha(AGENT)},
            {"path": d["site_file"], "sha256": sha(Path(d["site_file"]))},
            {"path": d["agent_properties"]["adapter.jar"],
             "sha256": sha(Path(d["agent_properties"]["adapter.jar"]))},
        ]
        # Preserve the template's compiled test class and classpath fixtures
        # where present. An old-image source tgz alone does not prove that the
        # byte-identical fixture is available to the selected Surefire test.
        pinned_paths = {a["path"] for a in d["runtime_artifacts"]}
        for old in template_runtime_artifacts:
            artifact = Path(old["path"])
            if (str(artifact) in pinned_paths or artifact.name.startswith("mallory-agent")
                    or artifact.name.startswith("mallory-hdfs-adapter")
                    or not artifact.is_file()):
                continue
            d["runtime_artifacts"].append(
                {"path": str(artifact), "sha256": sha(artifact)})
            pinned_paths.add(str(artifact))
        if case_id in {"HDFS-24", "HDFS-34"}:
            d["runtime_artifacts"].append(
                {"path": str(SOURCE / row["resource"]),
                 "sha256": sha(SOURCE / row["resource"])})
        dest = OUT / f"{case_id}-healthy-only.json"
        dest.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")
        target_class_name = d["target"]["function"].split("(")[0].rsplit(".", 1)[0]
        target_class_file = (Path(d["mapping"]["compiled_artifact"]) /
                             (target_class_name.replace(".", "/") + ".class"))
        assert sha(target_class_file) == d["expected_target_class_sha256"]
        test_class_name = d["cluster_test"].split("#", 1)[0]
        test_class_file = (Path(d["cwd"]) /
                           "hadoop-hdfs-project/hadoop-hdfs/target/test-classes" /
                           (test_class_name.replace(".", "/") + ".class"))
        assert test_class_file.is_file()
        manifest_row = {
            "case_id": case_id,
            "status": "source_only_existing_healthy_no_rerun" if case_id == "HDFS-48"
                      else "source_only_healthy_pending_dispatch_admission",
            "config": from_repo(str(dest.relative_to(ROOT))),
            "template": from_repo(row["template"]),
            "selector": d["cluster_test"],
            "target_source": src(row["source"], row["source_lines"]),
            "junit_source": src(row["test"], row["test_lines"]),
            "compiled_target_class": {"path": str(target_class_file),
                                      "sha256": sha(target_class_file)},
            "compiled_junit_class": {"path": str(test_class_file),
                                     "sha256": sha(test_class_file)},
            "prior_original_healthy": first_result(case_id),
            "assessment": row["assessment"],
            "remaining_gate": row["remaining_gate"],
        }
        if "resource" in row:
            manifest_row["fixture"] = src(row["resource"], "binary archive")
            manifest_row["fixture_transient_bytes_estimate"] = row["resource_transient_bytes_estimate"]
            assert manifest_row["fixture"]["sha256"] == row["resource_sha256"]
        if "existing_healthy_result" in row:
            manifest_row["existing_healthy_result"] = from_repo(row["existing_healthy_result"])
            manifest_row["existing_pilot_decision"] = from_repo(row["existing_pilot_decision"])
        cases.append(manifest_row)
    receipt = {
        "schema_version": 1,
        "scope": "source_only_hdfs_pending_healthy_preflight",
        "no_jvm_or_fault_trial_launched": True,
        "requires_dispatch_admission": True,
        "agent_release": {"path": str(AGENT), "sha256": sha(AGENT)},
        "core_release": {"path": str(CORE), "sha256": sha(CORE)},
        "cases": cases,
    }
    (OUT / "preflight.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    prepare()
