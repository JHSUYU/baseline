#!/usr/bin/env python3
"""Postprocess one fresh SOLR-40 v2 healthy trace without admitting faults."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import gate_v2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"))
from Mallory.core.events import Trace  # noqa: E402

NODE_BINDING = re.compile(r"MALLORY_SOLR_NODE logical=(\S+) physical=(\S+) epoch=(\d+)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out: Path) -> dict:
    trial = out / "trials/r0000"
    result_file, trial_file = out / "result.json", trial / "result.json"
    result, trial_result = json.loads(result_file.read_text()), json.loads(trial_file.read_text())
    trace_file, log = trial / "events.jsonl.gz", trial / "junit.log"
    with gzip.open(trace_file, "rt", encoding="utf-8") as stream:
        events = tuple(json.loads(line) for line in stream if line.strip())
    config = json.loads((HERE / "config.json").read_text())
    fb = gate_v2.analyze(Trace(events), config["target"], [],
                         return_code=trial_result.get("return_code"),
                         timed_out=trial_result.get("timed_out", False),
                         allow_local_timeline_doors=False,
                         reject_coarse_roots=True, require_event_time_paths=True)
    named = {(node, int(epoch)): physical for node, physical, epoch in
             NODE_BINDING.findall(log.read_text())}
    checks = [row for row in events if row.get("type") == "TARGET_CHECK" and
              row.get("site") == gate_v2.CHECK and
              (row.get("node"), row.get("epoch")) in named]
    selected = [row for row in fb["doors"] if
                (row["point"].get("node"), row["point"].get("epoch")) in named]
    junit = result.get("healthy_junit_validation", {})
    ready = (junit.get("status") == "passed" and junit.get("tests") == 1 and
             trial_result.get("return_code") == 0 and
             not trial_result.get("timed_out") and
             fb.get("target_threw") is False and bool(checks) and bool(selected) and
             fb.get("target_identity_complete") is True and
             fb.get("target_region_present") is True)
    return {"schema_version": 1, "case_id": "SOLR-40", "mode": "healthy_only",
            "status": "fresh_observed_handoff_for_review" if ready else
                      "fresh_handoff_not_proven",
            "eligible_for_full_review": bool(ready), "full_campaign_go": False,
            "junit_status": junit.get("status"), "junit_tests": junit.get("tests"),
            "named_exact_target_checks": len(checks),
            "named_observed_watcher_doors": len(selected),
            "exact_reference_witnesses": {row["event_id"]:
                fb["watcher_exact_reference_witnesses"][row["event_id"]]
                for row in selected},
            "trace_sha256": sha(trace_file), "junit_log_sha256": sha(log),
            "trial_result_sha256": sha(trial_file), "result_sha256": sha(result_file)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(args.output)
    (args.output / "handoff-audit.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in
                      ("case_id", "status", "named_exact_target_checks",
                       "named_observed_watcher_doors", "full_campaign_go")}, sort_keys=True))


if __name__ == "__main__":
    main()
