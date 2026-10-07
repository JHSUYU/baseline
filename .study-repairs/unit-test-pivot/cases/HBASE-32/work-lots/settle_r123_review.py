#!/usr/bin/env python3
"""Record the isolated exact replay verdict for the r123 timeout candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import campaign


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = campaign.HERE / "logs/r123.log"
    replay = campaign.HERE / "logs/replay-r123.log"
    summary = json.loads((campaign.HERE / "logs/replay-r123.summary.json").read_text())
    spec = json.loads((campaign.HERE / "replay-r123-plan.json").read_text())
    state = json.loads(campaign.CHECKPOINT.read_text())
    trial = next(item for item in state["trials"] if item["id"] == "r123")
    if trial["effective"] or trial["coverage_admitted"] or not trial["pending_replay"]:
        raise RuntimeError("r123 is not quarantined for pending review")
    if trial["plan"] != spec["plan"] or summary["plan"] != spec["plan"]:
        raise RuntimeError("source/replay plan mismatch")
    if sha256(source) != spec["source_log_sha256"]:
        raise RuntimeError("original raw log changed")
    if sha256(replay) != summary["log_sha256"]:
        raise RuntimeError("replay raw log changed")
    original_trace = campaign.parse_log(source)
    replay_trace = campaign.parse_log(replay)
    original_strict = campaign.strict_trace(original_trace, spec["plan"])
    replay_strict = campaign.strict_trace(replay_trace, spec["plan"])
    original_guard, original_b7 = campaign.related_after_fault(original_trace, original_strict)
    replay_guard, replay_b7 = campaign.related_after_fault(replay_trace, replay_strict)
    if not (original_strict and replay_strict and original_guard and original_b7
            and replay_guard and replay_b7):
        raise RuntimeError("exact fault or same-actor target did not reproduce")
    if (summary["exit"] != 0 or
            summary["junit"] != {"found": 1, "succeeded": 1, "failed": 0} or
            summary["create_table_child_success_count"] != 600 or
            len(summary["pre_shutdown_aborted_region_servers"]) != 1 or
            summary["first_scheduled_server_crash_procedure"] is None):
        raise RuntimeError("replay did not demonstrate successful recovery")
    original_tar = campaign.CASE / "evidence/hbase32-r123-original-node1.tar.gz"
    replay_tar = campaign.CASE / "evidence/hbase32-r123-node1-exact-replay.tar.gz"
    verdict = {
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "unreproduced_timeout_candidate",
        "new_bug_confirmed": False,
        "source_trial": "r123",
        "source_elapsed_seconds": original_trace["elapsed_seconds"],
        "source_junit": original_trace["junit"],
        "source_exit": int((campaign.HERE / "logs/r123.exit").read_text().strip()),
        "source_exact_fault": original_strict,
        "source_same_actor_guard": len(original_guard),
        "source_same_actor_b7": len(original_b7),
        "source_pre_shutdown_rs_abort_count": len(trial["aborted_region_servers"]),
        "source_log_sha256": sha256(source),
        "source_jacoco_sha256": sha256(campaign.HERE / "logs/r123.exec"),
        "source_archive_sha256": sha256(original_tar),
        "plan_sha256": hashlib.sha256(";".join(spec["plan"]).encode()).hexdigest(),
        "agent_class_sha256": summary["agent_class_sha256"],
        "hbase_server_jar_sha256": summary["hbase_server_jar_sha256"],
        "replay_timeout_seconds": spec["timeout_seconds"],
        "replay_exit": summary["exit"],
        "replay_elapsed_seconds": summary["elapsed_seconds"],
        "replay_junit": summary["junit"],
        "replay_exact_fault": replay_strict,
        "replay_same_actor_guard": len(replay_guard),
        "replay_same_actor_b7": len(replay_b7),
        "replay_pre_shutdown_rs_abort_count": len(summary["pre_shutdown_aborted_region_servers"]),
        "replay_scp": summary["first_scheduled_server_crash_procedure"],
        "replay_create_table_child_success_count": summary["create_table_child_success_count"],
        "replay_log_sha256": sha256(replay),
        "replay_jacoco_sha256": summary["exec_sha256"],
        "replay_archive_sha256": sha256(replay_tar),
        "interpretation": (
            "The selected flush RPC exception and same raw-region/actor B7 rethrow "
            "recurred; the isolated unchanged JUnit completed all 600 table-assignment "
            "children and passed. One RegionServer abort followed the handler's documented "
            "IOException behavior. The original timeout remains a scheduling-sensitive "
            "observation; no stable hang or new coordination bug is confirmed."
        ),
    }
    evidence_path = campaign.CASE / "evidence/r123-replay-verdict.json"
    campaign.atomic_json(evidence_path, verdict)
    previous = {
        "checkpoint_sha256": sha256(campaign.CHECKPOINT),
        "attempts": len(state["trials"]),
        "effective": sum(item["effective"] for item in state["trials"]),
        "queue": len(state["queue"]),
        "inflight": json.loads(campaign.INFLIGHT.read_text()),
    }
    reviewed = json.loads(campaign.REVIEW_VERDICTS.read_text())
    reviewed["r123"] = {
        "classification": "unreproduced_timeout_candidate",
        "evidence": "evidence/r123-replay-verdict.json",
        "reason": "exact 600-second isolated replay passed original JUnit in 79.72 seconds with 600 of 600 child assignments",
    }
    campaign.atomic_json(campaign.REVIEW_VERDICTS, reviewed)
    trial["pending_replay"] = False
    trial["disposition"] = "timeout_unreproduced_after_exact_replay"
    state.setdefault("migration_log", []).append({
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": "settle r123 same-plan exact replay as unreproduced timeout candidate",
        "trial_id": "r123",
        "evidence_sha256": sha256(evidence_path),
        "prior_checkpoint_sha256": previous["checkpoint_sha256"],
    })
    campaign.publish(state)
    current = {
        "checkpoint_sha256": sha256(campaign.CHECKPOINT),
        "attempts": len(state["trials"]),
        "effective": sum(item["effective"] for item in state["trials"]),
        "queue": len(state["queue"]),
        "inflight": json.loads(campaign.INFLIGHT.read_text()),
    }
    if any(previous[key] != current[key] for key in ("attempts", "effective", "queue", "inflight")):
        raise RuntimeError("review changed campaign progress")
    campaign.atomic_json(campaign.CASE / "evidence/r123-review-checkpoint-audit.json",
                         {"before": previous, "after": current,
                          "verdict_sha256": sha256(evidence_path)})
    print(json.dumps({"verdict": verdict["classification"], "before": previous,
                      "after": current}, sort_keys=True))


if __name__ == "__main__":
    main()
