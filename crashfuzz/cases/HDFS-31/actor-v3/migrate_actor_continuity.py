#!/usr/bin/env python3
"""Switch only future HDFS31 plans to the versioned pre-UUID actor rule."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path

import campaign


OBSERVED_PREUUID = (
    "535ec888f9d97608d01c",
    "d877cce0ebaf8909bfc2",
    "f1e1d3c9207d03f7ca57",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    path = anchor / "campaign-state.json"
    migration_receipt = anchor / "actor-continuity-v4-migration.json"
    with (anchor / "controller.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if migration_receipt.exists() or sha(path) != args.expected_state_sha256:
            raise RuntimeError("migration already exists or checkpoint SHA changed")
        state = json.loads(path.read_text())
        if (state.get("schema") != "hdfs31-actor-v3-campaign-1"
                or state.get("identity_rule_migration") is not None
                or len(state["completion_order"]) != 21
                or state["effective"] != 16 or state["in_flight"] is not None
                or not (anchor / "pause.request").is_file()
                or any(identity not in state["completion_order"]
                       for identity in OBSERVED_PREUUID)):
            raise RuntimeError("not at the frozen legacy21 boundary")
        if sum(state["completed"][identity]["result"]["valid_for_feedback"]
               for identity in state["completion_order"][:20]) != 15:
            raise RuntimeError("first 20 legacy effective count differs")
        manifest_path = anchor / "legacy21-freeze.manifest.json"
        manifest = json.loads(manifest_path.read_text())
        verified = json.loads((anchor / "legacy21-node1-verified.json").read_text())
        if (manifest["checkpoint_sha256"] != args.expected_state_sha256
                or manifest["completed_ids"] != state["completion_order"]
                or manifest["effective"] != 16
                or verified.get("schema") != "hdfs31-v3-legacy21-cross-host-verified-1"
                or not verified.get("restored_raw")
                or verified["manifest_sha256"] != sha(manifest_path)
                or verified["archive_sha256"] != manifest["archive_sha256"]
                or verified["verified_files"] != len(manifest["files"])):
            raise RuntimeError("frozen cross-host raw evidence not verified")
        old_ids = list(state["completion_order"])
        old_queue = [item["id"] for item in state["queue"]]
        state["identity_rule_migration"] = {
            "old_policy": "legacy-v3",
            "new_policy": "actor-continuity-v4",
            "boundary_completed": 21,
            "legacy_first20_effective": 15,
            "legacy_effective_at_boundary": 16,
            "old_state_sha256": args.expected_state_sha256,
            "legacy_archive_sha256": manifest["archive_sha256"],
            "legacy_archive_manifest_sha256": sha(manifest_path),
            "preuuid_postfault_targets_observed_not_credited": list(OBSERVED_PREUUID),
        }
        campaign.save(path, state)
        after_sha = sha(path)
        if (state["completion_order"] != old_ids
                or [item["id"] for item in state["queue"]] != old_queue
                or state["effective"] != 16 or state["in_flight"] is not None):
            raise RuntimeError("migration changed existing trial accounting")
        campaign.save(migration_receipt, {
            "schema": "hdfs31-actor-v4-boundary-migration-1",
            "before_state_sha256": args.expected_state_sha256,
            "after_state_sha256": after_sha,
            "legacy_completed": 21,
            "legacy_effective": 16,
            "queue_ids_unchanged": old_queue,
            "completed_ids_unchanged": old_ids,
            "new_policy": "actor-continuity-v4",
            "node1_verified_receipt_sha256": sha(anchor / "legacy21-node1-verified.json"),
        })
        print(json.dumps({"before": args.expected_state_sha256, "after": after_sha,
                          "boundary_completed": 21, "legacy_effective": 16}, sort_keys=True))


if __name__ == "__main__":
    main()
