#!/usr/bin/env python3
"""Case-local SOLR-09 campaign with runtime deleteCore actor binding."""

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
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-09/runtime-role-v1/work"
sys.path.insert(0, str(PINNED))
sys.path.insert(1, str(ROOT))

from Mallory.core import campaign  # noqa: E402
from Mallory.core.scheduler import sequence_signature  # noqa: E402

ROLE = "delete-replica-deletecore"
SITE = ("org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler"
        "#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1")
REGION = ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd"
          "#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;"
          "Ljava/lang/String;Lorg/apache/solr/common/cloud/ZkNodeProps;"
          "Ljava/lang/String;Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V")
CHECK = REGION + "@277:branch:7"
BASE_ANALYZE = campaign.analyze
BASE_MUTATE = campaign.mutate
BASE_RUN_TRIAL = campaign._run_trial


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_package() -> None:
    manifest = json.loads((HERE / "sha-manifest.json").read_text())
    if manifest.get("case_id") != "SOLR-09" or manifest.get("schema_version") != 1:
        raise ValueError("wrong node0 package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"node0 package changed: {name}")


def role_receipt(event: dict, point: dict) -> bool:
    return (event.get("site") == SITE and event.get("role") == ROLE
            and event.get("role_resolution") == "unique"
            and event.get("role_ordinal") == point.get("role_ordinal")
            and event.get("role_node") == event.get("node")
            and event.get("role_epoch") == event.get("epoch")
            and event.get("role_source_occurrence") == event.get("occurrence")
            and event.get("region") == REGION
            and isinstance(event.get("thread_id"), int)
            and isinstance(event.get("node"), str)
            and event["node"] != "unknown")


def analyze(trace, target, plan, **kwargs):
    feedback = BASE_ANALYZE(trace, target, plan, **kwargs)
    by_id = {event.get("id"): event for event in trace.events}
    for door in feedback.get("doors", []):
        event = by_id.get(door.get("event_id"))
        if event and event.get("site") == SITE:
            for key in ("role", "role_resolution", "role_ordinal", "role_node",
                        "role_epoch", "role_source_occurrence"):
                door[key] = event.get(key)
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
                or fault.get("exception_class") != "java.util.concurrent.TimeoutException"
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
    feedback["command_role_identity_valid"] = valid
    feedback["command_role_receipts"] = receipts
    if not valid:
        feedback["all_faults_effective"] = False
        feedback["fault_identity_valid"] = False
        feedback["target_exception_candidate"] = False
        feedback["status"] = "fault_command_role_identity_invalid"
    return feedback


def mutate(parent, feedback, config):
    candidates = BASE_MUTATE(parent, feedback, config)
    exact = {json.dumps(door["point"], sort_keys=True): door
             for door in feedback.get("doors", []) if door.get("site") == SITE
             and door.get("role") == ROLE and door.get("role_resolution") == "unique"
             and isinstance(door.get("role_ordinal"), int)
             and door.get("local_timeline_evidence")}
    result = []
    seen = set()
    for candidate in candidates:
        fault = candidate["faults"][-1]
        point = fault["point"]
        if point.get("site") == SITE:
            door = exact.get(json.dumps(point, sort_keys=True))
            if door is None:
                continue
            fault["point"] = {"site": SITE, "role": ROLE,
                              "role_ordinal": door["role_ordinal"]}
            fault["role_source"] = {"healthy_event_id": door["event_id"],
                                    "healthy_node": door["role_node"],
                                    "healthy_epoch": door["role_epoch"],
                                    "healthy_occurrence": door["role_source_occurrence"]}
            candidate["selection_reason"] = "runtime_deletecore_role"
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
    verify_package()
    config = json.loads(config_path.read_text())
    if config.get("case_id") != "SOLR-09" or config.get("cluster_test") != (
            "org.apache.solr.cloud.DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup"):
        raise ValueError("wrong case or JUnit selector")
    if config.get("budget") != {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 480}:
        raise ValueError("full campaign budget differs")
    if config.get("calibration_only") or not config.get("auto_promote_if_healthy"):
        raise ValueError("config is not a full campaign")
    if (config.get("admission", {}).get("host") != "node0"
            or config.get("target", {}).get("check_sites") != [CHECK]
            or config.get("require_event_time_paths") is not False
            or config.get("allow_local_timeline_doors") is not True):
        raise ValueError("node0 target or graph-optional admission changed")
    for row in config.get("runtime_artifacts", []):
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    compiled = Path(config["mapping"]["compiled_jar"])
    if sha(compiled) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("Solr distribution JAR changed")
    with zipfile.ZipFile(compiled) as archive:
        for member, expected in (
                ("org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class",
                 config["mapping"]["compiled_class_sha256"]),
                ("org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.class",
                 config["mapping"]["overseer_compiled_class_sha256"])):
            actual = hashlib.sha256(archive.read(member)).hexdigest()
            if actual != expected:
                raise ValueError(f"compiled Solr class changed: {member}")
    source = Path(config["cwd"])
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != "e27f44e3d78dfcec230c97e0a1240e3751daeff9":
        raise ValueError("Solr source revision changed")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).strip():
        raise ValueError("Solr source checkout is dirty")
    for field, rel in (("test_source_sha256", "solr/core/src/test/org/apache/solr/cloud/DeleteReplicaTest.java"),
                       ("target_source_sha256", "solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java"),
                       ("overseer_source_sha256", "solr/core/src/java/org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.java")):
        if sha(source / rel) != config["mapping"][field]:
            raise ValueError(f"Solr source SHA changed: {field}")
    campaign.validate_config(config)
    if not Path(campaign.__file__).resolve().is_relative_to(PINNED):
        raise ValueError("campaign core did not load from case-local snapshot")
    if admission_path:
        admission = json.loads(admission_path.read_text())
        terminal_path = Path(admission.get("solr31_terminal_result_path") or "")
        if (admission.get("go") is not True or admission.get("host") != "node0"
                or admission.get("case_id") != "SOLR-09"
                or admission.get("solr31_terminal") is not True
                or admission.get("config_sha256") != sha(config_path)
                or admission.get("runner_sha256") != sha(Path(__file__))
                or admission.get("launcher_sha256") != sha(HERE / "run_full_node0.sh")
                or admission.get("collector_sha256") != sha(HERE / "collect_offhost.py")
                or admission.get("package_manifest_sha256") != sha(HERE / "sha-manifest.json")
                or admission.get("intended_output") != str(out.resolve())
                or not terminal_path.is_file()
                or admission.get("solr31_terminal_result_sha256") != sha(terminal_path)):
            raise ValueError("dispatch GO receipt missing or mismatched")
        terminal = json.loads(terminal_path.read_text())
        if (terminal.get("case_id") != "SOLR-31"
                or terminal.get("status") not in {"budget_exhausted", "queue_exhausted"}
                or terminal.get("calibration_only") is not False):
            raise ValueError("SOLR-31 full campaign is not terminal")
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
