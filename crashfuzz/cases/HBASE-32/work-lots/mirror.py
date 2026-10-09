#!/usr/bin/env python3
"""Mirror only HBASE-32's atomic result to node0 and render its shared checklist."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
PIVOT = CASE.parent
RESULT = CASE / "result.json"
REMOTE = "ZhenyuLi@node1:" + str(RESULT)
SSH = ("ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes "
       "-o IdentitiesOnly=yes -o BatchMode=yes")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def mirror_once() -> None:
    old = digest(RESULT)
    subprocess.run(["rsync", "-a", "-e", SSH, REMOTE, str(RESULT)],
                   check=True, timeout=30)
    new = digest(RESULT)
    if new != old:
        subprocess.run([sys.executable, str(PIVOT / "checklist.py"), "render"],
                       check=True, timeout=30)
        print("HBASE32 result mirrored", new, flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        mirror_once()
    else:
        while True:
            try:
                mirror_once()
            except Exception as error:
                print("HBASE32 mirror retry after:", repr(error), flush=True)
            time.sleep(30)
