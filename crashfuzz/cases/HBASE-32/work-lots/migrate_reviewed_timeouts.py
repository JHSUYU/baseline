#!/usr/bin/env python3
"""Remove five reviewed historical timeouts from accepted fuzz feedback."""

import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import campaign


BAD_IDS = ("r003", "r011", "r058", "r066", "r075")
HERE = Path(__file__).resolve().parent
PRE_BACKUP = HERE / "evidence-reviewed-timeouts-pre-checkpoint.json.gz"
PRE = HERE / "evidence-reviewed-timeouts-pre.json"
POST = HERE / "evidence-reviewed-timeouts-post.json"


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha_json(value):
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def main():
    raw = campaign.CHECKPOINT.read_bytes()
    state = json.loads(raw)
    if any(entry.get("reason") == "exclude_five_reviewed_historical_timeouts"
           for entry in state.get("migration_log", [])):
        raise SystemExit("Migration already present; no old trial will be rerun")
    assert not campaign.INFLIGHT.exists()
    assert len(state["trials"]) == 177
    assert sum(bool(t["effective"]) for t in state["trials"]) == 128
    reviewed = json.loads(campaign.REVIEW_VERDICTS.read_text())
    by_id = {trial["id"]: trial for trial in state["trials"]}
    assert len(by_id) == len(state["trials"])
    for trial_id in BAD_IDS:
        trial = by_id[trial_id]
        assert reviewed[trial_id]["classification"] == "unreproduced_timeout_candidate"
        assert (trial["effective"] and trial["coverage_admitted"]
                and trial["review_candidate"] and trial["junit_exit"] == 124)
        assert not any(len(other["plan"]) > len(trial["plan"])
                       and other["plan"][:len(trial["plan"])] == trial["plan"]
                       for other in state["trials"] + state["queue"])
    assert not PRE_BACKUP.exists() and not PRE.exists() and not POST.exists()
    PRE_BACKUP.write_bytes(gzip.compress(raw, compresslevel=9))
    old_queue_hash = sha_json(state["queue"])
    old_seen_hash = sha_json(state["seen_plans"])
    old_union_hash = sha_json(state["related_io_union"])
    old_coverage_hash = sha_json(state["coverage_union"])
    campaign.atomic_json(PRE, {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": sha_bytes(raw),
        "checkpoint_backup_sha256": sha_bytes(PRE_BACKUP.read_bytes()),
        "trial_count": len(state["trials"]), "effective_count": 128,
        "coverage_exec_count": len(state["coverage_execs"]),
        "queue_count": len(state["queue"]), "queue_sha256": old_queue_hash,
        "seen_count": len(state["seen_plans"]), "seen_sha256": old_seen_hash,
        "io_union_count": len(state["related_io_union"]),
        "io_union_sha256": old_union_hash,
        "coverage_union_sha256": old_coverage_hash,
        "excluded_trial_ids": list(BAD_IDS),
    })

    for trial_id in BAD_IDS:
        trial = by_id[trial_id]
        trial["effective"] = False
        trial["coverage_admitted"] = False
        trial["pending_replay"] = False
        trial["disposition"] = "timeout_unreproduced_after_exact_replay"
        trial["new_production_branches_and_methods"] = 0
        trial["new_related_io_selectors"] = 0
        trial["global_new_related_io_selectors"] = 0

    accepted = [trial for trial in state["trials"] if trial["effective"]]
    execs = [str(HERE / "logs" / "actor-healthy.exec")]
    execs.extend(str(HERE / "logs" / (trial["id"] + ".exec")) for trial in accepted)
    assert execs == [path for path in state["coverage_execs"]
                     if not any(path.endswith("/" + trial_id + ".exec")
                                for trial_id in BAD_IDS)]
    state["coverage_execs"] = execs
    state["coverage_union"] = campaign.coverage([Path(path) for path in execs])

    seen = {event["selector"] for event in state["healthy"]["io"]}
    for trial in state["trials"]:
        if trial["effective"]:
            trace = campaign.parse_log(campaign.CASE / trial["log"])
            observed = campaign.related_selectors(trace)
            trial["global_new_related_io_selectors"] = len(observed - seen)
            seen.update(observed)
        else:
            trial["global_new_related_io_selectors"] = 0
    state["related_io_union"] = sorted(seen)

    assert sum(bool(t["effective"]) for t in state["trials"]) == 123
    assert len(state["coverage_execs"]) == 124
    assert sha_json(state["queue"]) == old_queue_hash
    assert sha_json(state["seen_plans"]) == old_seen_hash
    assert len(state["trials"]) == 177
    state.setdefault("migration_log", []).append({
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "exclude_five_reviewed_historical_timeouts",
        "excluded_trial_ids": list(BAD_IDS),
        "effective_before": 128, "effective_after": 123,
        "coverage_exec_count_before": 129,
        "coverage_exec_count_after": len(state["coverage_execs"]),
        "queue_sha256_unchanged": old_queue_hash,
        "seen_sha256_unchanged": old_seen_hash,
        "old_coverage_union_sha256": old_coverage_hash,
        "new_coverage_union_sha256": sha_json(state["coverage_union"]),
        "old_io_union_sha256": old_union_hash,
        "new_io_union_sha256": sha_json(state["related_io_union"]),
    })
    campaign.publish(state, status="running_coverage_io_campaign")
    written = json.loads(campaign.CHECKPOINT.read_text())
    result = json.loads((campaign.CASE / "result.json").read_text())
    assert sum(bool(t["effective"]) for t in written["trials"]) == 123
    assert result["current_campaign"]["effective_trials"] == 123
    assert result["bug_mark"] == "none"
    campaign.atomic_json(POST, {
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": sha_bytes(campaign.CHECKPOINT.read_bytes()),
        "trial_count": len(written["trials"]), "effective_count": 123,
        "coverage_exec_count": len(written["coverage_execs"]),
        "queue_count": len(written["queue"]),
        "queue_sha256": sha_json(written["queue"]),
        "seen_count": len(written["seen_plans"]),
        "seen_sha256": sha_json(written["seen_plans"]),
        "io_union_count": len(written["related_io_union"]),
        "io_union_sha256": sha_json(written["related_io_union"]),
        "coverage_union_sha256": sha_json(written["coverage_union"]),
        "result_status": result["status"],
        "result_effective_count": result["current_campaign"]["effective_trials"],
        "result_bug_mark": result["bug_mark"],
        "excluded_trial_ids": list(BAD_IDS),
        "no_older_trial_rerun": True,
    })
    print("MIGRATED reviewed timeouts: 177 trials, 123 effective,",
          len(written["queue"]), "queued plans", flush=True)


if __name__ == "__main__":
    main()
