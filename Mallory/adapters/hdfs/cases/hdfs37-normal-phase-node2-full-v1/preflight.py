#!/usr/bin/env python3
"""Read-only HDFS-37 full-campaign admission; never starts a JVM."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
ORIGINAL = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs37-normal-node2-v3")
V3 = HERE.parent / "hdfs37-normal-phase-node2-v3"
OUT = Path("/tmp/mallory-hdfs37-normal-node2-full-v1")
CONFIG = HERE / "HDFS-37-node2-full-v1.json"
DOOR_DN = "org.apache.hadoop.hdfs.server.datanode.BPServiceActor#retrieveNamespaceInfo()Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;@260:door:1"
DOOR_NN = "org.apache.hadoop.ipc.Server$RpcCall#run()Ljava/lang/Void;@1246:door:1"
DOOR_CHILD = "org.apache.hadoop.hdfs.server.common.StorageInfo#readPropertiesFile(Ljava/io/File;)Ljava/util/Properties;@272:door:1"
CHECK_940 = "org.apache.hadoop.hdfs.server.datanode.DataStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@940:branch:3"
CHECK_941 = "org.apache.hadoop.hdfs.server.datanode.DataStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@941:branch:4"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned file: {path}")


def line_contains(path: Path, line: int, fragment: str) -> None:
    lines = path.read_text().splitlines()
    if len(lines) < line or fragment not in lines[line - 1]:
        raise RuntimeError(f"source line moved: {path}:{line}")


def events_by_seq(path: Path) -> dict[int, dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    seqs = [row["seq"] for row in rows]
    if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
        raise RuntimeError("healthy event sequence is not unique and ordered")
    return {row["seq"]: row for row in rows}


def verify_healthy(review: dict, config: dict) -> dict:
    evidence = review["healthy_evidence"]
    summary = json.loads((HERE / "prior-healthy-summary.json").read_text())
    result = json.loads((HERE / "prior-healthy-trial-result.json").read_text())
    source_config = json.loads((HERE / "prior-healthy-config.json").read_text())
    events = events_by_seq(HERE / "prior-healthy-events.jsonl.gz")
    if (summary["case_id"] != "HDFS-37" or
            summary["status"] != "calibration_complete" or
            summary["healthy_seed_valid"] is not True or
            summary["calibration_only"] is not True or
            summary["fault_trials_completed"] != 0 or
            summary["target_binding"] != {"nodes": [evidence["target_node"]]} or
            summary["healthy_eligible_doors"] != evidence["eligible_doors_before_target"] or
            summary["runtime_attestation"]["valid"] is not True or
            summary["runtime_attestation"]["observed_target_class_sha256"] !=
            config["expected_target_class_sha256"] or
            summary["runtime_attestation"]["target_identity_gap_count"] != 0 or
            result["case_id"] != "HDFS-37" or result["trial_id"] != 0 or
            result["junit_validation"]["status"] != "passed" or
            any(result["junit_validation"][key] != value for key, value in evidence["junit"].items()) or
            result["feedback"]["target_reached"] is not True or
            result["feedback"]["target_identity_complete"] is not True or
            result["feedback"]["target_threw"] is not False or
            result["feedback"]["target_throw_evidence"] or
            result["feedback"]["target_exception_candidate"] is not False or
            result["events_evidence"]["gzip_sha256"] != evidence["events_sha256"] or
            source_config["mapping"]["compiled_test_class_sha256"] !=
            config["mapping"]["compiled_test_class_sha256"]):
        raise RuntimeError("prior healthy run did not meet exact gate")

    for step in review["observed_path"]:
        event = events.get(step["seq"])
        if (event is None or event["type"] != step["type"] or
                event["node"] != step["node"] or
                ("site_suffix" in step and not event["site"].endswith(step["site_suffix"])) or
                ("port" in step and event.get("port") != step["port"])):
            raise RuntimeError(f"healthy path event differs at seq {step['seq']}")
    for seq in (349, 353):
        if (events[seq]["fault_type"] != "EXCEPTION" or
                events[seq]["exception_class"] != "java.io.IOException"):
            raise RuntimeError("closure door is not typed IOException")
    if (events[349]["occurrence"] != events[350]["occurrence"] or
            events[352]["occurrence"] != events[353]["occurrence"] or
            events[353]["occurrence"] != events[356]["occurrence"] or
            events[358]["node"] != events[360]["node"] or
            events[360]["occurrence"] != events[364]["occurrence"] or
            events[364]["occurrence"] != events[365]["occurrence"] or
            events[350]["correlation"] != events[352]["correlation"] or
            events[356]["correlation"] != events[358]["correlation"] or
            events[350]["correlation"] != events[356]["correlation"] or
            [events[seq]["site"] for seq in evidence["target_check_sequences"]] !=
            [CHECK_940, CHECK_941] or
            events[362]["site"] != DOOR_CHILD):
        raise RuntimeError("healthy path lacks exact occurrence/RPC/target identity")

    edges = result["feedback"]["closure_edges"]
    edge_keys = {(row["kind"], row["producer_event"], row["consumer_event"])
                 for row in edges if row.get("certainty") == "observed"}
    expected = {(row["kind"], f"HDFS-37-r0000:{row['producer_seq']}",
                 f"HDFS-37-r0000:{row['consumer_seq']}")
                for row in review["observed_closure_edges"]}
    if edge_keys != expected:
        raise RuntimeError("observed target closure differs")
    closure_doors = [door for door in result["feedback"]["doors"] if door.get("in_closure")]
    if ([(door["site"], door["point"]["node"], door["event_seq"])
         for door in closure_doors] !=
            [(DOOR_DN, "hdfs-cluster-2/dn0", 349),
             (DOOR_NN, "hdfs-cluster-2/nn0", 353)] or
            any(door["site"] == DOOR_CHILD and door.get("in_closure")
                for door in result["feedback"]["doors"])):
        raise RuntimeError("eligible closure door set differs")
    return result["feedback"]


def preflight(runtime: bool) -> dict:
    if runtime and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-37 runtime is scoped to node2")
    manifest = json.loads((HERE / "package-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        require(HERE / name, expected)
    review = json.loads((HERE / "source-trace-review.json").read_text())
    for name, key in (("prior-healthy-config.json", "config_sha256"),
                      ("prior-healthy-events.jsonl.gz", "events_sha256"),
                      ("prior-healthy-summary.json", "summary_sha256"),
                      ("prior-healthy-trial-result.json", "trial_result_sha256")):
        if key in review["healthy_evidence"]:
            require(HERE / name, review["healthy_evidence"][key])
    config = json.loads(CONFIG.read_text())
    source_config = json.loads((HERE / "prior-healthy-config.json").read_text())
    expected_config = json.loads(json.dumps(source_config))
    expected_config["budget"] = {
        "trials": 80, "seconds": 3600, "max_faults_per_trial": 3,
        "trial_timeout_seconds": 360,
        "trial_timeout_basis": "16.378s pinned healthy; 5s BPServiceActor retry; cap per fault trial",
    }
    expected_config.update({
        "calibration_only": False, "auto_promote_if_healthy": True,
        "explore_outside_closure": False, "fault_types": ["EXCEPTION"],
        "multi_fault_exploration_interval": 4,
        "validated_recovery_sites": [],
    })
    expected_config["mapping"].update({
        "full_admission": True, "healthy_seed_verified": True,
        "node_identity_binding_verified": True,
        "status": "node2_full_staged_prior_healthy",
        "prior_healthy_result": "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-node2-full-v1/prior-healthy-trial-result.json",
        "prior_healthy_result_sha256": review["healthy_evidence"]["trial_result_sha256"],
        "prior_healthy_events": "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-node2-full-v1/prior-healthy-events.jsonl.gz",
        "prior_healthy_events_sha256": review["healthy_evidence"]["events_sha256"],
        "sealed_prior_healthy_archive": "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-node2-full-v1/sealed-healthy.tar.gz",
        "sealed_prior_healthy_archive_sha256": review["healthy_evidence"]["archive_sha256"],
        "sealed_prior_healthy_receipt": "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-node2-full-v1/sealed-healthy.receipt.json",
        "sealed_prior_healthy_receipt_sha256": review["healthy_evidence"]["archive_receipt_sha256"],
    })
    if (config != expected_config or
            config["target"]["nodes"] != ["hdfs-cluster-2/dn0"] or
            config["target"]["check_sites"] != [CHECK_940, CHECK_941] or
            config["target"]["source_line"] != 947 or
            config["target"]["exception_class"] !=
            "org.apache.hadoop.hdfs.server.common.InconsistentFSStateException" or
            config.get("static_frontier_file") or config.get("static_fault_sites") or
            config.get("static_fault_locations")):
        raise RuntimeError("full config differs from admitted healthy seed and bounded policy")

    sealed = HERE / "sealed-healthy.tar.gz"
    require(sealed, review["healthy_evidence"]["archive_sha256"])
    receipt_path = HERE / "sealed-healthy.receipt.json"
    require(receipt_path, review["healthy_evidence"]["archive_receipt_sha256"])
    receipt = json.loads(receipt_path.read_text())
    if (receipt["case_id"] != "HDFS-37" or
            receipt["kind"] != "healthy_observation_only" or
            receipt["status"] != "calibration_complete" or
            receipt["healthy_seed_valid"] is not True or
            receipt["full_campaign_completed"] is not False or
            receipt["fault_trials_completed"] != 0 or
            receipt["archive_sha256"] != review["healthy_evidence"]["archive_sha256"] or
            receipt["result_sha256"] != review["healthy_evidence"]["summary_sha256"]):
        raise RuntimeError("sealed healthy receipt differs")
    with tarfile.open(sealed, "r:gz") as archive:
        for member, expected in (
                ("config.json", sha(HERE / "prior-healthy-config.json")),
                ("result.json", review["healthy_evidence"]["summary_sha256"]),
                ("trials/r0000/result.json", review["healthy_evidence"]["trial_result_sha256"]),
                ("trials/r0000/events.jsonl.gz", review["healthy_evidence"]["events_sha256"]),
                ("provenance/TestDFSRollback.class", config["mapping"]["compiled_test_class_sha256"])):
            stream = archive.extractfile(member)
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != expected:
                raise RuntimeError(f"sealed healthy member differs: {member}")

    root = SOURCE if runtime else ORIGINAL
    for relative, expected in review["source_files"].items():
        require(root / relative, expected)
    hdfs = root / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server"
    line_contains(hdfs / "datanode/BPServiceActor.java", 260, "bpNamenode.versionRequest()")
    line_contains(hdfs / "datanode/BPServiceActor.java", 265, "catch(IOException e")
    line_contains(hdfs / "datanode/DataStorage.java", 939, "if (!(prevInfo.getLayoutVersion() >=")
    line_contains(hdfs / "datanode/DataStorage.java", 941, "&& prevInfo.getCTime() <= nsInfo.getCTime()")
    line_contains(hdfs / "datanode/DataStorage.java", 942, "throw new InconsistentFSStateException")
    line_contains(hdfs / "datanode/DataStorage.java", 947, "nsInfo.getCTime())")
    line_contains(hdfs / "common/StorageInfo.java", 272, "props.load(in)")
    line_contains(root / "hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/Server.java",
                  1246, "value = call(")

    sys.path.insert(0, str(config["core_release"]))
    from Mallory.core.campaign import validate_config  # noqa: E402
    from Mallory.core.scheduler import mutate  # noqa: E402

    candidate = json.loads(json.dumps(config))
    if not runtime:
        candidate["cwd"] = str(ORIGINAL)
    validate_config(candidate)
    feedback = verify_healthy(review, config)
    initial = mutate([], feedback, config)
    if (len(initial) != 2 or
            {(item["selection_reason"], item["faults"][0]["point"]["site"],
              item["faults"][0]["point"]["node"],
              item["faults"][0]["exception_class"])
             for item in initial} != {
                ("dynamic_closure", DOOR_DN, "hdfs-cluster-2/dn0", "java.io.IOException"),
                ("dynamic_closure", DOOR_NN, "hdfs-cluster-2/nn0", "java.io.IOException"),
            }):
        raise RuntimeError("initial fault scheduler leaks or loses closure doors")

    if runtime:
        result = subprocess.run([sys.executable, "-B", str(V3 / "preflight.py"), "--runtime"],
                                check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"v3 compiled runtime preflight failed: {result.stderr.strip()}")
        receipt = json.loads((SOURCE / "mallory-hdfs37-compiled-receipt.json").read_text())
        require(SOURCE / "mallory-hdfs37-healthy-node2-v3.json", receipt["runtime_config_sha256"])
        if json.loads((SOURCE / "mallory-hdfs37-healthy-node2-v3.json").read_text()) != source_config:
            raise RuntimeError("compiled healthy runtime config changed")
        for row in config["runtime_artifacts"]:
            require(Path(row["path"]), row["sha256"])
        if OUT.exists():
            if not (OUT / "checkpoint.json").is_file() or not (OUT / "config.json").is_file() or \
                    json.loads((OUT / "config.json").read_text()) != config:
                raise RuntimeError("existing full output has no byte-equivalent resumable checkpoint")
        if shutil.disk_usage("/tmp").free < 6_000_000_000:
            raise RuntimeError("node2 scratch below 6 GB reserve")
    return {"case_id": "HDFS-37", "status": "runtime_preflight_pass" if runtime else
            "static_preflight_pass", "config_sha256": sha(CONFIG),
            "initial_closure_faults": len(initial), "resuming": OUT.exists() if runtime else False,
            "jvm_started": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--static", action="store_true")
    mode.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    print(json.dumps(preflight(args.runtime), sort_keys=True))


if __name__ == "__main__":
    main()
