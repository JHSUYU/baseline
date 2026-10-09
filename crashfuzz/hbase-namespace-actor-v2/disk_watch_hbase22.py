#!/usr/bin/env python3
"""Pause HBASE-22 before the next JVM if node0 free space drops below 4 GiB."""
import hashlib
import json
import shutil
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / "campaigns/HBASE-22"
CHECKPOINT = CAMPAIGN / "checkpoint.json"
PAUSE = CAMPAIGN / "PAUSE"
MIN_FREE_BYTES = 4 * 1024 ** 3


def main():
    while True:
        state = json.loads(CHECKPOINT.read_text())
        if state["status"] in ("budget_complete_pending_audit",
                               "queue_exhausted_pending_audit",
                               "attempt_cap_pending_audit",
                               "candidate_review_pending_source_and_replay"):
            return
        free = shutil.disk_usage(HERE).free
        if free < MIN_FREE_BYTES:
            PAUSE.touch(exist_ok=True)
            # The runner checks PAUSE before creating the next trial's run
            # directory/JVM. The current JVM may finish and checkpoint safely.
            time.sleep(3)
            current = CHECKPOINT.read_bytes()
            receipt = {"reason": "node0_disk_below_4_gib",
                       "threshold_bytes": MIN_FREE_BYTES,
                       "free_bytes_when_detected": free,
                       "time_unix": time.time(),
                       "checkpoint_sha256_after_pause": hashlib.sha256(current).hexdigest(),
                       "completed_attempts_after_pause": len(json.loads(current)["trials"]),
                       "effective_after_pause": json.loads(current)["effective"],
                       "inflight_id": json.loads((CAMPAIGN / "inflight.json").read_text())["id"]
                                      if (CAMPAIGN / "inflight.json").exists() else None}
            (CAMPAIGN / "disk-pause-receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            print(json.dumps(receipt, sort_keys=True), flush=True)
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
