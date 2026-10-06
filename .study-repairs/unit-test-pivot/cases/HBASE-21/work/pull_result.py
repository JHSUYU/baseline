#!/usr/bin/env python3
"""Copy the node1 case result atomically to node0 for the 102-site checklist."""
import json
import os
from pathlib import Path
import subprocess
import time

case = Path(__file__).resolve().parent.parent
result = case / "result.json"
temp = case / ".result.node1.tmp"
remote = (
    "ZhenyuLi@node1:/users/ZhenyuLi/baseline/.study-repairs/"
    "unit-test-pivot/cases/HBASE-21/result.json"
)
terminal = {
    "budget_complete_pending_source_review",
    "queue_exhausted_pending_source_review",
    "attempt_cap_pending_source_review",
    "wall_cap_pending_source_review",
    "only_target_loss_prefixes_pending_source_review",
    "candidate_review",
}

while True:
    copy = subprocess.run(
        ["rsync", "-aq", "-e",
         "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes",
         remote, str(temp)],
        capture_output=True, text=True, check=False,
    )
    if copy.returncode == 0:
        try:
            data = json.loads(temp.read_text())
            if data.get("case_id") == "HBASE-21":
                os.replace(temp, result)
                print(data.get("status"), data.get("fault_trials"), flush=True)
                if data.get("status") in terminal:
                    break
        except (ValueError, OSError) as error:
            print("invalid remote result:", error, flush=True)
    else:
        print("sync failed:", copy.stderr.strip(), flush=True)
    time.sleep(10)
