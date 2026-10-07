#!/usr/bin/env python3
"""One-time atomic migration of a pre-v6 anomalous trial into pending review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

import campaign


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    trial_id = sys.argv[1]
    state = json.loads(campaign.CHECKPOINT.read_text())
    trial = next(item for item in state["trials"] if item["id"] == trial_id)
    if trial is not state["trials"][-1] or not trial["timed_out"]:
        raise RuntimeError("migration requires the last completed timeout trial")
    if not (trial["strict"] and trial["target_after_fault"] and trial["review_candidate"]):
        raise RuntimeError("not a strict, target-retaining review candidate")
    if not trial["effective"] or not trial["coverage_admitted"]:
        raise RuntimeError("trial was already excluded")
    raw = campaign.HERE / "logs" / f"{trial_id}.log"
    exit_file = campaign.HERE / "logs" / f"{trial_id}.exit"
    exec_file = campaign.HERE / "logs" / f"{trial_id}.exec"
    if exit_file.read_text().strip() != "124" or not raw.is_file():
        raise RuntimeError("missing complete timeout receipt")

    pre = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": digest(campaign.CHECKPOINT),
        "result_sha256": digest(campaign.CASE / "result.json"),
        "trial_id": trial_id,
        "plan_sha256": hashlib.sha256(";".join(trial["plan"]).encode()).hexdigest(),
        "raw_log_sha256": digest(raw),
        "exit_sha256": digest(exit_file),
        "jacoco_sha256": digest(exec_file),
        "trials": len(state["trials"]),
        "effective": sum(item["effective"] for item in state["trials"]),
        "queue": len(state["queue"]),
        "coverage_execs": len(state["coverage_execs"]),
        "related_io_union_size": len(state["related_io_union"]),
        "inflight": json.loads(campaign.INFLIGHT.read_text()),
    }
    campaign.atomic_json(campaign.HERE / "evidence-r123-pending-pre.json", pre)

    trial.update({
        "effective": False,
        "coverage_admitted": False,
        "pending_replay": True,
        "new_production_branches_and_methods": 0,
        "new_related_io_selectors": 0,
        "global_new_related_io_selectors": 0,
        "disposition": "timeout_pending_exact_replay",
    })
    state["coverage_execs"] = [path for path in state["coverage_execs"]
                              if Path(path).name != f"{trial_id}.exec"]
    state["coverage_union"] = campaign.coverage([Path(path)
                                                  for path in state["coverage_execs"]])
    related = {event["selector"] for event in state["healthy"]["io"]}
    for item in state["trials"]:
        if item["effective"]:
            related.update(campaign.related_selectors(
                campaign.parse_log(campaign.CASE / item["log"])))
    state["related_io_union"] = sorted(related)
    campaign.prune_queue(state)
    state.setdefault("migration_log", []).append({
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "pending exact replay cannot be effective or drive feedback",
        "trial_id": trial_id,
        "prior_checkpoint_sha256": pre["checkpoint_sha256"],
        "raw_log_sha256": pre["raw_log_sha256"],
    })
    campaign.publish(state)
    post = {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": digest(campaign.CHECKPOINT),
        "result_sha256": digest(campaign.CASE / "result.json"),
        "trial_id": trial_id,
        "plan_sha256": hashlib.sha256(";".join(trial["plan"]).encode()).hexdigest(),
        "raw_log_sha256": digest(raw),
        "exit_sha256": digest(exit_file),
        "jacoco_sha256": digest(exec_file),
        "trials": len(state["trials"]),
        "effective": sum(item["effective"] for item in state["trials"]),
        "queue": len(state["queue"]),
        "coverage_execs": len(state["coverage_execs"]),
        "related_io_union_size": len(state["related_io_union"]),
        "inflight": json.loads(campaign.INFLIGHT.read_text()),
        "migrated_trial": {key: trial[key] for key in (
            "id", "strict", "target_after_fault", "exact_b7_after_fault",
            "effective", "coverage_admitted", "pending_replay", "disposition")},
    }
    campaign.atomic_json(campaign.HERE / "evidence-r123-pending-post.json", post)
    assert pre["plan_sha256"] == post["plan_sha256"]
    assert pre["raw_log_sha256"] == post["raw_log_sha256"]
    assert pre["exit_sha256"] == post["exit_sha256"]
    assert pre["jacoco_sha256"] == post["jacoco_sha256"]
    assert pre["trials"] == post["trials"]
    assert pre["effective"] == post["effective"] + 1
    assert pre["queue"] == post["queue"]
    assert pre["inflight"] == post["inflight"]
    print(json.dumps(post, sort_keys=True))


if __name__ == "__main__":
    main()
