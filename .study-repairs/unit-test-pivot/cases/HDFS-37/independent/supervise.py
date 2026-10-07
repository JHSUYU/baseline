#!/usr/bin/env python3
"""Finish or extend an isolated, checkpointed MiniDFSCluster campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

from campaign import BASE, GROUPS

HERE = Path(__file__).resolve().parent
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
NODES = {"rollback37": "node1"}
SESSION = {"rollback37": "hdfs37_io"}
SYNC_SESSION = {"rollback37": "hdfs37_sync"}


def remote_running(node: str, name: str) -> bool:
    return subprocess.run([*SSH, "ZhenyuLi@" + node,
                           "tmux has-session -t " + shlex.quote(name)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def local_sync_running(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def start_sync(group: str) -> None:
    name = SYNC_SESSION[group]
    if local_sync_running(name):
        return
    anchor = GROUPS[group][0]
    log = BASE / anchor / "independent/evidence/sync.log"
    script = HERE / "sync_remote.py"
    command = (f"cd /users/ZhenyuLi/baseline && python3 -u {shlex.quote(str(script))} "
               f"--node {NODES[group]} --group {group} --interval 20 "
               f">> {shlex.quote(str(log))} 2>&1")
    subprocess.run(["tmux", "new-session", "-d", "-s", name, command], check=True)


def stop_sync(group: str) -> None:
    if local_sync_running(SYNC_SESSION[group]):
        subprocess.run(["tmux", "kill-session", "-t", SYNC_SESSION[group]], check=True)


def sync_full(group: str) -> None:
    subprocess.run([sys.executable, str(HERE / "sync_remote.py"),
                    "--node", NODES[group], "--group", group,
                    "--once", "--include-runs"], check=True)


def finalize(group: str) -> dict:
    subprocess.run([sys.executable, str(HERE / "finalize.py"), "--group", group],
                   check=True)
    return json.loads((BASE / GROUPS[group][0] / "result.json").read_text())


def start_extension(group: str) -> None:
    node = NODES[group]
    session = SESSION[group] + "_ext"
    anchor = GROUPS[group][0]
    script = HERE / "campaign.py"
    log = BASE / anchor / "independent/evidence/campaign.log"
    inner = (f"python3 -u {shlex.quote(str(script))} --group {group} "
             f"--max-trials 128 --max-faults 10 2>&1 | tee -a {shlex.quote(str(log))}")
    command = ("cd /users/ZhenyuLi/baseline && tmux new-session -d -s "
               + shlex.quote(session) + " " + shlex.quote(inner))
    subprocess.run([*SSH, "ZhenyuLi@" + node, command], check=True)
    SESSION[group] = session
    start_sync(group)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    args = parser.parse_args()
    group = args.group
    anchor = GROUPS[group][0]
    result_path = BASE / anchor / "result.json"
    result = json.loads(result_path.read_text())
    extension_session = SESSION[group] + "_ext"
    if (result.get("budget", {}).get("max_trials", 80) >= 128
            or remote_running(NODES[group], extension_session)):
        SESSION[group] = extension_session
        budget = 128
    else:
        budget = 80
    while True:
        result = json.loads(result_path.read_text())
        trials = result.get("fault_trials", 0)
        if trials >= budget and not remote_running(NODES[group], SESSION[group]):
            stop_sync(group)
            sync_full(group)
            final = finalize(group)
            print(json.dumps({"group": group, "trials": final["fault_trials"],
                              "status": final["status"], "bug_mark": final["bug_mark"]}),
                  flush=True)
            if final["status"] == "pending_budget_extension":
                start_extension(group)
                budget = 128
                continue
            break
        if trials < budget and not remote_running(NODES[group], SESSION[group]):
            # The remote process may have ended just before the next 20-second
            # node0 sync tick. Pull its final atomic result before deciding.
            subprocess.run([sys.executable, str(HERE / "sync_remote.py"),
                            "--node", NODES[group], "--group", group, "--once"], check=True)
            latest = json.loads(result_path.read_text())["fault_trials"]
            if latest < budget:
                raise SystemExit(f"Campaign stopped at {latest}/{budget}; resume checkpoint manually")
        time.sleep(30)


if __name__ == "__main__":
    main()
