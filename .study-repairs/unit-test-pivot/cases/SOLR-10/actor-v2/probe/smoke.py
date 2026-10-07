#!/usr/bin/env python3
"""Offline ASM instruction audit and wrong-actor smoke; no Solr cluster starts."""

import copy
import json
from pathlib import Path
import subprocess

from feedback import (actor_registrations, checked_target_identity, events,
                      strict_sequence, target_after, target_after_any_actor)
from deps import asm_jars


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence/offline-smoke"
JAVA8 = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HOOKS = {
    "org.apache.solr.common.cloud.SolrZkClient": {"io": 6},
    "org.apache.solr.cloud.ZkController": {"registerNode": 1},
    "org.apache.solr.cloud.MiniSolrCloudCluster": {"registerJettyRole": 1},
    "org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd": {"targetCheck": 1},
    "org.apache.solr.update.processor.RoutedAliasUpdateProcessor": {"targetCheck": 2},
}


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    smoke_classes = CASE / "smoke-classes"
    smoke_classes.mkdir(exist_ok=True)
    cp = (CASE / "classpath.txt").read_text().strip()
    asm = asm_jars()[0]
    subprocess.run([str(JAVA8 / "javac"), "-cp", cp + ":" + str(asm),
                    "-d", str(smoke_classes), str(CASE / "probe/AsmHookAudit.java"),
                    str(CASE / "probe/SmokeProbe.java")], check=True)
    counts = {}
    for name, expected in HOOKS.items():
        source = CASE / "classes" / (name.replace(".", "/") + ".class")
        counts[name] = {}
        for hook, expected_count in expected.items():
            result = subprocess.check_output([str(JAVA8 / "java"), "-cp",
                                              str(smoke_classes) + ":" + str(asm),
                                              "baseline.solr103940.AsmHookAudit", str(source),
                                              hook, str(expected_count)], text=True).strip()
            counts[name][hook] = int(result)
    plan = ("GET_DATA|/aliases.json|1|caller=<external>|actor=jetty:node1;"
            "GET_DATA|/aliases.json|@1|caller=<external>|actor=jetty:node1|"
            "after=F0|seed_global=2")
    proc = subprocess.run([str(JAVA8 / "java"),
                           "-Dsolr103940.v2.trace=" + str(EVIDENCE / "events.tsv"),
                           "-Dsolr103940.v2.faults=" + plan,
                           "-cp", str(smoke_classes) + ":" + cp,
                           "baseline.solr103940.SmokeProbe"],
                          capture_output=True, text=True, check=True)
    rows = [line.split("\t") for line in (EVIDENCE / "events.tsv").read_text().splitlines()]
    applied = [r for r in rows if r[2] == "IO_APPLIED_CONNECTION_LOSS"]
    observed = [r for r in rows if r[2] == "IO_OBSERVED"]
    guards = [r for r in rows if r[2] == "TARGET_CHECK"]
    if (len(applied) != 2 or len(observed) != 4 or len(guards) != 3 or
            [r[4] for r in applied] != ["/aliases.json", "/aliases.json"] or
            [r[5] for r in applied] != ["ordinal=1", "ordinal=@1"] or
            any("actor=jetty:node1" not in r for r in applied) or
            not any("actor=jetty:node2" in r for r in observed) or
            [r[4] for r in guards] != ["SOLR-10", "SOLR-39", "SOLR-40"] or
            "SOLR103940_V2_SMOKE_PASS" not in proc.stdout):
        raise RuntimeError("Wrong-actor, per-actor ordinal, or exact-guard smoke failed")
    parsed = events(EVIDENCE / "events.tsv")
    if (not strict_sequence(plan.split(";"), parsed) or
            not checked_target_identity(parsed) or
            not all(target_after(parsed, int(applied[-1][0]))[0].values()) or
            strict_sequence([plan.split(";")[0].replace("node1", "node2"),
                             plan.split(";")[1]], parsed)):
        raise RuntimeError("Offline actor-aware ledger verifier accepted a wrong actor")
    migrated = copy.deepcopy(parsed)
    other = next(value for value in actor_registrations(migrated).values()
                 if value["role"] == "node2")
    for event in migrated:
        if event["kind"] == "TARGET_CHECK" and event["parts"][1] == "SOLR-39":
            event["parts"] = [part if not part.startswith(("actor=", "node=", "client_id=", "manager_id="))
                              else {"actor": "actor=jetty:node2", "node": "node=" + other["node"],
                                    "client_id": "client_id=" + other["client_id"],
                                    "manager_id": "manager_id=" + other["manager_id"]}[part.split("=", 1)[0]]
                              for part in event["parts"]]
    final_fault = int(applied[-1][0])
    if (not checked_target_identity(migrated) or
            not target_after_any_actor(migrated, final_fault)[0]["SOLR-39"] or
            target_after(migrated, final_fault)[0]["SOLR-39"] or
            not target_after(migrated, final_fault)[0]["SOLR-10"]):
        raise RuntimeError("Ledger counted a guard on a different registered client")
    same_node_new_client = copy.deepcopy(parsed)
    selected = next(value for value in actor_registrations(same_node_new_client).values()
                    if value["role"] == "node1")
    same_node_new_client.append({"seq": 0, "kind": "ACTOR_REGISTERED",
                                 "parts": ["client_id=999999001", "manager_id=999999002",
                                           "node=" + selected["node"]]})
    for event in same_node_new_client:
        if event["kind"] == "TARGET_CHECK" and event["parts"][1] == "SOLR-39":
            event["parts"] = ["client_id=999999001" if part.startswith("client_id=") else
                              "manager_id=999999002" if part.startswith("manager_id=") else part
                              for part in event["parts"]]
    if (not checked_target_identity(same_node_new_client) or
            not strict_sequence(plan.split(";"), same_node_new_client) or
            target_after(same_node_new_client, final_fault)[0]["SOLR-39"]):
        raise RuntimeError("Ledger counted a replacement client on the same Jetty node")
    (EVIDENCE / "receipt.json").write_text(json.dumps({
        "asm_bytecode_hook_counts": counts,
        "wrong_actor_observed": 2,
        "faults_applied_to_selected_actor": len(applied),
        "three_exact_guards_after_final_fault": len(guards),
        "ledger_verifier_rejects_wrong_actor": True,
        "wrong_actor_target_after_rejected": True,
        "same_node_replacement_client_target_after_rejected": True,
        "wrong_alias_manager_rejected": True,
        "plan": plan,
        "cluster_started": False,
    }, indent=2) + "\n")
    print("SOLR103940_V2_OFFLINE_SMOKE_PASS")


if __name__ == "__main__":
    main()
