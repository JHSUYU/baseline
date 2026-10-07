#!/usr/bin/env python3
"""Offline bytecode and actor/core/replica mismatch smoke; no cluster."""

import copy
import json
from pathlib import Path
import subprocess

from deps import asm_jars
from feedback import (actor_registrations, checked_target_identity, events,
                      fields, strict_sequence, target_after, target_after_any_actor)

CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence/offline-smoke"
JAVA8 = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HOOKS = {
    "org.apache.solr.common.cloud.SolrZkClient": {"io": 6},
    "org.apache.solr.cloud.ZkController": {
        "registerNode": 1, "enterRegister": 1, "exitRegister": 2, "targetCheck": 1},
    "org.apache.solr.cloud.MiniSolrCloudCluster": {"registerJettyRole": 1},
}
PLAN = ("GET_DATA|/collections/testAddMultipleReplicas/state.json|1|caller=<external>|"
        "actor=jetty:node1|collection=testAddMultipleReplicas|shard=shard1|"
        "replica=core_node1|core=coreA;"
        "GET_DATA|/collections/testAddMultipleReplicas/state.json|@1|caller=<external>|"
        "actor=jetty:node1|collection=testAddMultipleReplicas|shard=shard1|"
        "replica=core_node1|core=coreA|after=F0|seed_global=2")


def changed_target(trace: list[dict], updates: dict[str, str],
                   registration: dict | None = None) -> list[dict]:
    """Move the post-fault guard into another otherwise valid register context."""
    altered = copy.deepcopy(trace)
    if registration is not None:
        altered.insert(0, registration)
    target_index = next(i for i, event in enumerate(altered)
                        if event["kind"] == "TARGET_CHECK")
    target = altered[target_index]
    current = fields(target)
    current.update(updates)
    target["parts"] = [part if "=" not in part else
                       part.split("=", 1)[0] + "=" + current[part.split("=", 1)[0]]
                       for part in target["parts"]]
    context = [key + "=" + current[key] for key in
               ("collection", "shard", "replica", "core", "node", "client_id",
                "reader_id", "thread")]
    altered.insert(target_index, {"seq": target["seq"], "kind": "REGISTER_ENTER",
                                  "parts": context})
    altered.insert(target_index + 2, {"seq": target["seq"], "kind": "REGISTER_EXIT",
                                      "parts": context})
    return altered


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    classes = CASE / "smoke-classes"
    classes.mkdir(exist_ok=True)
    cp = (CASE / "classpath.txt").read_text().strip()
    asm = asm_jars()[0]
    subprocess.run([str(JAVA8 / "javac"), "-cp", cp + ":" + str(asm),
                    "-d", str(classes), str(CASE / "probe/AsmHookAudit.java"),
                    str(CASE / "probe/SmokeProbe.java")], check=True)
    counts = {}
    for name, expected in HOOKS.items():
        source = CASE / "classes" / (name.replace(".", "/") + ".class")
        counts[name] = {}
        for hook, expected_count in expected.items():
            result = subprocess.check_output([str(JAVA8 / "java"), "-cp",
                                              str(classes) + ":" + str(asm),
                                              "baseline.solr05v2.AsmHookAudit", str(source),
                                              hook, str(expected_count)], text=True).strip()
            counts[name][hook] = int(result)
    proc = subprocess.run([str(JAVA8 / "java"),
                           "-Dsolr05.v2.trace=" + str(EVIDENCE / "events.tsv"),
                           "-Dsolr05.v2.faults=" + PLAN, "-cp",
                           str(classes) + ":" + cp, "baseline.solr05v2.SmokeProbe"],
                          capture_output=True, text=True, check=True)
    trace = events(EVIDENCE / "events.tsv")
    applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    observed = [e for e in trace if e["kind"] == "IO_OBSERVED"]
    final = applied[-1]["seq"] if applied else -1
    if (len(applied) != 2 or len(observed) != 6 or
            "SOLR05_V2_SMOKE_PASS" not in proc.stdout or
            not strict_sequence(PLAN.split(";"), trace) or
            not checked_target_identity(trace) or
            not target_after(trace, final)[0]["SOLR-05"] or
            strict_sequence([PLAN.split(";")[0].replace("node1", "node2"),
                             PLAN.split(";")[1]], trace) or
            strict_sequence([PLAN.split(";")[0].replace("core_node1", "core_node2"),
                             PLAN.split(";")[1]], trace)):
        raise RuntimeError("Actor/context selector or ledger smoke failed")
    clients = actor_registrations(trace)
    other = next(v for v in clients.values() if v["role"] == "node2")
    wrong_node = changed_target(trace, {
        "actor": "jetty:node2", "node": other["node"],
        "client_id": other["client_id"], "reader_id": other["reader_id"]})
    wrong_replica = changed_target(trace, {"replica": "core_node2", "core": "coreB"})
    right = next(v for v in clients.values() if v["role"] == "node1")
    replacement = changed_target(trace, {"client_id": "999999001", "reader_id": "999999002"},
                                 {"seq": 0, "kind": "ACTOR_REGISTERED",
                                  "parts": ["client_id=999999001", "reader_id=999999002",
                                            "node=" + right["node"]]})
    for name, altered in (("wrong_node", wrong_node), ("wrong_replica", wrong_replica),
                          ("replacement_client_same_node", replacement)):
        if (not checked_target_identity(altered) or
                not strict_sequence(PLAN.split(";"), altered) or
                not target_after_any_actor(altered, final)[0]["SOLR-05"] or
                target_after(altered, final)[0]["SOLR-05"]):
            raise RuntimeError("Ledger counted mismatched post-fault target: " + name)
    (EVIDENCE / "receipt.json").write_text(json.dumps({
        "asm_bytecode_hook_counts": counts,
        "wrong_node_io_observed": 2, "wrong_replica_same_node_io_observed": 2,
        "selected_faults_applied": 2, "target_after_selected_fault": True,
        "wrong_node_target_rejected": True, "wrong_replica_target_rejected": True,
        "replacement_client_same_node_target_rejected": True,
        "wrong_reader_registration_rejected": True,
        "plan": PLAN, "cluster_started": False,
    }, indent=2, sort_keys=True) + "\n")
    print("SOLR05_V2_OFFLINE_SMOKE_PASS")


if __name__ == "__main__":
    main()
