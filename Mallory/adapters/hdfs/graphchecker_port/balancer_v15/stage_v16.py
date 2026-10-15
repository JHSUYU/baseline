"""Stage an independent K8/max12 campaign with global strict-depth quota."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


OLD_ROOT = Path("/dev/shm/mallory-hdfs-balancer-v15b-node0")
OLD_CONFIG = OLD_ROOT / "inputs/campaign-config-v15c.json"
OLD_CONFIG_SHA = "d672b5136f381b532345f8985b8dcbde831683e26b2a37cda2134b14d617537a"
ROOT = Path("/dev/shm/mallory-hdfs-balancer-v16-node0")
CASE = "HDFS-11-TIMING-MONITOR-K8-DEPTH-V16"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    if ROOT.exists() or sha(OLD_CONFIG) != OLD_CONFIG_SHA:
        raise ValueError("V16 root exists or V15c input config changed")
    old = OLD_ROOT / "formal-v15c"
    state = json.loads((old / "checkpoint.json").read_text())
    if (state["completed_fault_trials"] != 4 or state["active"] is not None or
            state["status"] != "bounded_checkpoint_stop" or
            len(state["multi_anchor_addresses"]) != 8):
        raise ValueError("V15c four-trial predecessor is not sealed")
    archives = Path("/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-v15c-pilot")
    for index in range(5):
        archive = archives / f"raw-r{index:04d}.tar.gz"
        receipt = json.loads((archives / f"raw-r{index:04d}-receipt.json").read_text())
        if (receipt["archive_sha256"] != sha(archive) or
                receipt["verified_against_source"] is not True or
                receipt["result_sha256"] != sha(
                    old / f"trials/r{index:04d}/result.json")):
            raise ValueError(f"V15c raw archive {index} failed pin verification")
    config = json.loads(OLD_CONFIG.read_text())
    if (config["recording"]["multi_target_max_anchors"] != 8 or
            config["budget"]["max_faults_per_trial"] != 12 or
            config["junit"] != {"class":
                "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer",
                "method": "testEncryptedBalancer0"}):
        raise ValueError("V15c identity differs from expected original JUnit")
    config["case_id"] = CASE
    config["budget"]["fault_trials"] = 256
    config["budget"]["seconds"] = 28800
    config["recording"]["target_name"] = "HDFS11TIMINGMONITORK8DEPTHV16"
    config["recording"]["cross_anchor_strict_depth_policy"] = "global_quarter_v1"
    config["runner"]["local_artifact_root"] = str(ROOT / "raw")
    config["runner"]["local_work_root"] = str(ROOT / "work")
    from Mallory.native_graphchecker_campaign import campaign
    campaign._validate_config(config)
    ROOT.mkdir()
    (ROOT / "raw").mkdir()
    (ROOT / "work").mkdir()
    (ROOT / "formal").mkdir()
    path = ROOT / "campaign-config-v16.json"
    path.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n")
    source = Path(campaign.__file__).resolve(strict=True)
    receipt = {"config_sha256": sha(path), "campaign_source_sha256": sha(source),
               "v16_commit": "f0082b2a2e51b3bc245b971bf808313168cd6a2b",
               "predecessor_config_sha256": OLD_CONFIG_SHA,
               "predecessor_checkpoint_sha256": sha(old / "checkpoint.json"),
               "predecessor_completed_fault_trials": 4,
               "imported_fault_trials": 0, "new_healthy_graph_required": True,
               "source_overlay_pin_sha256": sha(OLD_ROOT /
                    "inputs/combined-overlay-pin-v15.json"),
               "weave_receipt_sha256": sha(OLD_ROOT /
                    "woven/native-original-weave-receipt.json"),
               "static_map_sha256": sha(OLD_ROOT /
                    "static-scope/static_scope_map.jsonl"),
               "manual_fault_site_overrides": 0}
    (ROOT / "stage-receipt-v16.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
