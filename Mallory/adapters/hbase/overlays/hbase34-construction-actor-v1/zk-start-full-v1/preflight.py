#!/usr/bin/env python3
"""Read-only source, artifact, sealed-seed, and full-config checks."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from healthy_gate import require, sha, verify_pair

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V6 = HERE.parent
ARCHIVE = ROOT / "data/mallory/healthy_observations/HBASE-34-construction-healthy-v6"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
ZK = SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/ZKSecretWatcher.java"
MANAGER = SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java"
PINNED_V6_RESULT = "4a51877ee767a7e08cb4da2f1fd754c51d374fa64db6f98b9f69f21f8a47302c"
PINNED_V6_TRACE = "57b52c554ab865bb64246b00e1cf463216ef06a65e7e28c8ac67dd2961453b79"
PINNED_ZK_SOURCE = "0f721f46c26ade96e120029da1e4370bc167ee7107f35b1fa11370ef76b3d008"
PINNED_MANAGER_SOURCE = "457a036cbbaaa6a1b0d66d2f4e35913933e431ef70409bbcaff7f2e59c43d51f"


def main() -> None:
    config = json.loads((HERE / "config.json").read_text())
    healthy = json.loads((V6 / "healthy-v6.json").read_text())
    require(sha(ARCHIVE / "result.json") == PINNED_V6_RESULT and
            sha(ARCHIVE / "trials/r0000/events.jsonl.gz") == PINNED_V6_TRACE,
            "sealed v6 healthy evidence changed")
    verdict = verify_pair(ARCHIVE)
    require(verdict["state_edge_certainty"] == "candidate" and
            {x["site"].split("@")[-1] for x in verdict["allowed_points"]} ==
            {"61:door:1", "63:door:2"},
            "v6 sampled state witness or typed doors changed")
    allowed = {"revision", "candidate_status", "mapping", "healthy_admission",
               "budget", "calibration_only", "auto_promote_if_healthy",
               "explore_outside_closure", "require_event_time_paths",
               "reject_coarse_roots", "fault_types"}
    require({key: value for key, value in config.items() if key not in allowed} ==
            {key: value for key, value in healthy.items() if key not in allowed},
            "JUnit command, target, sites, or instrumentation changed from v6")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                   "max_faults_per_trial": 3,
                                   "trial_timeout_seconds": 600} and
            config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["explore_outside_closure"] is False and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is False and
            config["fault_types"] == ["EXCEPTION"],
            "full budget or candidate state-edge policy changed")
    require(sha(ZK) == PINNED_ZK_SOURCE and
            sha(MANAGER) == PINNED_MANAGER_SOURCE,
            "HBase source revision changed")
    zk, manager = ZK.read_text(), MANAGER.read_text()
    require("public void start() throws KeeperException" in zk and
            "ZKUtil.watchAndCheckExists(watcher, keysParentZNode)" in zk and
            "ZKUtil.getChildDataAndWatchForNewChildren(watcher, keysParentZNode)" in zk and
            "this.zkWatcher.start();" in manager and
            "} catch (KeeperException ke) {\n      LOG.error(\"ZooKeeper initialization failed\", ke);" in manager and
            "zkWatcher.refreshKeys();" in manager and
            "masterKey = allKeys.get(identifier.getKeyId());" in manager,
            "typed watcher start catch or target refresh source changed")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        require(path.is_file() and sha(path) == row["sha256"],
                f"changed runtime artifact: {path}")
    sys.path.insert(0, str(Path(config["core_release"])))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    print(json.dumps({"case_id": "HBASE-34", "status": "preflight_passed",
                      "source_retention": "feasible_not_proven",
                      "state_edge_certainty": "candidate",
                      "fresh_healthy_gate_required": True,
                      "budget": config["budget"]}, sort_keys=True))


if __name__ == "__main__":
    main()
