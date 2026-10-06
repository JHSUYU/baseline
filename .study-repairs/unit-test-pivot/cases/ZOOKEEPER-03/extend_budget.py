#!/usr/bin/env python3
"""Reopen the same completed checkpoint for the approved 96/6 extension."""

import json
import os
from pathlib import Path

STATE = Path("/users/ZhenyuLi/zk03-case/campaign/ZOOKEEPER-03/state.json")
data = json.loads(STATE.read_text())
if len(data["completed"]) != 48 or data.get("status") != "budget_or_queue_complete":
    raise RuntimeError("Expected the completed 48-trial initial checkpoint")
data["finished"] = False
data["status"] = "fuzzing"
data["extension_reason"] = (
    "Trial 38 still added two call-site feedback IDs, and no depth-four "
    "fault sequence had been tried at the 48/4 limit. The higher budget "
    "tests the user's requested larger I/O fault combinations.")
temp = STATE.with_name("state.json.tmp.extend")
with temp.open("w") as output:
    json.dump(data, output, indent=2, sort_keys=True)
    output.write("\n")
    output.flush()
    os.fsync(output.fileno())
temp.replace(STATE)
