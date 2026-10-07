#!/usr/bin/env python3
"""One-time HDFS-07 post-pilot attempt-cap migration; no JUnit."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build_offline import HERE
from campaign_v2 import atom


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = HERE / "evidence/HDFS-07/campaign-v2"
    checkpoint = root / "checkpoint.json"
    receipt = root / "attempt-cap-migration-3-to-4.json"
    if receipt.exists():
        raise RuntimeError("migration receipt already exists")
    state = json.loads(checkpoint.read_text())
    if (state.get("case") != "HDFS-07" or state.get("version") != 2 or
            state.get("legacy_trials_imported") != 0 or state.get("current") is not None or
            len(state["completed"]) != 3 or
            sum(row["effective"] for row in state["completed"]) != 3 or
            state["budget"] != {"effective": 80, "max_faults": 8,
                                "attempt_cap": 160, "extension_effective": 128,
                                "extension_max_faults": 10}):
        raise RuntimeError("checkpoint is not the audited three-trial boundary")
    before = sha(checkpoint)
    state["budget"]["attempt_cap"] = 320
    atom(checkpoint, state)
    result = {"case": "HDFS-07", "at_utc": datetime.now(timezone.utc).isoformat(),
              "reason": "increase attempt caps to 320/512 while preserving the 80/128 effective budget",
              "old_checkpoint_sha256": before,
              "new_checkpoint_sha256": sha(checkpoint),
              "completed_preserved": 3, "effective_preserved": 3,
              "old_initial_attempt_cap": 160, "new_initial_attempt_cap": 320,
              "old_extension_attempt_cap": 256, "new_extension_attempt_cap": 512}
    atom(receipt, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
