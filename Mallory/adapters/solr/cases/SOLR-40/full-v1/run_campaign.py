#!/usr/bin/env python3
"""Pinned SOLR-40 full campaign using the exact alias watcher read door."""

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
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
sys.path.insert(0, str(PINNED))

from Mallory.core import campaign  # noqa: E402

DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
        "#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#getAliasProps(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)"
         "Ljava/util/Map;@132:branch:1")
BASE_ANALYZE = campaign.analyze
BASE_MUTATE = campaign.mutate
BASE_RUN_TRIAL = campaign._run_trial


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(trace, target, plan, **kwargs):
    feedback = BASE_ANALYZE(trace, target, plan, **kwargs)
    target_nodes = {row.get("node") for row in feedback.get("target_instances", [])}
    # The watcher and the selected check must both be seen on a named actor.
    # This is an actor constraint; it does not assert a causal watcher edge.
    exact = [door for door in feedback.get("doors", [])
             if door.get("site") == DOOR
             and door.get("point", {}).get("node") in target_nodes
             and door.get("point", {}).get("node") not in (None, "unknown")]
    feedback["watcher_doors_on_target_nodes"] = len(exact)
    feedback["doors"] = exact
    feedback["eligible_doors_before_target"] = len(exact)
    if not plan and feedback.get("status") == "observed" and not exact:
        feedback["status"] = "healthy_exact_watcher_door_missing"
    return feedback


def mutate(parent, feedback, config):
    return [candidate for candidate in BASE_MUTATE(parent, feedback, config)
            if candidate["faults"][-1]["point"].get("site") == DOOR]


def run_trial(config, out, trial_id, plan, save_running, target_binding):
    # A four-node JUnit can move its routed update to another physical node.
    # The fault point still pins its own named node/epoch/door ordinal.
    return BASE_RUN_TRIAL(config, out, trial_id, plan, save_running, None)


def preflight(config_path: Path, out: Path, admission_path: Path | None) -> dict:
    config = json.loads(config_path.read_text())
    if (config.get("case_id") != "SOLR-40" or config.get("cluster_test") !=
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test"):
        raise ValueError("wrong case or JUnit selector")
    if config.get("target", {}).get("check_sites") != [CHECK]:
        raise ValueError("wrong selected check")
    if config.get("budget") != {"trials": 80, "seconds": 3600,
                                "max_faults_per_trial": 3,
                                "trial_timeout_seconds": 480}:
        raise ValueError("full campaign budget differs")
    if config.get("calibration_only") or not config.get("auto_promote_if_healthy"):
        raise ValueError("config is not a full campaign")
    if config.get("site_file") != str(HERE / "sites.json"):
        raise ValueError("site file is not case-local")
    sites = json.loads((HERE / "sites.json").read_text())
    if len(sites.get("doors", [])) != 1 or sites["doors"][0].get("line") != 2312:
        raise ValueError("exact watcher door changed")
    for row in config.get("runtime_artifacts", []):
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    core = config["mapping"]["pinned_core"]
    if Path(core["root"]).resolve() != PINNED:
        raise ValueError("pinned core path changed")
    for rel, digest in core["files"].items():
        if sha(PINNED / rel) != digest:
            raise ValueError(f"pinned core changed: {rel}")
    if not Path(campaign.__file__).resolve().is_relative_to(PINNED):
        raise ValueError("campaign core did not load from pinned snapshot")
    source = Path(config["cwd"])
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                   text=True).strip()
    if head != config["mapping"]["source_git_revision"]:
        raise ValueError("Solr source revision changed")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                               text=True).strip():
        raise ValueError("Solr source checkout is dirty")
    for field, rel in (("test_source_sha256", "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"),
                       ("target_source_sha256", "solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"),
                       ("watcher_source_sha256", "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java")):
        if sha(source / rel) != config["mapping"][field]:
            raise ValueError(f"Solr source changed: {field}")
    for kind, member in (("target", "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
                         ("watcher", "org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class")):
        jar = Path(config["mapping"][f"{kind}_compiled_jar"])
        if sha(jar) != config["mapping"][f"{kind}_compiled_jar_sha256"]:
            raise ValueError(f"{kind} compiled JAR changed")
        with zipfile.ZipFile(jar) as archive:
            if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"][f"{kind}_class_sha256"]:
                raise ValueError(f"{kind} bytecode changed")
    campaign.validate_config(config)
    if admission_path:
        admission = json.loads(admission_path.read_text())
        if (admission.get("go") is not True or admission.get("host") != "node2"
                or admission.get("case_id") != "SOLR-40"
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
