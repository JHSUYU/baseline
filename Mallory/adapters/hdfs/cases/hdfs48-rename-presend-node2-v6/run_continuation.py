#!/usr/bin/env python3
"""Run the case-local invalid-plan novelty policy over pinned core release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket

from seed_continuation import CONFIG
from strict_policy import campaign, run


def check_seed(out: Path) -> None:
    if os.environ.get("MALLORY_DISPATCH_ADMITTED") != "1" or socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("v6 campaign requires separate node2 dispatch GO")
    cfg = json.loads(CONFIG.read_text())
    checkpoint = json.loads((out / "checkpoint.json").read_text())
    recorded = json.loads((out / "config.json").read_text())
    proof = json.loads((out / "seed-provenance.json").read_text())
    if (recorded != cfg or checkpoint.get("config_digest") != campaign.digest(cfg) or
            checkpoint.get("completed_trials", [])[:2] != [0, 1] or
            proof.get("v6_reused_trials") != [0, 1] or
            proof.get("v5_receipt_sha256") !=
                "9c1316fbd336fb053bb91ab12a81bc56dc966e497ede43ef8b1680efe0c57828" or
            proof.get("v6_config_sha256") != hashlib.sha256(CONFIG.read_bytes()).hexdigest()):
        raise RuntimeError("v6 checkpoint is not derived from sealed v5")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    check_seed(args.out)
    state = run(CONFIG, args.out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "queue_size": len(state["queue"])}, sort_keys=True))
