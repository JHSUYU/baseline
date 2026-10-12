#!/usr/bin/env python3
"""Validate the caller-side exception probe with one healthy and three exact replays."""

from __future__ import annotations

import fcntl
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from Mallory.core import campaign  # noqa: E402

OUT = ROOT / "data/mallory/solr40_callee_probe_v3_node0/SOLR-40"
PLAN_FILE = (ROOT / "data/mallory/solr40_targeted_replay_v2_node0/SOLR-40"
             / "trials/r0007/plan.json")
LOCKS = ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock")
THROW_SITE = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps"
              "(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;"
              "@133:callthrow:7")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    plan = json.loads(PLAN_FILE.read_text())["faults"]
    assert len(plan) == 1 and config["target"]["throw_site"] == THROW_SITE
    point = plan[0]["point"]
    assert (point["node"], point["door_ordinal"]) == ("node3", 1)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "classification": "prior-witness-seeded probe validation, not Mallory auto-discovery",
        "case_id": "SOLR-40",
        "config_sha256": sha(config_path),
        "sites_sha256": sha(HERE / "sites.json"),
        "agent_jar_sha256": sha(Path(config["agent_jar"])),
        "source_plan": str(PLAN_FILE),
        "source_plan_sha256": sha(PLAN_FILE),
        "throw_site": THROW_SITE,
        "trial_schedule": ["healthy", "node3-ordinal1", "node3-ordinal1", "node3-ordinal1"],
    }
    manifest_path = OUT / "probe-validation-manifest.json"
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text()) == manifest
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        for trial_id, faults in [(0, []), (1, plan), (2, plan), (3, plan)]:
            trial = OUT / "trials" / f"r{trial_id:04d}"
            if (trial / "result.json").exists():
                result = json.loads((trial / "result.json").read_text())
                assert result.get("plan") == faults
            elif trial.exists():
                raise ValueError(f"incomplete trial requires review: {trial}")
            else:
                result = campaign._run_trial(config, OUT, trial_id, faults,
                                             lambda pid: None, None)
            print(json.dumps({
                "trial": trial_id,
                "fault_applied": result["feedback"].get("all_faults_applied"),
                "target_exception_candidate": result["feedback"].get(
                    "target_exception_candidate"),
                "junit_status": result.get("junit_validation", {}).get("status"),
                "feedback_status": result["feedback"].get("status"),
                "site_catalog_valid": result.get("site_catalog_validation", {}).get("valid"),
            }, sort_keys=True), flush=True)
    finally:
        for handle in reversed(handles):
            handle.close()


if __name__ == "__main__":
    main()
