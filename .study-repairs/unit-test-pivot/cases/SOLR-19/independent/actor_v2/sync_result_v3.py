#!/usr/bin/env python3
"""Mirror the node1 resumable SOLR-19 ledger into node0's live checklist."""

import json
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
LOCAL_RESULT = CASE / "result.json"
LOCAL_STATE = HERE / "evidence/v3-campaign-node1-mirror/state.json"
REMOTE_CASE = "/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/SOLR-19"
REMOTE = "ZhenyuLi@node1:"
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"


def fetch(remote: str, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    command = ["rsync", "-q", "-e", SSH, REMOTE + remote, str(temporary)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        print("sync error", result.stderr.strip(), flush=True)
        return False
    try:
        data = json.loads(temporary.read_text())
        if data.get("case_id") != "SOLR-19":
            raise ValueError("wrong case ID")
        current = json.loads(target.read_text()) if target.exists() else {}
        old_count = (current.get("fault_trials", -1) if target == LOCAL_RESULT else
                     len(current.get("attempts", [])))
        new_count = (data.get("fault_trials", -1) if target == LOCAL_RESULT else
                     len(data.get("attempts", [])))
        if new_count < old_count:
            raise ValueError(f"regressing count {old_count}->{new_count}")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("invalid sync payload", error, flush=True)
        temporary.unlink(missing_ok=True)
        return False
    temporary.replace(target)
    if new_count > old_count:
        print(f"SOLR-19 mirrored {target.name}: {old_count}->{new_count}", flush=True)
    return True


def main() -> None:
    print("SOLR-19 node1 result mirror started", flush=True)
    while not (HERE / "STOP_RESULT_SYNC").exists():
        if fetch(REMOTE_CASE + "/result.json", LOCAL_RESULT):
            fetch(REMOTE_CASE + "/independent/actor_v2/evidence/v3-campaign/state.json",
                  LOCAL_STATE)
        time.sleep(20)


if __name__ == "__main__":
    main()
