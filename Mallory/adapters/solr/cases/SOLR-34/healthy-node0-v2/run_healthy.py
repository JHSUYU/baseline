#!/usr/bin/env python3
"""GO-gated, healthy-only SOLR-34 target discovery on node0."""

from __future__ import annotations

import argparse
import fcntl
import json
import socket
import sys
from contextlib import ExitStack
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SEED = HERE.parent / "target-discovery-v1"
OUT = ROOT / "data/mallory/solr34_healthy_node0_v2/SOLR-34"
sys.path.insert(0, str(ROOT / "Mallory/adapters/solr"))
from fault_discovery_runner import campaign, preflight, read, sha  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--go-receipt", type=Path)
    args = parser.parse_args()

    metadata = preflight(SEED, "healthy")
    config = SEED / "config-healthy-node2.json"
    if args.preflight_only:
        print(json.dumps({"status": "preflight_passed", "host_intent": "node0",
                          "output": str(OUT), **metadata}, sort_keys=True))
        return 0

    if not socket.gethostname().startswith("node0."):
        parser.error("SOLR-34 healthy-only v2 is reserved for node0")
    if args.go_receipt is None:
        parser.error("node0 steward GO receipt required before starting a JVM")
    receipt = read(args.go_receipt)
    expected = {"go": True, "host": "node0", "case_id": "SOLR-34",
                "mode": "healthy", "config_sha256": sha(config),
                "runner_sha256": sha(Path(__file__)), "intended_output": str(OUT)}
    if any(receipt.get(key) != value for key, value in expected.items()):
        parser.error("node0 steward GO receipt missing or mismatched")

    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = locks.enter_context((lock_root / name).open("a+"))
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps({"status": "admitted", "go_receipt_sha256": sha(args.go_receipt),
                          "host_intent": "node0", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(config, OUT)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
