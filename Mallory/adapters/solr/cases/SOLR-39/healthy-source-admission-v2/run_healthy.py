#!/usr/bin/env python3
"""GO-gated single healthy trial; --preflight-only never starts a JVM."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import socket
import sys
from pathlib import Path

import preflight

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
OUT = ROOT / "data/mallory/calibration_solr39_watcher_healthy_v2_node2/SOLR-39"
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight.main()
    if args.preflight_only:
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    receipt = json.loads(args.admission_receipt.read_text())
    if not (receipt.get("go") is True and receipt.get("host") == "node2" and
            receipt.get("mode") == "healthy" and receipt.get("case_id") == "SOLR-39" and
            receipt.get("config_sha256") == evidence["config_sha256"] and
            receipt.get("runner_sha256") == sha(Path(__file__)) and
            receipt.get("intended_output") == str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node2":
        raise ValueError("healthy trial must run on node2")
    if OUT.exists():
        raise ValueError("healthy output must be fresh")
    if shutil.disk_usage(ROOT).free < 7_650_410_496:
        raise ValueError("insufficient free disk")
    available_kib = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
    if available_kib < 8_388_608:
        raise ValueError("insufficient available RAM")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-lane3.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists():
            raise ValueError("healthy output was created while acquiring locks")
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign  # noqa: E402
        config = json.loads((HERE / "config.json").read_text())
        campaign.validate_config(config)
        state = campaign.run(HERE / "config.json", OUT)
        print(json.dumps({"status": state["status"], "case_id": "SOLR-39",
                          "completed_trials": state["completed_trials"]}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
