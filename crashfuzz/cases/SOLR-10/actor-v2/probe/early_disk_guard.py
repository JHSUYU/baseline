#!/usr/bin/env python3
"""Pause this campaign at an atomic boundary before shared node1 disk reaches 10 GiB."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "evidence/campaign-v4/state.json"
CAMPAIGN = STATE.parent
DRIVER = str(CASE / "probe/campaign.py")
THRESHOLD_GIB = 10.5


def drivers() -> list[int]:
    result = []
    for proc in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            argv = [item.decode(errors="replace") for item in proc.read_bytes().split(b"\0") if item]
        except OSError:
            continue
        if len(argv) >= 2 and Path(argv[0]).name.startswith("python") and DRIVER in argv[1:]:
            result.append(int(proc.parent.name))
    return result


def main() -> None:
    while True:
        state = json.loads(STATE.read_text())
        if all(item["stop_reason"] != "running" for item in state["site_progress"].values()):
            print(json.dumps({"terminal": True, "trials": len(state["trials"])}), flush=True)
            return
        free = shutil.disk_usage(CASE).free / 1024 ** 3
        if free < THRESHOLD_GIB:
            pids = drivers()
            if len(pids) != 1:
                raise RuntimeError(f"Expected one campaign driver at {free:.2f} GiB: {pids}")
            receipt = CAMPAIGN / ("early-disk-guard-" +
                                  datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
            subprocess.run([sys.executable, str(CASE / "probe/stop_at_boundary.py"),
                            "--pid", str(pids[0]), "--timeout", "420",
                            "--receipt", str(receipt)], check=True)
            print(json.dumps({"paused_for_disk": True, "free_gib_at_trigger": round(free, 3),
                              "receipt": str(receipt)}), flush=True)
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
