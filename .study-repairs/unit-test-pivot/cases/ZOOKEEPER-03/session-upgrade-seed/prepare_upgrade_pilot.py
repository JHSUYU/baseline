#!/usr/bin/env python3
"""Select ten distinct I/O occurrences observed before the target in both healthy JUnits."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "evidence/zk03-upgrade-health-evidence.tar.gz"
OUTPUT = HERE / "pilot-manifest.json"
CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing"


def trace(archive, label):
    content = archive.extractfile(f"healthy-v2/{label}/events.tsv").read()
    rows = []
    for line in content.decode().splitlines():
        fields = line.split("\t")
        rows.append((int(fields[0]), fields[1], fields[2:]))
    target = [seq for seq, kind, fields in rows
              if kind == "TARGET_GUARD" and fields[0] == CHECK]
    if len(target) != 1:
        raise RuntimeError(f"{label}: expected one selected global guard")
    selectors = {}
    for seq, kind, fields in rows:
        if kind == "IO" and seq < target[0] and len(fields) >= 7 \
                and fields[6] == "upgradedSession":
            selector = "@@".join(fields[:4])
            if selector in selectors:
                raise RuntimeError(f"{label}: duplicate I/O occurrence")
            selectors[selector] = {"sequence": seq, "fields": fields[:7]}
    return hashlib.sha256(content).hexdigest(), selectors


def main():
    with tarfile.open(ARCHIVE) as archive:
        a_sha, a = trace(archive, "healthy-a")
        b_sha, b = trace(archive, "healthy-b")
        if set(a) != set(b) or len(a) != 35:
            raise RuntimeError("two healthy pre-target bound I/O frontiers differ")
        receipt = json.load(io.TextIOWrapper(archive.extractfile(
            "healthy-v2/health-calibration.json")))
        if receipt["status"] != "healthy_target_calibrated" or \
                len(receipt["audits"]) != 2 or \
                any(not row["usable"] for row in receipt["audits"]):
            raise RuntimeError("healthy calibration is not usable")

    def find(site_fragment, role, op, ordinal):
        matches = [(selector, details) for selector, details in a.items()
                   if site_fragment in details["fields"][0]
                   and details["fields"][1].startswith(role)
                   and details["fields"][2].endswith(":op:" + op)
                   and details["fields"][3] == str(ordinal)]
        if len(matches) != 1:
            raise RuntimeError(f"selector not unique: {site_fragment}/{role}/{op}/{ordinal}")
        selector, details = matches[0]
        return {"selector": selector, "healthy_sequence_a": details["sequence"],
                "healthy_sequence_b": b[selector]["sequence"],
                "site": details["fields"][0], "actor": details["fields"][1],
                "resource": details["fields"][2], "ordinal": ordinal,
                "relation": "same_session", "family": role + ":" + op}

    candidates = [find("ClientCnxnSocketNIO#doIO:74", "client:initial", "read", n)
                  for n in (1, 2, 3, 5, 7, 9, 11, 12)]
    candidates.append(find("NIOServerCnxn#doIO:334", "peer:1", "read", 3))
    candidates.append(find("ClientCnxnSocketNIO#doIO:119", "client:reconnected",
                           "write", 1))
    if len({x["selector"] for x in candidates}) != 10:
        raise RuntimeError("pilot contains duplicate selectors")
    for index, job in enumerate(candidates, 1):
        job["pilot_id"] = f"upgrade-pilot-{index:03d}"
        job["priority"] = 10 if job["family"] == "client:initial:read" else 5
    manifest = {"case_id": "ZOOKEEPER-03", "phase": "session-upgrade-pilot",
                "original_junit": "org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower",
                "original_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
                "check": CHECK, "session_tag": "upgradedSession",
                "agent_sha256": receipt["agent_sha256"],
                "healthy_events_sha256": {"healthy-a": a_sha, "healthy-b": b_sha},
                "healthy_frontier_size": len(a), "max_trials": 10,
                "fault_type": "IOException", "jobs": candidates}
    OUTPUT.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"manifest": str(OUTPUT), "sha256": hashlib.sha256(
        OUTPUT.read_bytes()).hexdigest(), "jobs": len(candidates)}, sort_keys=True))


if __name__ == "__main__":
    main()
