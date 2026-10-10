#!/usr/bin/env python3
"""SHA-bound, state-only admission review for SOLR-31 v46.

The watcher and force-leader request execute on different threads. This review
records their common physical reader and ordered cache operands; it never
claims an observed Mallory graph edge between them.
"""

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path


COLLECTION = "forceleader_lower_terms_collection"
DOOR = ("org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
        "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:watcher")
TARGET = "org.apache.solr.handler.admin.CollectionsHandler#forceLeaderElection"
LINE = re.compile(
    r"MALLORY_SOLR31_STATE phase=(?P<phase>\w+) ts=(?P<ts>\d+) "
    r"node=(?P<node>\S+) epoch=(?P<epoch>\d+) thread_id=(?P<thread_id>\d+) "
    r"occurrence=(?P<occurrence>\S+) collection=(?P<collection>\S+) "
    r"reader_id=(?P<reader_id>\S+) .*?version=(?P<version>\S+) "
    r"leader=(?P<leader>\S+) leader_state=(?P<leader_state>\S+)")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def review(campaign: Path) -> dict:
    trial = campaign / "trials" / "r0000"
    campaign_result = json.loads((campaign / "result.json").read_text())
    trial_result = json.loads((trial / "result.json").read_text())
    junit = json.loads((trial / "junit-receipt.json").read_text())
    event_file = trial / "events.jsonl.gz"
    packed = event_file.read_bytes()
    raw = gzip.decompress(packed)
    events = [json.loads(line) for line in raw.splitlines()]
    diagnostics = [m.groupdict() for m in LINE.finditer((trial / "junit.log").read_text(errors="replace"))]
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               TARGET in e.get("site", "") and "@1476:" in e.get("site", "")]
    assert campaign_result.get("status") == "calibration_complete"
    assert junit.get("status") == "passed", junit
    assert len(targets) == 1, len(targets)
    target = targets[0]
    assert target.get("node") not in (None, "unknown", "client")
    assert isinstance(target.get("thread_id"), int)
    target_logs = [d for d in diagnostics if d["phase"] == "target" and
                   d["occurrence"] == target.get("occurrence") and
                   d["node"] == target.get("node") and
                   int(d["epoch"]) == target.get("epoch") and
                   d["collection"] == COLLECTION]
    assert len(target_logs) == 1, target_logs
    operand = target_logs[0]
    same_reader = [d for d in diagnostics if d["reader_id"] == operand["reader_id"] and
                   d["node"] == operand["node"] and d["epoch"] == operand["epoch"] and
                   d["collection"] == COLLECTION]
    assert not any(d["reader_id"] != operand["reader_id"] and
                   d["node"] == operand["node"] and d["epoch"] == operand["epoch"] and
                   d["collection"] == COLLECTION for d in diagnostics)
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") == DOOR and e.get("node") == target.get("node") and
             e.get("epoch") == target.get("epoch") and
             e.get("seq", 10**18) < target.get("seq", -1)]
    watches = []
    for door in doors:
        before = [d for d in same_reader if d["phase"] == "before" and
                  d["occurrence"] == door.get("occurrence")]
        after = [d for d in same_reader if d["phase"] == "after" and
                 d["occurrence"] == door.get("occurrence")]
        if len(before) != 1 or len(after) != 1:
            continue
        if int(before[0]["ts"]) >= int(after[0]["ts"]) or int(after[0]["ts"]) >= int(operand["ts"]):
            continue
        watches.append({"door_seq": door["seq"], "door_ordinal": door["door_ordinal"],
                        "occurrence": door["occurrence"], "thread_id": door["thread_id"],
                        "before": {k: before[0][k] for k in ("ts", "version", "leader", "leader_state")},
                        "after": {k: after[0][k] for k in ("ts", "version", "leader", "leader_state")}})
    assert watches, "no exact same-reader qualified watcher preceding target"
    return {"schema_version": 1, "case_id": "SOLR-31", "status": "state_timeline_admitted",
            "evidence_kind": "observed_state_timeline_not_graph_edge",
            "junit_status": junit["status"], "campaign_status": campaign_result["status"],
            "target": {"seq": target["seq"], "node": target["node"], "epoch": target["epoch"],
                       "thread_id": target["thread_id"], "occurrence": target["occurrence"],
                       "reader_id": operand["reader_id"], "version": operand["version"],
                       "leader": operand["leader"], "leader_state": operand["leader_state"]},
            "qualified_watches_before_target": watches,
            "sha256": {"campaign_result": file_sha(campaign / "result.json"),
                       "trial_result": file_sha(trial / "result.json"),
                       "junit_receipt": file_sha(trial / "junit-receipt.json"),
                       "junit_log": file_sha(trial / "junit.log"),
                       "events_gzip": sha(packed), "events_raw": sha(raw),
                       "sites": file_sha(trial / "sites.jsonl"),
                       "config": file_sha(campaign / "config.json")}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    evidence = review(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": evidence["status"], "target": evidence["target"],
                      "watch_count": len(evidence["qualified_watches_before_target"])}, sort_keys=True))


if __name__ == "__main__":
    main()
