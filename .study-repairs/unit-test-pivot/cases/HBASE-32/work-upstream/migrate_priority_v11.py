#!/usr/bin/env python3
"""Change only HBASE-32 supplemental selection weights at a safe checkpoint."""

from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import campaign


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "campaign.py"
SOURCE_IN_GIT = ".study-repairs/unit-test-pivot/cases/HBASE-32/work-upstream/campaign.py"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def main():
    assert campaign.PAUSE_AFTER_CHECKPOINT.exists()
    assert not campaign.INFLIGHT.exists()
    data = campaign.CHECKPOINT.read_bytes()
    state = json.loads(data)
    assert (state["version"], len(state["trials"]),
            sum(t["effective"] for t in state["trials"]),
            len(state["queue"]), len(state["seen_plans"])) == (10, 146, 34, 5270, 8200)
    assert digest(data) == "c037934a83de12253700c47977fa0980e93c1df0bfa6fe26b857ea8c367c15e9"
    before = {"checkpoint_sha256": digest(data),
              "queue_sha256": digest(encoded(state["queue"])),
              "seen_sha256": digest(encoded(state["seen_plans"])),
              "coverage_sha256": digest(encoded(state["coverage_union"])),
              "io_sha256": digest(encoded(state["io_union"])),
              "trials": len(state["trials"]), "queue": len(state["queue"]),
              "seen": len(state["seen_plans"]),
              "effective": sum(t["effective"] for t in state["trials"])}
    window = state["trials"][125:]
    histogram = {}
    for depth in sorted({len(t["plan"]) for t in window}):
        members = [t for t in window if len(t["plan"]) == depth]
        histogram[str(depth)] = {"attempts": len(members),
                                 "effective": sum(t["effective"] for t in members),
                                 "dispositions": dict(Counter(t["disposition"] for t in members))}
    assert sum(x["attempts"] for x in histogram.values()) == 21
    old_source = subprocess.run(["git", "show", "HEAD:" + SOURCE_IN_GIT],
                                capture_output=True, check=True).stdout
    backup = HERE / "evidence-v11-pre-checkpoint.json.gz"
    with gzip.open(backup, "wb") as output:
        output.write(data)
    state["version"] = 11
    state["selection_policy"] = "upstream_v11_depth_retention"
    state.setdefault("migration_log", []).append({
        "at_utc": datetime.now(timezone.utc).isoformat(), "to_version": 11,
        "reason": "prefer_short_same_actor_terminal_RPC_outside_mandatory_depth_round",
        "depth_round_every": 10, "depth_penalty_per_fault_above_three": 10,
        "attempts_unchanged": len(state["trials"]),
        "effective_unchanged": sum(t["effective"] for t in state["trials"]),
        "queue_unchanged": len(state["queue"]),
        "seen_unchanged": len(state["seen_plans"]),
    })
    campaign.publish(state, "paused_priority_v11_migration_complete")
    after = {"checkpoint_sha256": digest(campaign.CHECKPOINT.read_bytes()),
             "queue_sha256": digest(encoded(state["queue"])),
             "seen_sha256": digest(encoded(state["seen_plans"])),
             "coverage_sha256": digest(encoded(state["coverage_union"])),
             "io_sha256": digest(encoded(state["io_union"])),
             "trials": len(state["trials"]), "queue": len(state["queue"]),
             "seen": len(state["seen_plans"]),
             "effective": sum(t["effective"] for t in state["trials"])}
    for key in ("queue_sha256", "seen_sha256", "coverage_sha256", "io_sha256",
                "trials", "queue", "seen", "effective"):
        assert before[key] == after[key], key
    campaign.atomic_json(HERE / "evidence-v11-depth-priority-migration.json", {
        "at_utc": datetime.now(timezone.utc).isoformat(), "pre": before, "post": after,
        "recent_v10_depth_outcomes": histogram,
        "old_controller_sha256": digest(old_source),
        "new_controller_sha256": campaign.sha256(SOURCE),
        "backup_sha256": campaign.sha256(backup),
        "no_completed_plan_rerun": True,
        "feedback_and_queue_unchanged": True,
        "depth_round_preserved": True,
    })
    print("V11_MIGRATED", before["checkpoint_sha256"], after["checkpoint_sha256"],
          before["effective"], before["queue"])


if __name__ == "__main__":
    main()
