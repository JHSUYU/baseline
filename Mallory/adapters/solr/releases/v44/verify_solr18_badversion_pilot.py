#!/usr/bin/env python3
"""Check the exact SOLR-18 BadVersion fault-to-guard recovery chain."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from verify_solr18_badversion_admission import BAD_VERSION, DOOR, TARGET_PREFIX


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def identity(row: dict) -> tuple:
    return tuple(row.get(key) for key in ("site", "node", "epoch", "thread_id",
                                          "occurrence", "door_ordinal"))


def review(campaign: Path) -> dict:
    top_path = campaign / "result.json"
    config_path = campaign / "config.json"
    top = load(top_path)
    config = load(config_path)
    assert top["case_id"] == config["case_id"] == "SOLR-18"
    assert config["budget"]["trials"] == 1
    assert config["budget"]["max_faults_per_trial"] == 1
    assert config["site_file"].endswith("sites-v44-badversion.json")
    assert config["agent_properties"]["auto.io.doors"] is False
    assert top["fault_trials_completed"] == 1
    assert top["status"] in ("budget_exhausted", "queue_exhausted")

    trial_path = campaign / "trials/r0001/result.json"
    trial = load(trial_path)
    assert len(trial["plan"]) == 1
    plan = trial["plan"][0]
    point = plan["point"]
    assert point["site"] == DOOR
    assert plan["exception_class"] == BAD_VERSION
    events_path = campaign / "trials/r0001/events.jsonl.gz"
    compressed = events_path.read_bytes()
    raw = gzip.decompress(compressed)
    events = [json.loads(line) for line in raw.splitlines() if line]
    enter = {row["occurrence"]: row for row in events if row.get("type") == "REGION_ENTER"}
    exits = {row["occurrence"]: row for row in events if row.get("type") == "REGION_EXIT"}
    faults = [row for row in events if row.get("type") == "FAULT_APPLIED"
              and row.get("fault_id") == plan["fault_id"]]
    matches = [row for row in events if row.get("type") == "FAULT_MATCHED"
               and row.get("fault_id") == plan["fault_id"]]
    exact = len(faults) == len(matches) == 1
    door = None
    update = None
    target = None
    ordered = False
    if exact:
        fault, matched = faults[0], matches[0]
        door_rows = [row for row in events if row.get("type") == "DOOR_OBSERVED"
                     and identity(row) == identity(fault)]
        exact = (len(door_rows) == 1 and
                 all(fault.get(key) == point[key] for key in ("site", "node", "epoch", "door_ordinal")) and
                 fault.get("exception_class") == BAD_VERSION and
                 identity(fault) == identity(matched) and
                 isinstance(fault.get("thread_id"), int) and
                 fault["occurrence"] in enter and fault["occurrence"] in exits)
        if exact:
            door = door_rows[0]
            ordered = door["seq"] < matched["seq"] < fault["seq"] < exits[fault["occurrence"]]["seq"]
            updates = [row for row in events if row.get("type") == "REGION_ENTER"
                       and row.get("site", "").endswith("AliasesManager#update()Z")
                       and row.get("parent_id") == fault["occurrence"]
                       and row.get("node") == fault["node"]
                       and row.get("epoch") == fault["epoch"]
                       and row.get("thread_id") == fault["thread_id"]
                       and fault["seq"] < row["seq"] < exits[fault["occurrence"]]["seq"]]
            if updates:
                update = min(updates, key=lambda row: row["seq"])
                children = [row for row in events if row.get("type") == "REGION_ENTER"
                            and "AliasesManager#setIfNewer" in row.get("site", "")
                            and row.get("parent_id") == update["occurrence"]
                            and row.get("node") == fault["node"]
                            and row.get("epoch") == fault["epoch"]
                            and row.get("thread_id") == fault["thread_id"]
                            and update["seq"] < row["seq"] < exits[fault["occurrence"]]["seq"]]
                checks = [row for row in events if row.get("type") == "TARGET_CHECK"
                          and row.get("site", "").startswith(TARGET_PREFIX)
                          and row.get("occurrence") in {child["occurrence"] for child in children}
                          and row.get("node") == fault["node"]
                          and row.get("epoch") == fault["epoch"]
                          and row.get("thread_id") == fault["thread_id"]
                          and update["seq"] < row["seq"] < exits[fault["occurrence"]]["seq"]]
                if checks:
                    target = min(checks, key=lambda row: row["seq"])
    witness = bool(exact and ordered and update is not None and target is not None)
    target_throws = [row for row in events if row.get("type") == "TARGET_THROW"
                     and "AliasesManager#setIfNewer" in row.get("site", "")]
    return {
        "schema_version": 1, "case_id": "SOLR-18", "classification":
        "same_invocation_badversion_recovery_witness" if witness else "no_same_invocation_badversion_recovery_witness",
        "full_campaign_promoted": False, "new_bug_confirmed": False,
        "campaign_result_sha256": sha(top_path.read_bytes()),
        "config_sha256": sha(config_path.read_bytes()),
        "trial_result_sha256": sha(trial_path.read_bytes()),
        "events_gzip_sha256": sha(compressed), "events_raw_sha256": sha(raw),
        "events_raw_bytes": len(raw), "fault_id": plan["fault_id"],
        "plan_point": point, "exact_applied": exact, "strict_event_order": ordered,
        "same_invocation_recovery_witness": witness,
        "door_event_id": door.get("id") if door else None,
        "fault_event_id": faults[0].get("id") if faults else None,
        "update_event_id": update.get("id") if update else None,
        "target_event_id": target.get("id") if target else None,
        "junit_status": trial.get("junit_validation", {}).get("status"),
        "target_throw_event_ids": [row.get("id") for row in target_throws],
        "source_reason": (
            "A BadVersionException at setData is caught by applyModificationAndExportToZk; "
            "a descendant update() reads ZooKeeper before invoking setIfNewer. The event chain "
            "must remain within one apply occurrence, physical actor, epoch, and numeric thread."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    row = review(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: row[key] for key in ("classification", "exact_applied",
                                                "same_invocation_recovery_witness", "junit_status")}))


if __name__ == "__main__":
    main()
