#!/usr/bin/env python3
"""Audit a settled HBASE-32 trial batch before mirroring it in the checklist."""

from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
EXPECTED = {
    "org/apache/hadoop/hbase/master/assignment/AssignmentManager",
    "org/apache/hadoop/hbase/master/assignment/ServerStateNode",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(start, end):
    checkpoint = json.loads((HERE / "supplemental-checkpoint.json").read_text())
    if len(checkpoint["trials"]) < end:
        raise RuntimeError("Batch includes an in-flight or absent trial")
    rows = []
    for number in range(start, end + 1):
        trial = checkpoint["trials"][number - 1]
        trial_id = f"s{number:03d}"
        if trial["id"] != trial_id:
            raise RuntimeError("Trial order changed: " + trial_id)
        log = HERE / "logs" / (trial_id + ".log.gz")
        woven, events, unknown = set(), 0, 0
        with gzip.open(log, "rt", errors="replace") as source:
            for line in source:
                if "HBASE32LOCK PROBE_WOVEN class=" in line:
                    woven.add(line.rsplit("class=", 1)[1].strip())
                if line.startswith("HBASE32LOCK seq="):
                    events += 1
                    unknown += "server=UNKNOWN" in line
        if woven != EXPECTED or events < 1000 or unknown:
            raise RuntimeError("Incomplete lock identity trace: " + trial_id)
        rows.append({
            "id": trial_id,
            "elapsed_seconds": trial["elapsed_seconds"],
            "disposition": trial["disposition"],
            "exit": trial["exit"],
            "junit": trial["junit"],
            "effective": trial["effective"],
            "log_sha256": sha256(log),
            "lock_events": events,
            "unknown_server_events": unknown,
            "woven_classes": sorted(woven),
        })
    report = {
        "case": "HBASE-32",
        "stage": "supplemental",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "trial_range": f"s{start:03d}-s{end:03d}",
        "attempts_completed_at_snapshot": end,
        "effective_at_snapshot": sum(t["effective"] for t in checkpoint["trials"][:end]),
        "new_exact_timeout_candidates": sum(
            t["review_candidate"] and t["exit"] == 124 and t["exact_b7"]
            for t in checkpoint["trials"][start - 1:end]),
        "new_bug": False,
        "lock_agent_jar_sha256": sha256(HERE / "diag-s203/agent.jar"),
        "rows": rows,
        "raw_logs_retained_locally": True,
    }
    artifact = HERE / f"evidence-lock-probe-s{start:03d}-s{end:03d}.json"
    if artifact.exists():
        raise RuntimeError("Refusing to overwrite an existing audit")
    artifact.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    result_path = CASE / "result.json"
    result = json.loads(result_path.read_text())
    supplemental = result["supplemental_stage"]
    if supplemental["new_bug"] or result["status"] != "campaign_budget_reached":
        raise RuntimeError("Unexpected case classification")
    supplemental["attempted_trials"] = end
    supplemental["effective_trials"] = report["effective_at_snapshot"]
    supplemental["elapsed_seconds"] = round(sum(
        t["elapsed_seconds"] or 0 for t in checkpoint["trials"][:end]), 2)
    supplemental["state"] = "running_after_bounded_diagnostic"
    supplemental["last_reviewed_trial"] = f"s{end:03d}"
    supplemental["last_reviewed_utc"] = report["created_utc"]
    supplemental["evidence"] = list(dict.fromkeys(
        supplemental["evidence"] + [str(artifact.relative_to(CASE))]))
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(artifact, report["effective_at_snapshot"], sha256(artifact))


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
