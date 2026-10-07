#!/usr/bin/env python3
"""Resume the calibrated startup campaign with actor-episode queue diversity.

Only queue selection changes.  The original controller still owns attempt
execution, fail-closed actor matching, coverage accounting, and checkpoints.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

import campaign as base


EXPECTED_BASE_SHA256 = "b65f23dd8b80bbdb5a6f09efac82e313771be22dcd8b094ade4ff70c5ccc913a"
POLICY = "target_actor_episode_diversity_v1"


def _pending(state: dict, item: dict) -> list[str]:
    return [case for case in item["cases"]
            if state["effective_by_case"].get(case, 0)
            < state["budget"]["goal_by_case"].get(case, 80)]


def _effective_actor_counts(state: dict) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for sequence_id in state["completion_order"]:
        completed = state["completed"][sequence_id]
        if not completed["result"]["exact_order_applied"]:
            continue
        actor = completed["item"]["sequence"][-1]["actorKey"]
        for case, outcome in completed["result"]["by_case"].items():
            if outcome["valid_for_feedback"]:
                counts[case, actor] += 1
    return counts


def pick_episode_diverse(state: dict) -> dict | None:
    if state["in_flight"] is not None:
        return state["in_flight"]
    while state["queue"]:
        n = len(state["completion_order"])
        progress = state["effective_by_case"]
        frontier = max(progress.values(), default=0)
        target_lost_file = sum(
            bool(entry.get("item")) and bool(entry.get("result"))
            and "FILE:" in entry["item"]["sequence"][-1]["marker"]
            and entry["result"]["exact_order_applied"]
            and not any(outcome["valid_for_feedback"]
                        for outcome in entry["result"]["by_case"].values())
            for entry in state["completed"].values())

        def priority(index: int) -> tuple[int, int, int]:
            item = state["queue"][index]
            pending = _pending(state, item)
            deficit = frontier - min((progress[case] for case in pending),
                                     default=frontier)
            file_penalty = (1000 if target_lost_file >= 3 and
                            "FILE:" in item["sequence"][-1]["marker"] else 0)
            return (item["score"] + 300 * deficit - file_penalty,
                    len(item["sequence"]), -index)

        eligible = [index for index, item in enumerate(state["queue"])
                    if item["id"] not in state["completed"]
                    and _pending(state, item)]
        if not eligible:
            state["queue"].clear()
            return None

        rpc = [index for index in eligible
               if "RPC:" in state["queue"][index]["sequence"][-1]["marker"]]
        if n % 4 == 0 and rpc:
            actor_counts = _effective_actor_counts(state)

            def least_tested(index: int) -> tuple[int, int, tuple[int, int, int]]:
                item = state["queue"][index]
                actor = item["sequence"][-1]["actorKey"]
                counts = [actor_counts[case, actor] for case in _pending(state, item)]
                # Unseen logical target actors win this slot.  Once every
                # actor has been tested, balance the least-tested episode.
                return (-min(counts), -sum(counts), priority(index))

            index = max(rpc, key=least_tested)
        elif n % 10 == 9 and rpc:
            index = rpc[0]  # retain the original oldest-RPC exploration slot
        else:
            index = max(eligible, key=priority)
        item = state["queue"].pop(index)
        state["in_flight"] = item
        return item
    return None


def main() -> None:
    path = Path(base.__file__)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != EXPECTED_BASE_SHA256:
        raise RuntimeError(f"base controller SHA mismatch: {actual}")
    base.pick = pick_episode_diverse
    print(f"scheduler_policy={POLICY} base_sha256={actual}", flush=True)
    base.main()


if __name__ == "__main__":
    main()
