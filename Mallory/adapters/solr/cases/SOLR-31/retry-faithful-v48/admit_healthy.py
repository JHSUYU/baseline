#!/usr/bin/env python3
"""Bind one passed SOLR-31 healthy run to a same-reader retry occurrence."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from build_plan import CLASS_SHA, COLLECTION, PATH, SITE


def fields(line: str) -> dict:
    return dict(part.split("=", 1) for part in line.split() if "=" in part)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def admit(trial: Path) -> dict:
    junit = json.loads((trial / "junit-receipt.json").read_text())
    result = json.loads((trial / "result.json").read_text())
    feedback = result.get("feedback", {})
    if junit.get("status") != "passed" or junit.get("tests") != 1 \
            or feedback.get("status") != "observed" \
            or feedback.get("target_reached") is not True \
            or feedback.get("target_exception_candidate") is not False:
        raise ValueError("healthy JUnit and target gate did not pass")

    log = (trial / "junit.log").read_text(errors="replace")
    marker = "MALLORY_SOLR31_RETRY_WEAVE status=ok matches=1 original_sha256=" + CLASS_SHA
    if log.count(marker) != 1:
        raise ValueError("pinned SolrZkClient weave marker missing or duplicated")
    targets = [fields(line) for line in log.splitlines()
               if "MALLORY_SOLR31_STATE phase=target" in line
               and "collection=" + COLLECTION in line]
    if len(targets) != 1:
        raise ValueError("exactly one named target operand is required")
    target = targets[0]
    reads = [fields(line) for line in log.splitlines()
             if "MALLORY_SOLR31_RETRY phase=" in line
             and "collection=" + COLLECTION in line and "path=" + PATH in line]
    attempts = [row for row in reads if row.get("phase") == "attempt"
                and row.get("attempt") == "1"
                and row.get("node") == target.get("node")
                and row.get("epoch") == target.get("epoch")
                and row.get("reader_id") == target.get("reader_id")
                and int(row["ts"]) < int(target["ts"])]
    if not attempts:
        raise ValueError("no same-server-reader low-level attempt before target")
    selected = max(attempts, key=lambda row: int(row["ts"]))
    successes = [row for row in reads if row.get("phase") == "success"
                 and row.get("node") == selected["node"]
                 and row.get("epoch") == selected["epoch"]
                 and row.get("reader_id") == selected["reader_id"]
                 and row.get("read_ordinal") == selected["read_ordinal"]
                 and row.get("occurrence") == selected["occurrence"]
                 and row.get("session_id") == selected["session_id"]
                 and row.get("stable_session") == "true"]
    if len(successes) != 1 or successes[0].get("attempt") != "1":
        raise ValueError("selected healthy low-level operation did not succeed once")
    if selected.get("stable_session") != "true" or not 2 <= int(selected["retry_count"]) <= 16:
        raise ValueError("unbound or unsupported retry budget/session")

    events_file = trial / "events.jsonl.gz"
    door = False
    with gzip.open(events_file, "rt") as source:
        for line in source:
            row = json.loads(line)
            if row.get("type") == "DOOR_OBSERVED" and row.get("site") == SITE \
                    and row.get("node") == selected["node"] \
                    and row.get("epoch") == int(selected["epoch"]):
                door = True
                break
    if not door:
        raise ValueError("selected low-level door absent from typed trace")
    return {
        "schema_version": 1,
        "status": "retry_lowlevel_healthy_admitted",
        "binding": {
            "site": SITE, "collection": COLLECTION, "path": PATH,
            "original_class_sha256": CLASS_SHA,
            "node": selected["node"], "epoch": int(selected["epoch"]),
            "watch_read_ordinal": int(selected["read_ordinal"]),
            "reader_id": selected["reader_id"], "client_id": selected["client_id"],
            "keeper_id": selected["keeper_id"], "session_id": int(selected["session_id"]),
            "retry_count": int(selected["retry_count"]),
            "occurrence": selected["occurrence"],
            "healthy_stat_version": int(successes[0]["stat_version"]),
            "target_reader_id": target["reader_id"],
            "target_version": int(target["version"]),
            "target_leader": target["leader"],
        },
        "evidence": {name: sha(trial / name) for name in
                     ("junit.log", "junit-receipt.json", "result.json", "events.jsonl.gz")},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("receipt output must be fresh")
    value = admit(args.trial)
    args.out.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps(value["binding"], sort_keys=True))


if __name__ == "__main__":
    main()
