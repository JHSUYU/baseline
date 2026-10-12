#!/usr/bin/env python3
"""Stage a healthy-only SOLR-10 role trace from the pinned v28a workload."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parents[4]
SOLR = BASELINE / "Mallory/adapters/solr"
BASE_CONFIG = SOLR / "cases/SOLR-10/config-v28a-overseer-task-healthy.json"
OUTPUT = HERE / "config-role-v1-healthy-node2.json"
AGENT = HERE / "releases/v1/mallory-agent.jar"
ADAPTER = HERE / "releases/v1/mallory-solr-adapter.jar"
RUNNER = HERE / "run_pilot.py"
ROLE_RUNNER = HERE / "run_pilot_role_v1.py"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/solr-routed-alias-v23")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    config = json.loads(BASE_CONFIG.read_text())
    assert config["case_id"] == "SOLR-10"
    config["revision"] = "SOLR-10-overseer-role-v1-healthy-node2"
    config["agent_jar"] = str(AGENT)
    config["agent_properties"]["adapter.jar"] = str(ADAPTER)
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    config["env"]["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    config["cwd"] = str(SOURCE)
    config["source_equivalent_root"] = str(SOURCE)
    config["command"] = ["python3", str(RUNNER), "SOLR-10", "--source",
                         str(SOURCE), "--output", "{trial_dir}", "--campaign",
                         "--timeout", "420"]
    config["budget"] = {"max_faults_per_trial": 1, "seconds": 900,
                        "trial_timeout_seconds": 480, "trials": 1}
    config["calibration_only"] = True
    config["auto_promote_if_healthy"] = False
    config["mapping"].pop("agent_build", None)
    config["mapping"].update({
        "agent_sha256": sha(AGENT),
        "overseer_source_sha256": "cae75fa3ae928f085b69dd5d39c4bac978b7d1160692b936b934f8a59838c14b",
        "overseer_class_sha256": "98f21c0235c5e9dc7937d67e0a44dfeccd3726582feb2696d7fbe4420ca8a6c0",
        "status": "role_v1_healthy_only_preflight",
        "healthy_seed_verified": False,
        "node_identity_binding_verified": False,
        "door_status": "role_ordinal_pending_fresh_healthy_trace",
    })
    pinned = [AGENT, ADAPTER, RUNNER, ROLE_RUNNER,
              SOLR / "cases/SOLR-10/sites-v28-overseer-task.json",
              SOLR / "solr_junit_runner_v8.py",
              SOLR / "releases/v10/inventory.json",
              SOLR / "releases/v10/source_reference.json"]
    config["runtime_artifacts"] = [{"path": str(path), "sha256": sha(path)}
                                   for path in pinned]
    OUTPUT.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(f"{OUTPUT} {sha(OUTPUT)}")


if __name__ == "__main__":
    main()
