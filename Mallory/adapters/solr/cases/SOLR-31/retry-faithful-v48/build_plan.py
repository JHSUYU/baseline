#!/usr/bin/env python3
"""Build one exact low-level getData retry plan from an admitted healthy receipt.

The add-on hook selects one physical actor/epoch and one qualified watcher-read
ordinal before calling Probe.beforeDoor. Probe's `hit` is then the low-level
attempt number within that watcher occurrence.
"""

import argparse
import hashlib
import json
from pathlib import Path

SITE = (
    "org.apache.solr.common.cloud.SolrZkClient#lambda$getData$6"
    "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B"
    "@349:door:lowlevel-retry"
)
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
COLLECTION = "forceleader_lower_terms_collection"
PATH = f"/collections/{COLLECTION}/state.json"
CLASS_SHA = "51b3131fed142509b80da408d0d3f8d036045237b51a48c2a4dd9cf574a72dc0"


def plan_from_receipt(receipt: dict, mode: str) -> dict:
    if receipt.get("schema_version") != 1 or receipt.get("status") != "retry_lowlevel_healthy_admitted":
        raise ValueError("healthy retry receipt has not been admitted")
    binding = receipt.get("binding", {})
    if binding.get("site") != SITE or binding.get("collection") != COLLECTION \
            or binding.get("path") != PATH or binding.get("original_class_sha256") != CLASS_SHA:
        raise ValueError("source/site/collection binding differs from pinned release")
    actor = binding.get("node")
    epoch = binding.get("epoch")
    rank = binding.get("watch_read_ordinal")
    retries = binding.get("retry_count")
    if not isinstance(actor, str) or not actor.startswith("shard-") \
            or type(epoch) is not int or epoch < 0 \
            or type(rank) is not int or rank < 1 \
            or type(retries) is not int or not 2 <= retries <= 12:
        raise ValueError("unbound actor, epoch, watcher read, or retry budget")
    if not binding.get("reader_id") or not binding.get("keeper_id") \
            or type(binding.get("session_id")) is not int \
            or binding["session_id"] <= 0:
        raise ValueError("reader and ZooKeeper session identity required")
    if mode not in ("transient", "exhaust"):
        raise ValueError("mode must be transient or exhaust")
    count = 1 if mode == "transient" else retries
    return {
        "schema_version": 1,
        # FaultPlan ignores this field; the future runner must verify it and set all
        # three MALLORY_SOLR31_RETRY_* selectors before invoking the JUnit JVM.
        "selection": {"mode": mode, "node": actor, "epoch": epoch,
                      "watch_read_ordinal": rank, "reader_id": binding["reader_id"],
                      "keeper_id": binding["keeper_id"],
                      "session_id": binding["session_id"], "retry_count": retries},
        "faults": [
            {
                "fault_id": f"solr31-v48-{mode}-attempt-{attempt}",
                "point": {"site": SITE, "node": actor, "epoch": epoch, "hit": attempt},
                "fault_type": "EXCEPTION",
                "exception_class": EXCEPTION,
            }
            for attempt in range(1, count + 1)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthy-receipt", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("transient", "exhaust"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("plan output must be fresh")
    raw = args.healthy_receipt.read_bytes()
    receipt = json.loads(raw)
    plan = plan_from_receipt(receipt, args.mode)
    args.out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"mode": args.mode, "attempt_faults": len(plan["faults"]),
                      "healthy_receipt_sha256": hashlib.sha256(raw).hexdigest(),
                      "plan_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
