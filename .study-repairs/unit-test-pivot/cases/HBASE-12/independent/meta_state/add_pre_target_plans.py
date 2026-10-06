#!/usr/bin/env python3
"""Append healthy-observed TableState writes that precede HBASE-12 B3."""

import json
import os
import sys
import time

from campaign import PLANS, STATE, save, utc


def main() -> None:
    wait = "--wait" in sys.argv
    while True:
        state = json.loads(STATE.read_text())
        if state["phase"] == "complete":
            break
        if not wait:
            raise SystemExit("Finish the six original META write plans before extending")
        time.sleep(15)
    if len(state["completed"]) != 6:
        raise SystemExit("Expected exactly six original META write plans")
    healthy = state["healthy"]
    first_b3 = min(visit["line_index"] for visit in healthy["target_visits"]
                   if visit["b3_evaluated"])
    choices = []
    for table_state in ("ENABLING", "ENABLED"):
        for marker, kind in (("META_WRITE_REQUEST", "IOException"),
                             ("META_WRITE_RESPONSE", "SocketTimeoutException")):
            points = [point for point in healthy["io"]
                      if point["marker"] == marker
                      and ("|" + table_state + "|") in point["family"]
                      and point["line_index"] < first_b3]
            if len(points) != 1:
                raise SystemExit("Expected one pre-B3 " + marker + " for " + table_state)
            choices.append({"point": points[0], "kind": kind})
    prior = {(choice["point"]["id"], choice["kind"])
             for choice in state["choices"]}
    if any((choice["point"]["id"], choice["kind"]) in prior for choice in choices):
        raise SystemExit("Continuation would duplicate an existing fault selector")
    for index, choice in enumerate(choices, len(state["choices"]) + 1):
        choice["name"] = "meta_%04d" % index
        plan = PLANS / (choice["name"] + ".plan")
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(choice["point"]["id"] + " " + choice["kind"] + "\n")
        choice["plan"] = str(plan)
    state["choices"].extend(choices)
    state["phase"] = "trials"
    state["stop_reason"] = ""
    state["pre_target_continuation_utc"] = utc()
    state["pre_target_continuation_note"] = (
        "Four ENABLING/ENABLED meta writes precede the first B3 evaluation in the "
        "same healthy trace; the initial six DISABLING/DISABLED writes follow both B3 "
        "evaluations. Same recorder and production coverage scope; prior trials retained.")
    save(STATE, state)
    print("APPENDED", len(choices), "pre-target plans; total", len(state["choices"]),
          flush=True)
    if wait:
        os.chdir(STATE.parent)
        os.execv(sys.executable, [sys.executable, "-u", str(STATE.parent / "campaign.py")])


if __name__ == "__main__":
    main()
