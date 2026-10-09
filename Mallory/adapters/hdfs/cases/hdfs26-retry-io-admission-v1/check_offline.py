#!/usr/bin/env python3
"""Check the HDFS-26 source admission, optionally a later healthy campaign.

This verifier reads files only. It does not start Hadoop or run a fault trial.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
sys.path.insert(0, str(REPO))

from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_line(path, number):
    return path.read_text(encoding="utf-8").splitlines()[number - 1]


def check_source():
    receipt = read_json(HERE / "source-receipt.json")
    config_path = HERE / "HDFS-26-healthy-only.json"
    site_path = HERE / "HDFS-26.sites.json"
    config = read_json(config_path)
    sites = read_json(site_path)
    assert receipt["source_commit"] == subprocess.run(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    for item in receipt["inputs"]:
        path = Path(item["path"])
        assert path.is_file() and digest(path) == item["sha256"], path
    validate_config(config)
    verify_runtime_artifacts(config)
    assert config["case_id"] == "HDFS-26"
    assert config["cluster_test"] == "org.apache.hadoop.hdfs.TestDFSRollback#testRollback"
    assert config["calibration_only"] and config["auto_promote_if_healthy"] is False
    assert config["budget"]["trials"] == 1
    assert config["mapping"]["healthy_seed_verified"] is False
    assert config["mapping"]["node_identity_binding_verified"] is False
    assert config["mapping"]["compiled_class_sha256"] == (
        "3585869cf95c5a58dd50ffb3766bceb797c09b532d46bdc08e811ae659c520a9")
    assert config["healthy_gate"]["require_named_target_node"]
    assert config["healthy_gate"]["require_target_exception_absent"]
    assert config["reject_coarse_roots"] and config["require_event_time_paths"]
    assert "org.apache.hadoop.hdfs.server.common.StorageInfo" in config["agent_include"]
    assert len(sites["doors"]) == 2
    assert sites["doors"][0] == {
        "callee": "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB#versionRequest()Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;",
        "clazz": "org.apache.hadoop.hdfs.server.datanode.BPServiceActor",
        "descriptor": "()Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;",
        "exception_class": "java.io.IOException",
        "line": 260,
        "method": "retrieveNamespaceInfo",
    }
    assert sites["doors"][1] == {
        "callee": "java.util.Properties#load(Ljava/io/InputStream;)V",
        "clazz": "org.apache.hadoop.hdfs.server.common.StorageInfo",
        "descriptor": "(Ljava/io/File;)Ljava/util/Properties;",
        "exception_class": "java.io.IOException",
        "line": 272,
        "method": "readPropertiesFile",
    }
    assert config["target"]["check_sites"] == [
        "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@619:branch:3",
        "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@620:branch:4",
    ]
    assert config["target"]["throw_site"].endswith("@626:throw:1")
    main = SOURCE / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs"
    actor = main / "server/datanode/BPServiceActor.java"
    storage = main / "server/common/StorageInfo.java"
    slice_storage = main / "server/datanode/BlockPoolSliceStorage.java"
    test = SOURCE / "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollback.java"
    assert "bpNamenode.versionRequest()" in source_line(actor, 260)
    actor_source = actor.read_text(encoding="utf-8")
    assert "catch(IOException e )" in actor_source
    assert 'sleepAndLogInterrupts(5000, "requesting version info from NN")' in actor_source
    assert "NamespaceInfo nsInfo = retrieveNamespaceInfo();" in actor_source
    assert "doRollback(sd, nsInfo);" in slice_storage.read_text(encoding="utf-8")
    assert "prevInfo.readPreviousVersionProperties(bpSd);" in slice_storage.read_text(encoding="utf-8")
    assert "props.load(in);" in source_line(storage, 272)
    assert "sd.getPreviousVersionFile()" in storage.read_text(encoding="utf-8")
    test_source = test.read_text(encoding="utf-8")
    assert "void testRollback() throws Exception" in test_source
    assert 'log("Normal BlockPool rollback", numDirs)' in test_source
    assert 'cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);' in test_source
    assert config["site_file"] == str(site_path)
    return config


def check_campaign(config, campaign):
    """Require the explicit retry RPC door in the observed target closure."""
    errors = []
    required = ("config.json", "result.json", "trials/r0000/result.json",
                "offline-causal-audit.json")
    for name in required:
        if not (campaign / name).is_file():
            errors.append("missing " + name)
    if errors:
        return errors
    if digest(campaign / "config.json") != digest(HERE / "HDFS-26-healthy-only.json"):
        errors.append("campaign config differs from source-admitted selector")
    summary = read_json(campaign / "result.json")
    trial = read_json(campaign / "trials/r0000/result.json")
    audit = read_json(campaign / "offline-causal-audit.json")
    feedback = trial.get("feedback") or {}
    junit = summary.get("healthy_junit_validation") or {}
    if summary.get("case_id") != "HDFS-26" or summary.get("cluster_test") != config["cluster_test"]:
        errors.append("wrong case or JUnit selector")
    if summary.get("target") != config["target"]:
        errors.append("wrong selected check")
    if summary.get("healthy_seed_valid") is not True:
        errors.append("runner did not validate healthy seed")
    if (junit.get("status") != "passed" or junit.get("runner") != "surefire_xml"
            or any(junit.get(key) != value for key, value in
                   (("tests", 1), ("failures", 0), ("errors", 0), ("skipped", 0)))):
        errors.append("JUnit 1/0/0/0 Surefire receipt absent")
    if trial.get("return_code") != 0 or trial.get("timed_out") is not False:
        errors.append("healthy run failed or timed out")
    if (feedback.get("target_reached") is not True or feedback.get("target_threw") is not False
            or feedback.get("target_identity_complete") is not True
            or feedback.get("target_identity_gaps") or feedback.get("trace_truncated")):
        errors.append("exact nonthrowing named target or complete trace absent")
    instances = feedback.get("target_instances") or []
    if not instances or any(not str(i.get("node", "")).startswith("hdfs-cluster-")
                            or "/dn" not in str(i.get("node", "")) for i in instances):
        errors.append("target occurrence outside named DataNode")
    catalog = trial.get("site_catalog_validation") or {}
    if (catalog.get("valid") is not True or catalog.get("class_hash_match") is not True
            or catalog.get("missing_check_sites") or catalog.get("duplicate_target_sites")):
        errors.append("compiled selected site missing or ambiguous")
    attestation = summary.get("runtime_attestation") or {}
    expected_class = config["expected_target_class_sha256"]
    if (attestation.get("valid") is not True
            or attestation.get("observed_target_class_sha256") != expected_class):
        errors.append("runtime target class SHA mismatch")
    if (audit.get("campaign_result_sha256") != digest(campaign / "result.json")
            or audit.get("report_gate_passed") is not True
            or audit.get("healthy_closure_proven") is not True
            or audit.get("healthy_observed_path_doors", 0) < 1):
        errors.append("offline root-free target path gate failed")
    core_release = read_json(Path(config["core_release"]) / "manifest.json")
    core_files = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")
    expected_core = {name: core_release["files"]["Mallory/core/" + name]
                     for name in core_files}
    if audit.get("core_source_sha256") != expected_core or audit.get("allow_local_timeline_doors", False):
        errors.append("offline audit did not use frozen core or allowed local timeline doors")
    retry_doors = [door for door in feedback.get("doors", [])
                   if "BPServiceActor#retrieveNamespaceInfo" in str(door.get("site", ""))
                   and "@260:door:" in str(door.get("site", ""))
                   and door.get("exception_class") == "java.io.IOException"
                   and door.get("in_closure") is True]
    if not retry_doors:
        errors.append("typed versionRequest retry door absent from observed target closure")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path,
                        help="also check a later dispatch-produced healthy campaign")
    args = parser.parse_args()
    config = check_source()
    errors = check_campaign(config, args.campaign) if args.campaign else []
    print(json.dumps({"source_admitted": True, "campaign_admitted":
                      not errors if args.campaign else None,
                      "campaign": str(args.campaign) if args.campaign else None,
                      "errors": errors}, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
