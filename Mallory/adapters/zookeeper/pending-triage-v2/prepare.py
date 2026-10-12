#!/usr/bin/env python3
"""Prepare the isolated, source-pinned ZK04 readBool healthy preflight."""

import copy
import gzip
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/zk11-independent-unit")
AGENT = BASE / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
CORE = BASE / ("Mallory/dispatch/releases/"
               "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f")
OVERLAY = BASE / "Mallory/adapters/zookeeper/zookeeper-3.8.7-connectpath-lane2-overlay.json"
ORIGINAL = BASE / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-04-5a-healthy.json"
PRIOR = BASE / "data/mallory/admissions/ZOOKEEPER-04-5a-actor-retention-v1.json"
TRACE_HEALTHY = BASE / "data/mallory/pilot_core5a/ZOOKEEPER-04/trials/r0000/events.jsonl.gz"
TRACE_FAULT = BASE / "data/mallory/pilot_core5a/ZOOKEEPER-04/trials/r0001/events.jsonl.gz"
PILOT_GATE = HERE / "pilot-gate.json"
SOURCE_RELS = (
    "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java",
    "zookeeper-jute/src/main/java/org/apache/jute/BinaryInputArchive.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/server/ConnectionMetricsTest.java",
    "zookeeper-server/src/test/java/org/apache/zookeeper/server/ZooKeeperServerTest.java",
)
DOOR = ("org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest("
        "Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V@1420:door:1")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def events(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def main():
    assert read(OVERLAY)["base_commit"] == "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
    assert SOURCE.is_dir() and AGENT.is_file() and CORE.is_dir()
    original = read(ORIGINAL)
    overlay = read(OVERLAY)
    assert original["case_id"] == "ZOOKEEPER-04"
    assert original["target"]["check_sites"] == [
        "org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest("
        "Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V@1434:branch:7"]
    assert original["mapping"]["target_source_sha256"] == overlay["modified_files"][SOURCE_RELS[0]]
    source = (SOURCE / SOURCE_RELS[0]).read_text(encoding="utf-8").splitlines()
    assert 'readOnly = bia.readBool("readOnly");' in source[1416]
    assert '} catch (IOException e) {' in source[1418]
    assert 'if (connReq.getLastZxidSeen() > zkDb.dataTree.lastProcessedZxid) {' in source[1430]
    assert 'return in.readBoolean();' in (SOURCE / SOURCE_RELS[1]).read_text(encoding="utf-8")

    healthy = events(TRACE_HEALTHY)
    faulted = events(TRACE_FAULT)
    healthy_target = [e for e in healthy if e.get("type") == "TARGET_CHECK"
                      and e.get("node") == "zk2"]
    assert len(healthy_target) == 1 and healthy_target[0]["seq"] == 641
    applied = [e for e in faulted if e.get("type") == "FAULT_APPLIED"
               and e.get("site") == "zookeeper.client.connect.read"
               and e.get("node") == "zk2"]
    later = [e for e in faulted if e.get("type") == "TARGET_CHECK"
             and e.get("node") == "zk2" and e.get("seq", 0) > applied[0]["seq"]]
    assert len(applied) == 1 and applied[0]["seq"] == 637
    assert len(later) == 1 and later[0]["seq"] == 683
    assert applied[0]["occurrence"] != later[0]["occurrence"]
    assert not [e for e in later if e["occurrence"] == applied[0]["occurrence"]]

    config = copy.deepcopy(original)
    sites = read(original["site_file"])
    assert sites["doors"] == []
    sites["doors"] = [{"class": "org.apache.zookeeper.server.ZooKeeperServer",
                       "method": "processConnectRequest",
                       "descriptor": "(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V",
                       "line": 1420,
                       "callee": "org.apache.jute.BinaryInputArchive#readBool(Ljava/lang/String;)Z",
                       "exception_class": "java.io.IOException"}]
    sites_path = HERE / "ZOOKEEPER-04.readbool.sites.json"
    config_path = HERE / "ZOOKEEPER-04.readbool.healthy-only.json"
    write(sites_path, sites)

    config.update(calibration_only=True, auto_promote_if_healthy=False,
                  require_event_time_paths=True, reject_coarse_roots=True,
                  site_file=str(sites_path), agent_jar=str(AGENT),
                  core_release=str(CORE),
                  source_overlay_receipt=str(OVERLAY),
                  source_overlay_receipt_sha256=sha(OVERLAY))
    config["budget"] = {"trials": 1, "seconds": 300,
                        "max_faults_per_trial": 1,
                        "trial_timeout_seconds": 180,
                        "trial_timeout_basis": "source_only_preflight_ceiling"}
    config["mapping"].update(
        status="readbool_source_preflight_not_executed",
        healthy_seed_verified=False,
        node_identity_binding_verified=False,
        agent_sha256=sha(AGENT))
    config["mapping"].pop("verified_healthy_probe", None)
    config["runtime_artifacts"] = [
        {"path": str(AGENT), "sha256": sha(AGENT)},
        {"path": str(sites_path), "sha256": sha(sites_path)}]
    write(config_path, config)

    receipt = {
        "schema_version": 1, "case_id": "ZOOKEEPER-04",
        "status": "target_retaining_readbool_door_source_plausible_unverified",
        "source_commit": overlay["base_commit"],
        "source_sha256": {rel: sha(SOURCE / rel) for rel in SOURCE_RELS},
        "overlay_receipt": str(OVERLAY), "overlay_receipt_sha256": sha(OVERLAY),
        "prior_pilot_audit": str(PRIOR), "prior_pilot_audit_sha256": sha(PRIOR),
        "prior_trace": {"healthy": {"path": str(TRACE_HEALTHY),
                                    "sha256": sha(TRACE_HEALTHY),
                                    "target_seq": 641},
                        "faulted": {"path": str(TRACE_FAULT),
                                    "sha256": sha(TRACE_FAULT),
                                    "fault_seq": 637, "later_target_seq": 683,
                                    "fault_occurrence": applied[0]["occurrence"],
                                    "later_target_occurrence": later[0]["occurrence"]}},
        "old_connect_read_conclusion": "fault_model_target_lost_for_exact_connect_attempt",
        "new_door": {"expected_site_pending_catalog": DOOR,
                     "source_call_line": 1417,
                     "patched_call_line": 1420,
                     "exception_class": "java.io.IOException",
                     "catch_source_line": 1419,
                     "check_source_line": 1431,
                     "check_patched_line": 1434,
                     "operand_effect": "does_not_modify_client_or_server_zxid"},
        "healthy_config": str(config_path),
        "healthy_config_sha256": sha(config_path),
        "site_file": str(sites_path), "site_file_sha256": sha(sites_path),
        "pilot_gate": str(PILOT_GATE), "pilot_gate_sha256": sha(PILOT_GATE),
        "execution": "no_cluster_junit_or_fault_trial",
    }
    write(HERE / "source-preflight.json", receipt)


if __name__ == "__main__":
    main()
