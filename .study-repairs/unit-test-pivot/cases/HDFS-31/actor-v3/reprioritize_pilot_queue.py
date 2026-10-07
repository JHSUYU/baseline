#!/usr/bin/env python3
"""One-time, fail-closed reprioritization of pending HDFS31 pilot plans."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path

import campaign


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    path = anchor / "campaign-state.json"
    receipt_path = anchor / "pilot-queue-reprioritization.json"
    if receipt_path.exists():
        raise RuntimeError("queue migration receipt already exists")
    with (anchor / "controller.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before_sha = digest(path)
        if before_sha != args.expected_state_sha256:
            raise RuntimeError("checkpoint SHA changed")
        state = json.loads(path.read_text())
        if (state.get("schema") != "hdfs31-actor-v3-campaign-1"
                or state.get("in_flight") is not None
                or len(state["completion_order"]) != 2
                or state["effective"] != 1
                or len(state["queue"]) != 16):
            raise RuntimeError("pilot boundary no longer matches")
        old_queue = [dict(item) for item in state["queue"]]
        old_ids = [item["id"] for item in old_queue]
        if len(old_ids) != len(set(old_ids)):
            raise RuntimeError("duplicate pending plan")
        # An ordinal-six fault reached the exact target in only one of the two
        # pilot schedules.  Earlier stable, same-actor NN0 RPC responses have
        # more slack before the original JUnit transfer/guard executes.
        for item in state["queue"]:
            if len(item["sequence"]) != 1:
                continue
            step = item["sequence"][0]
            ordinal = step["hitOrdinal"]
            if step["siteId"] == "Client.getRpcResponse" and 1 <= ordinal < 6:
                item["score"] += 6 * (6 - ordinal)
        if [item["id"] for item in state["queue"]] != old_ids:
            raise RuntimeError("queue identity or order changed")
        state["queue_priority_revision"] = "early-same-actor-nn0-response-after-two-pilots"
        campaign.save(path, state)
        receipt = {
            "schema": "hdfs31-actor-v3-queue-priority-1",
            "before_state_sha256": before_sha,
            "after_state_sha256": digest(path),
            "completed_ids_unchanged": state["completion_order"],
            "queue_ids_unchanged": old_ids,
            "scores_before": {item["id"]: item["score"] for item in old_queue},
            "scores_after": {item["id"]: item["score"] for item in state["queue"]},
            "effective_unchanged": state["effective"],
            "in_flight": state["in_flight"],
        }
        campaign.save(receipt_path, receipt)
        print(json.dumps({"before": before_sha, "after": receipt["after_state_sha256"],
                          "plans": len(old_ids), "effective": state["effective"]},
                         sort_keys=True))


if __name__ == "__main__":
    main()
