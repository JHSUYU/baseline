#!/usr/bin/env python3
"""Generate the isolated, bounded SOLR-38 strict-path fault config."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "election-field-healthy-node2-v1/config-healthy-node2.json"
OUT = ROOT / "data/mallory/solr38_strict_fault_v3_node1/SOLR-38/pilot"
AGENT = (ROOT / "Mallory/instrumentation/releases/"
         "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar")
ADAPTER = HERE / "mallory-solr-adapter-v2.jar"
RELEASE = (ROOT / "Mallory/dispatch/releases/"
           "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4")


def sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate() -> dict:
    config = json.loads(BASE.read_text(encoding="utf-8"))
    old_adapter = config["agent_properties"]["adapter.jar"]
    old_sites = config["site_file"]
    config["revision"] = "SOLR-38-election-strict-pilot-node1-v3"
    config["admission"] = {
        "host": "node1", "scope": "fresh_healthy_strict_then_four_fault_trials",
        "intended_output": str(OUT),
        "fault_gate": "source-backed exact-object last-writer STATE edge and same-thread typed door path"}
    config["site_file"] = str(HERE / "sites.json")
    config["agent_jar"] = str(AGENT)
    config["agent_properties"]["adapter.jar"] = str(ADAPTER)
    config["command"][1] = str(HERE / "run_pilot.py")
    config["env"]["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    config["core_release"] = str(RELEASE)
    config["calibration_only"] = False
    config["auto_promote_if_healthy"] = True
    config["require_event_time_paths"] = True
    config["reject_coarse_roots"] = True
    config["explore_outside_closure"] = False
    config["allow_local_timeline_doors"] = False
    config["candidate_replays"] = 1
    config["budget"] = {"trials": 4, "seconds": 1800,
                        "trial_timeout_seconds": 480, "max_faults_per_trial": 1}
    config["mapping"]["election_adapter_sha256"] = sha(ADAPTER)
    config["mapping"]["value_diagnostic_adapter_sha256"] = sha(ADAPTER)
    config["mapping"]["source_backed_overlay_sha256"] = sha(HERE / "graph_overlay.py")
    config["mapping"]["source_backed_audit_sha256"] = sha(
        HERE.parent / "election-unique-writer-audit-v1/audit.py")
    config["mapping"]["pilot_runner_sha256"] = sha(HERE / "run_pilot.py")
    config["mapping"]["source_backed_gate_sha256"] = sha(HERE / "run_campaign.py")
    config["runtime_artifacts"] = [row for row in config["runtime_artifacts"]
                                   if row["path"] not in {old_adapter, old_sites}]
    for path in (HERE / "sites.json", ADAPTER, HERE / "run_pilot.py",
                 HERE / "graph_overlay.py", HERE / "run_campaign.py",
                 HERE / "config_v3.py", HERE / "preflight.py",
                 HERE.parent / "election-unique-writer-audit-v1/audit.py"):
        config["runtime_artifacts"].append({"path": str(path), "sha256": sha(path)})
    if (config["agent_jar"] != str(AGENT) or config["budget"]["max_faults_per_trial"] != 1
            or config["budget"]["trials"] != 4 or config["explore_outside_closure"]):
        raise ValueError("bounded strict pilot policy changed")
    return config
