#!/usr/bin/env python3
"""Exclude cross-region supplemental plans at a complete trial boundary."""

from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import campaign


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
REMOTE_CASE = "/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def queue_sha(entries):
    return sha(json.dumps(entries, sort_keys=True).encode())


def remote_log(trial_id):
    number = int(trial_id[1:])
    if number <= 47:
        suffix = "upstream-archive-node0-s047/logs"
    elif number <= 80:
        suffix = "archived-upstream/s048-s080"
    elif number <= 106:
        suffix = "upstream-archive-node0-s106/logs"
    elif number <= 112:
        suffix = "archive-node0-older-noncandidate-20261007/work-upstream/logs"
    else:
        raise FileNotFoundError(trial_id)
    path = REMOTE_CASE + "/" + suffix + "/" + trial_id + ".log.gz"
    return subprocess.run(SSH + ["cat", path], check=True,
                          stdout=subprocess.PIPE).stdout


def trace_for(trial):
    path = CASE / trial["log"]
    data = path.read_bytes() if path.exists() else remote_log(trial["id"])
    assert sha(data) == trial["compressed_log_sha256"], trial["id"]
    assert sha(gzip.decompress(data)) == trial["raw_log_sha256"], trial["id"]
    if path.exists():
        trace = campaign.parse_log(path)
    else:
        with tempfile.TemporaryDirectory(prefix="hbase32-v10-log-") as temporary:
            temporary_path = Path(temporary) / (trial["id"] + ".log.gz")
            temporary_path.write_bytes(data)
            trace = campaign.parse_log(temporary_path)
    assert campaign.strict(trace, trial["plan"]) == trial["strict"], trial["id"]
    assert trace["junit"] == trial["junit"], trial["id"]
    assert campaign.target_outcome(trace, trial["plan"])["b7"] or not trial["effective"], trial["id"]
    return trace


