#!/usr/bin/env python3
"""Resume the HDFS-12 long-lived-client campaign with key-delivery I/O."""

from __future__ import annotations

import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hdfs12_long_lived_campaign",
                                               HERE.parent / "campaign.py")
assert spec is not None and spec.loader is not None
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)

# Reuse the same queue, exact matching, feedback and atomic checkpoint code.
# All mutable evidence paths are exclusive to this control-plane campaign.
campaign.HERE = HERE
campaign.CASE = HERE.parent.parent.parent
campaign.STATE = HERE / "campaign-state.json"
campaign.LOCK = HERE / "campaign.lock"
campaign.RESULT = HERE / "result.json"
campaign.LEDGER = HERE / "trial-ledger.csv"
campaign.RUNNER = HERE / "run_control_plane.py"
campaign.HEALTHY = HERE / "healthy-01"


def initial_queue(state: dict) -> None:
    trace = campaign.rows(campaign.HEALTHY)
    targets = [event["seq"] for event in trace
               if event["event"] == "TARGET_CHECK"
               and event.get("siteId") == campaign.TARGET]
    if not targets:
        raise RuntimeError("original long-lived JUnit did not reach HDFS-12 target")
    for event in trace:
        if event["event"] != "FAULT_POINT_OBSERVED" or event["seq"] >= max(targets):
            continue
        marker = event["marker"]
        # Favor the control-plane update window that carries the fresh key.
        # All observed SASL socket reads remain in the queue for exploration.
        priority = (100 if marker == "FAULT:HDFS_KEY_UPDATE:RPC" else
                    80 if marker == "FAULT:HDFS_HEARTBEAT:RPC" else 0)
        for kind in campaign.KINDS:
            campaign.enqueue(state, [campaign.point(event, kind)],
                             priority=priority + event["seq"])


campaign.initial_queue = initial_queue

base_initialize = campaign.initialize


def initialize() -> dict:
    state = base_initialize()
    for name in ("smoke-heartbeat", "smoke-keyupdate"):
        directory = HERE / name
        applied = [event for event in campaign.rows(directory)
                   if event["event"] == "FAULT_APPLIED"]
        if len(applied) != 1:
            raise RuntimeError(name + " did not apply exactly one fault")
        sequence = [campaign.point(applied[0], applied[0]["faultType"])]
        trial = campaign.evaluate(directory, sequence, state)
        if not trial["valid_for_feedback"]:
            raise RuntimeError(name + " did not retain the target check")
        state["queue"] = [item for item in state["queue"] if item["id"] != trial["id"]]
        state["completed"].append(trial)
        campaign.admit(state, trial)
    campaign.atomic_json(campaign.STATE, state)
    campaign.write_result(state)
    return state


campaign.initialize = initialize


if __name__ == "__main__":
    campaign.main()
