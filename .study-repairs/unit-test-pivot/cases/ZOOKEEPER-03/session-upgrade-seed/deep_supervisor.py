#!/usr/bin/env python3
"""Audit and resume only clean wall-limit boundaries of the depth campaign."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import time


ROOT = Path("/users/ZhenyuLi/zk03-upgrade-deep")
FIRST_SESSION = "zk03_upgrade_deep"
ARCHIVE = ROOT.parent / "zk03-upgrade-deep-raw.tar.gz"


def session_alive():
    # tmux accepts a session-name prefix by default; the supervisor's own
    # name starts with FIRST_SESSION, so require an exact session match.
    return subprocess.run(["tmux", "has-session", "-t", "=" + FIRST_SESSION],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def checkpoint():
    state = json.loads((ROOT / "deep-checkpoint.json").read_text())
    if state["source_pilot_effective"] != 3 or state["source_child_effective"] != 7 or \
            len(state["results"]) > 256:
        raise RuntimeError("deep budget or source denominators changed")
    return state


def archive():
    temporary = ARCHIVE.with_suffix(".tar.gz.tmp")
    with tarfile.open(temporary, "w:gz") as output:
        output.add(ROOT, arcname=ROOT.name,
                   filter=lambda info: None if "/temp/" in info.name or
                   "/test-data/" in info.name else info)
    temporary.replace(ARCHIVE)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    value = {"status": "archived", "archive": str(ARCHIVE),
             "archive_sha256": digest, "bytes": ARCHIVE.stat().st_size,
             "checkpoint_sha256": hashlib.sha256(
                 (ROOT / "deep-checkpoint.json").read_bytes()).hexdigest()}
    (ROOT / "deep-archive-receipt.json").write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n")
    print(json.dumps(value, sort_keys=True), flush=True)


def main():
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("ZK03 supervisor reserved for node1")
    print("waiting for first deep tmux; no concurrent JUnit launch", flush=True)
    while session_alive():
        time.sleep(10)
    while True:
        state = checkpoint()
        print(json.dumps({"status": state["status"],
                          "selected": len(state["results"]),
                          "pending": len(state["queue"]),
                          "inflight": state["inflight"] is not None},
                         sort_keys=True), flush=True)
        if state["inflight"] is not None:
            print("stopping for inflight raw review", flush=True)
            return
        subprocess.run([sys.executable, "audit_deep.py"], cwd=ROOT, check=True)
        if state["status"] == "paused_wall_limit":
            subprocess.run([sys.executable, "deep_campaign.py"], cwd=ROOT, check=True)
            with (ROOT / "deep-console.log").open("a") as log:
                subprocess.run([sys.executable, "-u", "deep_campaign.py", "--run",
                                "--timeout", "180", "--wall-limit", "1800"],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            continue
        if state["status"] in ("effective_budget_80_reached",
                               "selected_cap_before_effective_budget",
                               "queue_exhausted_before_effective_budget",
                               "candidate_needs_replay", "paused_junit_timeout"):
            archive()
        return


if __name__ == "__main__":
    main()