def main():
    assert campaign.PAUSE_AFTER_CHECKPOINT.exists()
    assert not campaign.INFLIGHT.exists()
    checkpoint = campaign.CHECKPOINT.read_bytes()
    state = json.loads(checkpoint)
    assert state["version"] == 9
    assert len(state["trials"]) == 125
    assert sum(t["effective"] for t in state["trials"]) == 29
    assert len(state["queue"]) == 8040
    assert len(state["seen_plans"]) == 8124
    before = {
        "checkpoint_sha256": sha(checkpoint), "queue_sha256": queue_sha(state["queue"]),
        "seen_sha256": queue_sha(state["seen_plans"]),
        "coverage_union_sha256": queue_sha(state["coverage_union"]),
        "io_union_sha256": queue_sha(state["io_union"]),
        "trials": len(state["trials"]), "effective": sum(t["effective"] for t in state["trials"]),
        "queue": len(state["queue"]), "seen": len(state["seen_plans"]),
        "coverage_execs": len(state["coverage_execs"]), "io_union": len(state["io_union"]),
    }
    observed = {}
    wrong = []
    for trial in state["trials"]:
        if not trial["coverage_admitted"]:
            continue
        trace = trace_for(trial)
        valid_actor = (campaign.same_plan_actor(trial["plan"])
                       and campaign.same_observed_actor(trace))
        if not valid_actor:
            wrong.append(trial["id"])
        observed[trial["id"]] = {selector for _, selector in campaign.selector_events(trace)}
    assert set(wrong) == {"s120", "s121"}, wrong
    # Verify the archived raw traces reconstruct the old feedback exactly.
    full_io = set(state["healthy_selectors"])
    for trial in state["trials"]:
        if trial["coverage_admitted"]:
            full_io.update(observed[trial["id"]])
    assert full_io == set(state["io_union"]), (len(full_io), len(state["io_union"]))
    backup = HERE / "evidence-v10-pre-checkpoint.json.gz"
    with gzip.open(backup, "wb") as output:
        output.write(checkpoint)
    old_trials = {"s120": next(t for t in state["trials"] if t["id"] == "s120").copy(),
                  "s121": next(t for t in state["trials"] if t["id"] == "s121").copy()}
    for trial in state["trials"]:
        if trial["id"] in wrong:
            trial.update({"invalid_actor": True, "effective": False,
                          "coverage_admitted": False, "new_branches_methods": 0,
                          "new_io_selectors": 0,
                          "disposition": "cross_actor_upstream_prefix_excluded"})
        else:
            trial["invalid_actor"] = False
    excluded_execs = {trial_id + ".exec" for trial_id in wrong}
    state["coverage_execs"] = [path for path in state["coverage_execs"]
                              if Path(path).name not in excluded_execs]
    assert len(state["coverage_execs"]) == before["coverage_execs"] - len(wrong)
    state["coverage_union"] = campaign.coverage([Path(p) for p in state["coverage_execs"]])
    new_io = set(state["healthy_selectors"])
    changed_novelty = {}
    for trial in state["trials"]:
        if trial["coverage_admitted"]:
            selectors = observed[trial["id"]]
            old = trial["new_io_selectors"]
            trial["new_io_selectors"] = len(selectors - new_io)
            new_io.update(selectors)
            if trial["new_io_selectors"] != old:
                changed_novelty[trial["id"]] = {"before": old, "after": trial["new_io_selectors"]}
    state["io_union"] = sorted(new_io)
    original_queue = state["queue"]
    state["queue"] = [entry for entry in original_queue
                      if campaign.same_plan_actor(entry["plan"])]
    # Existing children of a retained parent carry its updated feedback.
    parent_novelty = {tuple(trial["plan"]): trial["new_io_selectors"]
                      for trial in state["trials"] if trial["coverage_admitted"]}
    for entry in state["queue"]:
        prefix = tuple(entry["plan"][:-1])
        if prefix in parent_novelty:
            entry["parent_io_novelty"] = parent_novelty[prefix]
    assert all(campaign.same_plan_actor(entry["plan"]) for entry in state["queue"])
    assert len({";".join(entry["plan"]) for entry in state["queue"]}) == len(state["queue"])
    assert all(";".join(trial["plan"]) in state["seen_plans"] for trial in state["trials"])
    assert not any(entry["plan"][:5] == old_trials["s120"]["plan"]
                   for entry in state["queue"])
    state["version"] = 10
    state["selection_policy"] = "upstream_v10_same_raw_actor"
    state.setdefault("migration_log", []).append({
        "at_utc": datetime.now(timezone.utc).isoformat(), "to_version": 10,
        "reason": "reject_cross_raw_region_upstream_prefixes",
        "excluded_feedback_trials": wrong, "removed_queue_entries": len(original_queue) - len(state["queue"]),
        "tested_plans_retained": len(state["trials"]),
    })
    campaign.publish(state, "paused_same_actor_migration_complete")
    after_bytes = campaign.CHECKPOINT.read_bytes()
    after = {
        "checkpoint_sha256": sha(after_bytes), "queue_sha256": queue_sha(state["queue"]),
        "seen_sha256": queue_sha(state["seen_plans"]),
        "coverage_union_sha256": queue_sha(state["coverage_union"]),
        "io_union_sha256": queue_sha(state["io_union"]),
        "trials": len(state["trials"]), "effective": sum(t["effective"] for t in state["trials"]),
        "queue": len(state["queue"]), "seen": len(state["seen_plans"]),
        "coverage_execs": len(state["coverage_execs"]), "io_union": len(state["io_union"]),
    }
    audit = {"at_utc": datetime.now(timezone.utc).isoformat(),
             "pre": before, "post": after, "backup_sha256": campaign.sha256(backup),
             "excluded_trial_records_before": old_trials,
             "changed_io_novelty": changed_novelty,
             "remote_log_sha256_verified": len(observed),
             "exact_trial_ids_preserved": [trial["id"] for trial in state["trials"]],
             "seen_plan_sha_unchanged": before["seen_sha256"] == after["seen_sha256"],
             "no_replay": True}
    campaign.atomic_json(HERE / "evidence-v10-same-actor-migration.json", audit)
    print("MIGRATED", json.dumps({"pre": before, "post": after,
                                  "changed_novelty": changed_novelty}, sort_keys=True))


if __name__ == "__main__":
    main()
