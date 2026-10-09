#!/usr/bin/env python3
"""Keep the SHA-verifying node0 sync alive across temporary disk shortfalls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/io-version-retry-v3-owner-binding"
SYNC = HERE / "sync_hdfs24_full_v3.py"
SYNC_SHA = "dffa22d72d31bf0ed53741c0ae5a633ca5b3f2bbd182b0e618fd781f521ae11c"
SESSION = "mallory-node0-hdfs24-v3-sync"
LOG = Path("/tmp/mallory-hdfs24-v3-full.sync.log")
RECEIPT = BASE / "data/mallory/dispatch/node0-hdfs24-v3-full/terminal-sync.json"
CANONICAL = BASE / "data/mallory/cases/HDFS-24"
FLOOR = 5 * 1024**3


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active() -> bool:
    return subprocess.run(["tmux", "has-session", "-t", SESSION],
                          capture_output=True).returncode == 0


def published() -> bool:
    if not RECEIPT.is_file() or not (CANONICAL / "result.json").is_file():
        return False
    receipt = json.loads(RECEIPT.read_text())
    return (receipt.get("case_id") == "HDFS-24" and
            receipt.get("result_sha256") == sha(CANONICAL / "result.json"))


def main() -> None:
    if sha(SYNC) != SYNC_SHA:
        raise RuntimeError("pinned sync script changed")
    while True:
        if published():
            print("HDFS-24 canonical SHA publication verified", flush=True)
            return
        if active():
            time.sleep(30)
            continue
        failure = LOG.read_text() if LOG.is_file() else ""
        if not any(text in failure for text in
                   ("disk reserve insufficient", "disk reserve insufficient for publication")):
            raise RuntimeError("sync exited for a reason other than the disk reserve")
        if shutil.disk_usage(BASE).free < FLOOR + 512 * 1024**2:
            print("node0 sync waiting for verified disk reserve", flush=True)
            time.sleep(60)
            continue
        command = f"python3 {SYNC} >> {LOG} 2>&1"
        subprocess.run(["tmux", "new-session", "-d", "-s", SESSION,
                        "-c", "/tmp", command], check=True)
        print("restarted pinned HDFS-24 SHA sync after disk reserve recovered", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
