#!/usr/bin/env python3
"""Start the supplementary JUnit phase once the primary campaign is finalized."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[5]
PRIMARY = HERE.parent.parent / "result.json"
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
NODE = "ZhenyuLi@node1"
REMOTE_ROOT = "/users/ZhenyuLi/baseline"


def session_exists(name: str, remote: bool = False) -> bool:
    cmd = ["tmux", "has-session", "-t", name]
    if remote:
        cmd = [*shlex.split(SSH), NODE, " ".join(map(shlex.quote, cmd))]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def start() -> None:
    root = "crashfuzz/cases/HDFS-43/independent/equal_phase"
    paths = [root + "/campaign.py", root + "/equal-result.json",
             root + "/evidence/healthy/"]
    subprocess.run(["rsync", "-aR", "-e", SSH, *paths, NODE + ":" + REMOTE_ROOT + "/"],
                   cwd=BASE, check=True)
    if not session_exists("hdfs43_equal_io", remote=True):
        inner = ("cd " + REMOTE_ROOT + "/" + root + " && "
                 "python3 -u campaign.py --group equal43 --max-trials 80 --max-faults 8 "
                 ">> evidence/campaign.log 2>&1")
        subprocess.run([*shlex.split(SSH), NODE,
                        "tmux new-session -d -s hdfs43_equal_io " + shlex.quote(inner)],
                       check=True)
    if not session_exists("hdfs43_equal_sync"):
        inner = ("cd " + REMOTE_ROOT + " && python3 -u " + root + "/sync_remote.py "
                 "--node node1 --group equal43 --interval 20 >> "
                 + root + "/evidence/sync.log 2>&1")
        subprocess.run(["tmux", "new-session", "-d", "-s", "hdfs43_equal_sync", inner],
                       check=True)
    if not session_exists("hdfs43_equal_supervise"):
        inner = ("cd " + REMOTE_ROOT + " && python3 -u " + root + "/supervise.py "
                 "--group equal43 >> " + root + "/evidence/supervise.log 2>&1")
        subprocess.run(["tmux", "new-session", "-d", "-s", "hdfs43_equal_supervise", inner],
                       check=True)
    print("HDFS-43 equal-branch phase launched", flush=True)


def main() -> None:
    while True:
        try:
            if PRIMARY.is_file():
                status = json.loads(PRIMARY.read_text()).get("status")
                if status == "quality_complete":
                    start()
                    return
                if status == "pending_candidate_replay_source_review":
                    print("Primary candidate needs replay before equal phase", flush=True)
                    return
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("waiting to launch equal phase: " + str(error), flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
