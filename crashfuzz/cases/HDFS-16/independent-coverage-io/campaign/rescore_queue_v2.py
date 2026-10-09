#!/usr/bin/env python3
"""One-time HDFS-16 queue migration after trial 12; no trial is rerun."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

import run_campaign as campaign


DIRECTORY = Path(__file__).resolve().parent
SNAPSHOT = DIRECTORY / "checkpoint-before-priority-v2.json"
REPORT = DIRECTORY / "priority-migration-v2.json"


def main() -> None:
    if REPORT.is_file():
        print(REPORT.read_text())
        return
    state = json.loads(campaign.STATE.read_text())
    before = json.loads(SNAPSHOT.read_text())
    assert len(state["completed"]) == len(before["completed"]) == 12
    assert state["completed"] == before["completed"]
    assert state["current"] == before["current"]
    assert len(state["queue"]) == len(before["queue"])
    assert [entry["sequence_id"] for entry in state["queue"]] == [
        entry["sequence_id"] for entry in before["queue"]]
    parents = {row["trial"]: row for row in state["completed"]}
    healthy_points = {campaign.point_id(row) for row in
                      campaign.events(campaign.TRACE) if campaign.relevant(row)}
    changed = 0
    old_scores = Counter()
    new_scores = Counter()
    for entry in state["queue"]:
        old = entry["priority"]
        old_scores[old] += 1
        match = re.match(r"mutated (trial-\d+) from", entry["reason"])
        if match:
            parent = parents[match.group(1)]
            entry["priority"] = campaign.mutation_priority(
                parent, entry["sequence"], healthy_points)
        else:
            entry["priority"] = campaign.base_priority(entry["sequence"][-1])
            if entry["sequence"][-1]["exception"] == "IOException":
                entry["priority"] += 3
        new_scores[entry["priority"]] += 1
        changed += entry["priority"] != old
    campaign.atomic_json(campaign.STATE, state)
    report = {"case_id": "HDFS-16", "completed_trials_untouched": 12,
              "current_trial_untouched": 13, "queue_entries": len(state["queue"]),
              "changed_priorities": changed,
              "old_score_range": [min(old_scores), max(old_scores)],
              "new_score_range": [min(new_scores), max(new_scores)],
              "reason": "Depth-four trial 11 timed out after only 3/4 faults; "
                        "new policy scores production method/branch and "
                        "stable I/O-family novelty, penalizes slow parents "
                        "and repeated edit-log fault families, and samples "
                        "at most two I/O points per family per mutation.",
              "snapshot": SNAPSHOT.name}
    campaign.atomic_json(REPORT, report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
