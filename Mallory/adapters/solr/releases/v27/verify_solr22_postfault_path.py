#!/usr/bin/env python3
"""Bind exact post-fault HTTP-to-target paths to a terminal SOLR-22 pilot."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sys


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def paths_for_trial(trial: Path) -> dict:
    result_file = trial / "result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    event_file = trial / "events.jsonl.gz"
    trace = events(event_file)
    faults = [event for event in trace if event.get("type") == "FAULT_APPLIED"]
    sends = [event for event in trace if event.get("type") == "SEND"]
    receives = [event for event in trace if event.get("type") == "RECV"]
    targets = [event for event in trace if event.get("type") == "TARGET_CHECK"]
    paths = []
    for fault in faults:
        if fault.get("node") in (None, "unknown") or fault.get("epoch") is None:
            continue
        for send in sends:
            if (send.get("seq", -1) <= fault.get("seq", -1)
                    or send.get("node") != fault.get("node")
                    or send.get("epoch") != fault.get("epoch")
                    or send.get("thread") != fault.get("thread")
                    or not send.get("correlation")):
                continue
            linked = [recv for recv in receives
                      if recv.get("seq", -1) > send.get("seq", -1)
                      and recv.get("correlation") == send["correlation"]
                      and recv.get("node") not in (None, "unknown")
                      and recv.get("epoch") is not None]
            if len(linked) != 1:
                continue
            recv = linked[0]
            matched = [target for target in targets
                       if target.get("seq", -1) > recv.get("seq", -1)
                       and target.get("node") == recv.get("node")
                       and target.get("epoch") == recv.get("epoch")
                       and target.get("context") == recv.get("context")]
            if matched:
                paths.append({"fault_event": fault["id"],
                              "send_event": send["id"],
                              "receive_event": recv["id"],
                              "target_event": matched[0]["id"],
                              "correlation": send["correlation"],
                              "fault_actor": [fault["node"], fault["epoch"]],
                              "target_actor": [recv["node"], recv["epoch"]],
                              "fault_thread": fault["thread"],
                              "target_context": recv["context"]})
                break
    return {"trial": trial.name,
            "trial_result_sha256": sha256(result_file),
            "events_sha256": sha256(event_file),
            "all_faults_effective": result.get("feedback", {}).get("all_faults_effective"),
            "target_reached": result.get("feedback", {}).get("target_reached"),
            "paths": paths}


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    result_file = root / "result.json"
    audit_file = root / "offline-causal-audit.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    if result.get("case_id") != "SOLR-22" or result.get("status") not in (
            "budget_exhausted", "queue_exhausted"):
        raise ValueError("expected terminal SOLR-22 pilot")
    if not audit.get("report_gate_passed") or audit.get("campaign_result_sha256") != sha256(result_file):
        raise ValueError("SHA-bound frozen causal audit failed")
    trials = [paths_for_trial(trial) for trial in sorted((root / "trials").glob("r*"))]
    output = {"schema_version": 1, "case_id": "SOLR-22",
              "campaign_result_sha256": sha256(result_file),
              "offline_causal_audit_sha256": sha256(audit_file),
              "strict_postfault_http_paths": sum(bool(row["paths"]) for row in trials
                                                if row["all_faults_effective"] and row["target_reached"]),
              "trials": trials}
    destination = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else root / "postfault-http-path-review.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"path": str(destination),
                      "sha256": sha256(destination),
                      "strict_postfault_http_paths": output["strict_postfault_http_paths"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
