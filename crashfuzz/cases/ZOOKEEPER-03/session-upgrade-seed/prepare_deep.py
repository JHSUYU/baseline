#!/usr/bin/env python3
"""Pin a depth≥3 mutation campaign to the completed child raw archive."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "evidence/zk03-upgrade-recovery-children-raw.tar.gz"
PILOT = HERE / "evidence/zk03-upgrade-pilot-raw.tar.gz"
OUT = HERE / "deep-manifest.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with tarfile.open(ARCHIVE) as archive:
        data = archive.extractfile(
            "zk03-upgrade-recovery-children/child-checkpoint.json").read()
        source = json.loads(data)
        if source["status"] != "queue_exhausted" or len(source["results"]) != 13 or \
                any(r["selected_target_throws"] for r in source["results"]):
            raise RuntimeError("child queue is incomplete or needs target exception replay")
    child_effective = sum(r["target_after_final_fault"] for r in source["results"])
    manifest = {"case_id": "ZOOKEEPER-03", "phase": "session-upgrade-depth3plus",
                "original_junit": "org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower",
                "original_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
                "target_check": "SessionTrackerImpl#setOwner:329:missingOrClosing",
                "target_session_tag": "upgradedSession", "fault_type": "IOException",
                "max_faults": 8, "effective_target": 80, "selected_cap": 256,
                "pilot_selected": 10, "pilot_effective": 3,
                "child_selected": 13, "child_effective": child_effective,
                "agent_sha256": "9e2ad5f3cdfd8ba45990a9802c351180d72afffac5320597714ab1208bd5f32f",
                "pilot_archive_sha256": sha(PILOT),
                "child_archive_sha256": sha(ARCHIVE),
                "child_checkpoint_sha256": hashlib.sha256(data).hexdigest(),
                "mutation": "add one observed actor-bound same-session I/O after final fault and before later global target guard; prioritize new I/O family and code coverage feedback",
                "resource_gate": "node1 slot15; shared jvm-start.lock; Java<4; free disk>=10GiB"}
    OUT.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"child_effective": child_effective,
                      "manifest_sha256": sha(OUT), "selected_cap": 256,
                      "effective_target": 80}, sort_keys=True))


if __name__ == "__main__":
    main()
