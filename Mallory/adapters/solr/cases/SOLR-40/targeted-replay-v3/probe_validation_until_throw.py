#!/usr/bin/env python3
"""Run at most twelve new exact node3 replays, stopping at the first target throw."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT))
from Mallory.core import campaign  # noqa: E402
from probe_validation import PLAN_FILE, THROW_SITE  # noqa: E402

OUT = ROOT / "data/mallory/solr40_callee_probe_v3b_node0/SOLR-40"
LOCKS = ("solr-node0-v1.lock", "solr-source-graphchecker-8.11.4.lock")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(trial: Path, result: dict) -> dict:
    with gzip.open(trial / "events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    faults = [event for event in events if event["type"] == "FAULT_APPLIED"]
    throws = [event for event in events if event["type"] == "TARGET_THROW"
              and event.get("site") == THROW_SITE]
    catalog = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()]
    assert any(row.get("type") == "TARGET_THROW" and row.get("site") == THROW_SITE
               for row in catalog)
    assert result["site_catalog_validation"]["valid"]
    if result["plan"]:
        assert len(faults) == 1
        assert (faults[0]["node"], faults[0]["door_ordinal"]) == ("node3", 1)
    else:
        assert not faults
    log = (trial / "junit.log").read_text(errors="replace")
    return {
        "trial": trial.name,
        "fault_applied": bool(faults),
        "fault_event_id": faults[0]["id"] if faults else None,
        "target_throw_event_ids": [event["id"] for event in throws],
        "target_throw_classes": [event.get("exception_class") for event in throws],
        "mallory_target_exception_candidate": result["feedback"].get(
            "target_exception_candidate"),
        "junit_status": result.get("junit_validation", {}).get("status"),
        "junit_has_target_message": "Routed alias myalias appears to have been removed during request processing." in log,
        "trace_sha256": sha(trial / "events.jsonl.gz"),
        "junit_log_sha256": sha(trial / "junit.log"),
        "result_sha256": sha(trial / "result.json"),
    }


def main() -> None:
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    plan = json.loads(PLAN_FILE.read_text())["faults"]
    assert config["target"]["throw_site"] == THROW_SITE
    assert len(plan) == 1 and (plan[0]["point"]["node"],
                               plan[0]["point"]["door_ordinal"]) == ("node3", 1)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "classification": "prior-witness-seeded probe validation, not Mallory auto-discovery",
        "case_id": "SOLR-40",
        "config_sha256": sha(config_path),
        "sites_sha256": sha(HERE / "sites.json"),
        "source_plan": str(PLAN_FILE),
        "source_plan_sha256": sha(PLAN_FILE),
        "throw_site": THROW_SITE,
        "healthy_trials": 1,
        "max_fault_trials": 12,
        "stop_condition": "first raw TARGET_THROW at exact callthrow site",
    }
    manifest_path = OUT / "probe-validation-manifest.json"
    if manifest_path.exists():
        assert json.loads(manifest_path.read_text()) == manifest
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    rows = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        for trial_id in range(13):
            faults = [] if trial_id == 0 else plan
            trial = OUT / "trials" / f"r{trial_id:04d}"
            if (trial / "result.json").exists():
                result = json.loads((trial / "result.json").read_text())
                assert result.get("plan") == faults
            elif trial.exists():
                raise ValueError(f"incomplete trial requires review: {trial}")
            else:
                result = campaign._run_trial(config, OUT, trial_id, faults,
                                             lambda pid: None, None)
            row = inspect(trial, result)
            rows.append(row)
            summary = {"case_id": "SOLR-40", "rows": rows,
                       "completed_fault_trials": max(0, len(rows) - 1),
                       "target_throw_trials": sum(bool(row["target_throw_event_ids"])
                                                  for row in rows),
                       "complete": bool(row["target_throw_event_ids"] or trial_id == 12)}
            (OUT / "probe-validation-audit.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n")
            print(json.dumps({key: row[key] for key in (
                "trial", "fault_applied", "target_throw_event_ids",
                "mallory_target_exception_candidate", "junit_status",
                "junit_has_target_message")}, sort_keys=True), flush=True)
            if row["target_throw_event_ids"]:
                break
    finally:
        for handle in reversed(handles):
            handle.close()


if __name__ == "__main__":
    main()
