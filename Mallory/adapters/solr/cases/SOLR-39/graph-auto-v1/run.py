#!/usr/bin/env python3
"""Resume a bounded graph-guided SOLR-39 Time-test campaign on node0."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import socket
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = ROOT / "Mallory/adapters/solr/cases/SOLR-39/preemptive-healthy-v3/config.json"
CONFIG = HERE / "config.json"
OUT = ROOT / "data/mallory/solr39_graph_auto_v1_node0/SOLR-39"
CORE = ROOT / "Mallory/core/campaign.py"


def make_config() -> dict:
    config = json.loads(BASE.read_text())
    config.update({
        "revision": "SOLR-39-graph-auto-v1-actor-replay",
        "campaign_kind": "healthy-closure-guided-with-bounded-actor-replay",
        "calibration_only": False,
        "auto_promote_if_healthy": True,
        "allow_node_timeline_guidance": True,
        "node_timeline_exploration_interval": 2,
        "require_event_time_paths": False,
        "reject_coarse_roots": True,
        "explore_outside_closure": False,
        "actor_miss_replays": 2,
        "target_branch_replays": 8,
        "max_queue": 400,
        "budget": {"trials": 30, "seconds": 1200,
                   "trial_timeout_seconds": 240,
                   "max_faults_per_trial": 1},
        "diagnostic_controller_sha256": hashlib.sha256(CORE.read_bytes()).hexdigest(),
    })
    config.pop("core_release", None)
    config["agent_properties"]["auto.io.doors"] = False
    saved = json.dumps(config, indent=2, sort_keys=True) + "\n"
    if CONFIG.exists():
        if CONFIG.read_text() != saved:
            raise RuntimeError("saved config differs from generated pins")
    else:
        CONFIG.write_text(saved)
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if socket.gethostname().split(".", 1)[0] != "node0":
        raise RuntimeError("this isolated diagnostic is assigned to node0")
    sys.path.insert(0, str(ROOT))
    from Mallory.core import campaign  # noqa: E402
    from Mallory.dispatch import scheduler  # noqa: E402
    config = make_config()
    campaign.validate_config(config)
    scheduler.verify_runtime_artifacts(config)
    if args.preflight_only:
        print(json.dumps({"case_id": "SOLR-39", "mode": "graph_auto",
                          "budget": config["budget"], "runtime_pins_verified": True},
                         sort_keys=True))
        return 0
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        state = campaign.run(CONFIG, OUT)
        print(json.dumps({"case_id": "SOLR-39", "status": state["status"],
                          "completed_trials": state["completed_trials"]}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
