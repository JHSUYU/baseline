#!/usr/bin/env python3
"""Case-local SOLR-13 campaign with runtime routed-alias write binding."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = HERE / "work"
sys.path.insert(0, str(PINNED))
sys.path.insert(1, str(ROOT))

from Mallory.core import campaign  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402

ROLE = "maintain-routed-alias-write"
SITE = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
        "#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1")
REGION = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
          "#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V")
PARENT_REGION = ("org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd"
                 "#call(Lorg/apache/solr/common/cloud/ClusterState;"
                 "Lorg/apache/solr/common/cloud/ZkNodeProps;"
                 "Lorg/apache/solr/common/util/NamedList;)V")
BASE_ANALYZE = campaign.analyze
BASE_MUTATE = campaign.mutate
BASE_RUN_TRIAL = campaign._run_trial


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def role_receipt(event: dict, point: dict) -> bool:
    parent = event.get("role_parent_occurrence")
    node = event.get("node")
    epoch = event.get("epoch")
    return (event.get("site") == SITE and event.get("role") == ROLE
            and event.get("role_resolution") == "unique"
            and event.get("role_ordinal") == point.get("role_ordinal")
            and event.get("role_node") == event.get("node")
            and event.get("role_epoch") == event.get("epoch")
            and event.get("role_source_occurrence") == event.get("occurrence")
            and isinstance(parent, str)
            and parent.startswith(f"{node}:{epoch}:{PARENT_REGION}:")
            and event.get("region") == REGION
            and isinstance(event.get("thread_id"), int)
            and isinstance(node, str) and node != "unknown")


def analyze(trace, target, plan, **kwargs):
    feedback = BASE_ANALYZE(trace, target, plan, **kwargs)
    by_id = {event.get("id"): event for event in trace.events}
    for door in feedback.get("doors", []):
        event = by_id.get(door.get("event_id"))
        if event and event.get("site") == SITE:
            for key in ("role", "role_resolution", "role_ordinal", "role_node",
                        "role_epoch", "role_source_occurrence", "role_parent_occurrence"):
                door[key] = event.get(key)
    if not plan and feedback.get("status") == "observed" and not any(
            door.get("site") == SITE and door.get("role") == ROLE
            and door.get("role_resolution") == "unique"
            for door in feedback.get("doors", [])):
        feedback["status"] = "healthy_alias_role_missing"
    valid = True
    receipts = []
    for fault in plan:
        point = fault.get("point", {})
        if point.get("role") != ROLE:
            continue
        fid = fault.get("fault_id")
        matched = [e for e in trace.events if e.get("type") == "FAULT_MATCHED"
                   and e.get("fault_id") == fid]
        applied = [e for e in trace.events if e.get("type") == "FAULT_APPLIED"
                   and e.get("fault_id") == fid]
        if (set(point) != {"site", "role", "role_ordinal"}
                or fault.get("fault_type") != "EXCEPTION"
                or fault.get("exception_class") != "org.apache.zookeeper.KeeperException$BadVersionException"
                or len(matched) != 1 or len(applied) != 1
                or not role_receipt(matched[0], point)
                or not role_receipt(applied[0], point)
                or any(matched[0].get(key) != applied[0].get(key)
                       for key in ("node", "epoch", "occurrence", "thread_id"))):
            valid = False
            continue
        receipts.append({"fault_id": fid, "node": applied[0]["node"],
                         "epoch": applied[0]["epoch"],
                         "occurrence": applied[0]["occurrence"],
                         "applied_event_id": applied[0]["id"]})
    feedback["alias_role_identity_valid"] = valid
    feedback["alias_role_receipts"] = receipts
    if not valid:
        feedback["all_faults_effective"] = False
        feedback["fault_identity_valid"] = False
        feedback["target_exception_candidate"] = False
        feedback["status"] = "fault_alias_role_identity_invalid"
    return feedback


def mutate(parent, feedback, config):
    candidates = BASE_MUTATE(parent, feedback, config)
    exact = {json.dumps(door["point"], sort_keys=True): door
             for door in feedback.get("doors", []) if door.get("site") == SITE
             and door.get("role") == ROLE and door.get("role_resolution") == "unique"
             and isinstance(door.get("role_ordinal"), int)
             and isinstance(door.get("role_parent_occurrence"), str)}
    result = []
    seen = set()
    for candidate in candidates:
        fault = candidate["faults"][-1]
        point = fault["point"]
        if point.get("site") != SITE:
            continue
        door = exact.get(json.dumps(point, sort_keys=True))
        if door is None:
            continue
        fault["point"] = {"site": SITE, "role": ROLE,
                          "role_ordinal": door["role_ordinal"]}
        fault["role_source"] = {"healthy_event_id": door["event_id"],
                                "healthy_node": door["role_node"],
                                "healthy_epoch": door["role_epoch"],
                                "healthy_occurrence": door["role_source_occurrence"],
                                "healthy_parent_occurrence": door["role_parent_occurrence"]}
        candidate["selection_reason"] = "runtime_maintain_alias_write_role"
        signature = sequence_signature(candidate["faults"])
        if signature not in seen:
            candidate["signature"] = signature
            result.append(candidate)
            seen.add(signature)
    return result


def run_trial(config, out, trial_id, plan, save_running, target_binding):
    # The fresh cluster can assign its Overseer to a different physical node.
    return BASE_RUN_TRIAL(config, out, trial_id, plan, save_running, None)


def preflight(config_path: Path, out: Path, admission_path: Path | None) -> dict:
    config = json.loads(config_path.read_text())
    if config.get("case_id") != "SOLR-13" or config.get("cluster_test") != (
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation"):
        raise ValueError("wrong case or JUnit selector")
    if config.get("budget") != {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 480}:
        raise ValueError("full campaign budget differs")
    if config.get("calibration_only") or not config.get("auto_promote_if_healthy"):
        raise ValueError("config is not a full campaign")
    for row in config.get("runtime_artifacts", []):
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    source = Path(config["cwd"])
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != "e27f44e3d78dfcec230c97e0a1240e3751daeff9":
        raise ValueError("Solr source revision changed")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("Solr source checkout is dirty")
    for field, rel in (("test_source_sha256", "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"),
                       ("target_source_sha256", "solr/core/src/java/org/apache/solr/cloud/api/collections/RoutedAlias.java"),
                       ("zk_state_reader_source_sha256", "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java")):
        if sha(source / rel) != config["mapping"][field]:
            raise ValueError(f"Solr source SHA changed: {field}")
    jar = Path(config["mapping"]["compiled_jar"])
    if sha(jar) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("Solr compiled core JAR changed")
    with zipfile.ZipFile(jar) as archive:
        member = "org/apache/solr/cloud/api/collections/RoutedAlias.class"
        if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"]["compiled_class_sha256"]:
            raise ValueError(f"Solr bytecode SHA changed: {member}")
    solrj = Path(config["mapping"]["aliases_manager_compiled_jar"])
    if sha(solrj) != config["mapping"]["aliases_manager_compiled_jar_sha256"]:
        raise ValueError("SolrJ compiled JAR changed")
    with zipfile.ZipFile(solrj) as archive:
        member = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class"
        if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"]["aliases_manager_class_sha256"]:
            raise ValueError(f"Solr bytecode SHA changed: {member}")
    campaign.validate_config(config)
    if not Path(campaign.__file__).resolve().is_relative_to(PINNED):
        raise ValueError("campaign core did not load from case-local snapshot")
    if admission_path:
        admission = json.loads(admission_path.read_text())
        if (admission.get("go") is not True or admission.get("host") != "node2"
                or admission.get("case_id") != "SOLR-13"
                or admission.get("config_sha256") != sha(config_path)
                or admission.get("runner_sha256") != sha(Path(__file__))
                or admission.get("intended_output") != str(out.resolve())):
            raise ValueError("dispatch GO receipt missing or mismatched")
    return {"config_sha256": sha(config_path), "source_head": head,
            "agent_sha256": sha(Path(config["agent_jar"])),
            "admission_sha256": sha(admission_path) if admission_path else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not args.preflight_only and args.admission_receipt is None:
        parser.error("dispatch GO receipt required for JVM campaign")
    receipt = preflight(args.config, args.out, args.admission_receipt)
    print(json.dumps({"preflight": "passed", **receipt}, sort_keys=True), flush=True)
    if args.preflight_only:
        return 0
    campaign.analyze = analyze
    campaign.mutate = mutate
    campaign._run_trial = run_trial
    state = campaign.run(args.config, args.out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
