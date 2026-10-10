#!/usr/bin/env python3
"""Review exact SOLR-31 watcher faults without inventing cross-thread graph edges."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from verify_solr31_state_healthy import COLLECTION, DOOR, LINE, TARGET


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return sha(path.read_bytes())


def identity(event: dict) -> tuple:
    return (event.get("site"), event.get("node"), event.get("epoch"),
            event.get("occurrence"), event.get("thread_id"), event.get("door_ordinal"))


def review_trial(trial: Path, config: dict) -> dict:
    result_path = trial / "result.json"
    result = json.loads(result_path.read_text())
    plan = result["plan"]
    assert len(plan) == 1 and plan[0]["point"] == {
        "site": config["diagnostic_plan"]["site"],
        "node": config["diagnostic_plan"]["node"],
        "epoch": config["diagnostic_plan"]["epoch"],
        "door_ordinal": config["diagnostic_plan"]["door_ordinal"]}
    packed = (trial / "events.jsonl.gz").read_bytes()
    raw = gzip.decompress(packed)
    events = [json.loads(line) for line in raw.splitlines()]
    diagnostics = [m.groupdict() for m in LINE.finditer((trial / "junit.log").read_text(errors="replace"))]
    fault_id = plan[0]["fault_id"]
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED" and
               e.get("fault_id") == fault_id]
    matched = [e for e in events if e.get("type") == "FAULT_MATCHED" and
               e.get("fault_id") == fault_id]
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               TARGET in e.get("site", "") and "@1476:" in e.get("site", "")]
    witness = None
    if applied:
        assert len(applied) == len(matched) == 1
        fault, match = applied[0], matched[0]
        doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
                 identity(e) == identity(fault)]
        assert len(doors) == 1
        assert doors[0]["seq"] < match["seq"] < fault["seq"]
        assert fault["site"] == DOOR
        assert fault["exception_class"] == config["source_backed_state_candidate"]["exception_class"]
        before = [d for d in diagnostics if d["phase"] == "before" and
                  d["occurrence"] == fault["occurrence"] and d["node"] == fault["node"] and
                  int(d["epoch"]) == fault["epoch"] and d["collection"] == COLLECTION]
        after = [d for d in diagnostics if d["phase"] == "after" and
                 d["occurrence"] == fault["occurrence"] and d["node"] == fault["node"] and
                 int(d["epoch"]) == fault["epoch"] and d["collection"] == COLLECTION]
        assert len(before) == len(after) == 1
        assert before[0]["reader_id"] == after[0]["reader_id"]
        same_actor_targets = [e for e in targets if e.get("node") == fault["node"] and
                              e.get("epoch") == fault["epoch"] and e.get("seq", -1) > fault["seq"]]
        same_reader = []
        for target in same_actor_targets:
            operand = [d for d in diagnostics if d["phase"] == "target" and
                       d["occurrence"] == target["occurrence"] and
                       d["reader_id"] == before[0]["reader_id"] and
                       d["collection"] == COLLECTION and int(d["ts"]) > int(after[0]["ts"])]
            if len(operand) == 1:
                same_reader.append((target, operand[0]))
        if same_reader:
            target, operand = same_reader[0]
            throws = [e for e in events if e.get("type") == "TARGET_THROW" and
                      e.get("node") == target["node"] and
                      e.get("epoch") == target["epoch"] and
                      e.get("occurrence") == target["occurrence"] and
                      e.get("seq", -1) > target["seq"] and "@1477:" in e.get("site", "")]
            witness = {"door_seq": doors[0]["seq"], "fault_matched_seq": match["seq"],
                       "fault_applied_seq": fault["seq"], "fault_id": fault_id,
                       "node": fault["node"], "epoch": fault["epoch"],
                       "thread_id": fault["thread_id"], "door_ordinal": fault["door_ordinal"],
                       "watch_occurrence": fault["occurrence"], "reader_id": before[0]["reader_id"],
                       "before_version": before[0]["version"],
                       "before_leader_state": before[0]["leader_state"],
                       "after_version": after[0]["version"],
                       "after_leader_state": after[0]["leader_state"],
                       "target_seq": target["seq"], "target_occurrence": target["occurrence"],
                       "target_version": operand["version"],
                       "target_leader": operand["leader"],
                       "target_leader_state": operand["leader_state"],
                       "selected_throw_seqs": [e["seq"] for e in throws]}
    return {"trial": trial.name, "trial_result_sha256": digest(result_path),
            "junit_log_sha256": digest(trial / "junit.log"),
            "junit_receipt_sha256": digest(trial / "junit-receipt.json"),
            "events_gzip_sha256": sha(packed), "events_raw_sha256": sha(raw),
            "junit_status": result["junit_validation"]["status"],
            "feedback_status": result["feedback"]["status"],
            "all_faults_effective": result["feedback"].get("all_faults_effective"),
            "exact_applied_count": len(applied), "exact_target_count": len(targets),
            "same_reader_state_witness": witness}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = json.loads((args.campaign / "result.json").read_text())
    config = json.loads((args.campaign / "config.json").read_text())
    assert result["status"] == "diagnostic_budget_complete"
    rows = [review_trial(args.campaign / "trials" / f"r{i:04d}", config)
            for i in result["trial_ids"]]
    document = {"schema_version": 1, "case_id": "SOLR-31",
                "evidence_kind": "postfault_state_timeline_not_graph_edge",
                "result_sha256": digest(args.campaign / "result.json"),
                "config_sha256": digest(args.campaign / "config.json"),
                "healthy_receipt_sha256": config["diagnostic_plan"]["healthy_receipt_sha256"],
                "strict_same_reader_witness_count": sum(r["same_reader_state_witness"] is not None
                                                        for r in rows),
                "selected_throw_witness_count": sum(bool((r["same_reader_state_witness"] or {})
                                                         .get("selected_throw_seqs")) for r in rows),
                "trials": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"strict_same_reader_witness_count": document["strict_same_reader_witness_count"],
                      "selected_throw_witness_count": document["selected_throw_witness_count"]}))


if __name__ == "__main__":
    main()
