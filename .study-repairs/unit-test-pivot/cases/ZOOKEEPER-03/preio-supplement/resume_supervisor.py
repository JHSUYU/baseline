#!/usr/bin/env python3
"""Resume ZK03's fixed supplement only at audited wall-limit boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


ASSETS = Path("/users/ZhenyuLi/zk03-supplement-assets")
ROOT = Path("/users/ZhenyuLi/zk03-supplement-runs")
CAMPAIGN_LOG = Path("/users/ZhenyuLi/zk03-supplement-run.log")
FIRST_SESSION = "zk03_preio_supplement"
MIN_FREE = 10 * 1024**3
MAX_JAVA = 4
PORT_LOW = 28719
PORT_HIGH = 30064


def session_alive():
    return subprocess.run(["tmux", "has-session", "-t", FIRST_SESSION],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def resource_gate():
    free = shutil.disk_usage(ROOT.parent).free
    java_ps = subprocess.run(["ps", "-C", "java", "-o", "pid="],
                             capture_output=True, text=True)
    if java_ps.returncode not in (0, 1):
        raise RuntimeError("cannot count Java processes: " + java_ps.stderr)
    java = len(java_ps.stdout.splitlines())
    ports = []
    for line in subprocess.check_output(["ss", "-H", "-ltn"],
                                        text=True).splitlines():
        try:
            port = int(line.split()[3].rsplit(":", 1)[1])
        except (IndexError, ValueError):
            continue
        if PORT_LOW <= port <= PORT_HIGH:
            ports.append(port)
    gate = {"free_bytes": free, "java_processes": java,
            "occupied_reserved_ports": ports}
    if free < MIN_FREE or java >= MAX_JAVA or ports:
        raise RuntimeError("node1 supplement resume resource gate: " +
                           json.dumps(gate, sort_keys=True))
    return gate


def inspect_checkpoint():
    state = json.loads((ROOT / "supplement-checkpoint.json").read_text())
    selected = len(state["results"])
    pending = len(state["pending_ids"])
    if selected + pending != 63 or state["legacy_attempts"] != 480 or \
            state["legacy_effective"] != 37 or state["inflight"] is not None:
        raise RuntimeError("checkpoint incomplete or denominator changed")
    return {"status": state["status"], "selected": selected,
            "effective": sum(bool(r["effective"]) for r in state["results"]),
            "pending": pending,
            "target_throws": sum(r["selected_target_throws"]
                                 for r in state["results"])}


def run_checked(args, log=None):
    if log is None:
        subprocess.run(args, cwd=ASSETS, check=True)
        return
    with log.open("a") as stream:
        subprocess.run(args, cwd=ASSETS, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    if not Path("/proc/sys/kernel/hostname").read_text().startswith("node1"):
        raise RuntimeError("ZK03 supervisor reserved for node1")
    print("watching original tmux session; no new JVM while it is alive", flush=True)
    while session_alive():
        time.sleep(10)
    while True:
        before = inspect_checkpoint()
        print(json.dumps({"checkpoint": before}, sort_keys=True), flush=True)
        if before["status"] == "queue_exhausted" and before["pending"] == 0:
            run_checked([sys.executable, "audit.py", "--archive"])
            print("terminal raw audit/archive complete", flush=True)
            return
        if before["status"] != "paused_wall_limit":
            print("paused for case-owner review; no automatic resume", flush=True)
            return
        run_checked([sys.executable, "audit.py"])
        run_checked([sys.executable, "campaign.py"])
        gate = resource_gate()
        print(json.dumps({"resuming_after_audited_boundary": before,
                          "gate": gate}, sort_keys=True), flush=True)
        run_checked([sys.executable, "-u", "campaign.py", "--run",
                     "--slot", "14", "--workers", "16", "--timeout", "180",
                     "--wall-limit", "1800"], CAMPAIGN_LOG)


if __name__ == "__main__":
    main()
