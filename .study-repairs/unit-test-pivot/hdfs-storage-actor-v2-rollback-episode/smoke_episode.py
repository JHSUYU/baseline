#!/usr/bin/env python3
"""Offline scheduler smoke: a queued RPC for a new actor episode is sampled."""
from __future__ import annotations

import copy

import campaign


def item(identity: str, episode: int, score: int) -> dict:
    return {"id": identity, "score": score, "cases": ["HDFS-26"],
            "sequence": [{"actorKey": f"episode={episode}/dn=1/dirs=dfs/data1",
                          "marker": "FAULT:HDFS_BP_RPC:RESPONSE"}]}


def main() -> None:
    history = {f"old-{i}": {"item": item(f"old-{i}", 5, 1),
                             "result": {"exact_order_applied": True,
                                        "by_case": {"HDFS-26": {"valid_for_feedback": True}}}}
               for i in range(9)}
    state = {"in_flight": None, "completion_order": list(history),
             "completed": history, "queue": [item("repeated", 5, 2000),
                                               item("new-episode", 15, 1000)],
             "effective_by_case": {"HDFS-26": 9},
             "budget": {"goal_by_case": {"HDFS-26": 80}}}
    selected = campaign.pick(copy.deepcopy(state))
    assert selected is not None and selected["id"] == "new-episode", selected
    # Outside the original one-in-ten exploration slot, ordinary score order
    # is unchanged. The real campaign state itself is never imported or edited.
    state["completion_order"].pop()
    selected = campaign.pick(copy.deepcopy(state))
    assert selected is not None and selected["id"] == "repeated", selected
    print("episode scheduler smoke passed: periodic novelty and normal priority")


if __name__ == "__main__":
    main()
