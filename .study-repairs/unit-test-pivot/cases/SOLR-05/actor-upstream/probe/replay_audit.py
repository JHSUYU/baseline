#!/usr/bin/env python3
"""Audit a separate POST-write diagnostic replay without changing fuzz counts."""

import hashlib
import json
from pathlib import Path
import re
import sys

from feedback import (atomic_json, checked_target_identity, events, fields,
                      strict_sequence, target_after, target_link)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    directory = Path(sys.argv[1]).resolve()
    manifest_path = directory / "manifest.json"
    trace_path = directory / "events.tsv"
    log_path = directory / "junit.log"
    manifest = json.loads(manifest_path.read_text())
    trace = events(trace_path)
    plan = manifest["faults"].split(";")
    applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    fault = applied[-1] if applied else None
    final_seq = fault["seq"] if fault else -1
    link = target_link(fault) if fault else None
    checks = [e for e in trace if e["kind"] == "TARGET_CHECK" and
              e["seq"] > final_seq and target_link(e) == link and
              fields(e).get("last_fault") == "F" + str(len(applied) - 1)]
    f = fields(fault) if fault else {}
    later_same_core = [e for e in trace if e["kind"] == "UPSTREAM_UPDATE_PENDING" and
                       e["seq"] > final_seq and fields(e).get("core") == f.get("core") and
                       fields(e).get("target_node") == f.get("target_node") and
                       fields(e).get("replica") != f.get("replica")]
    log = log_path.read_text(errors="replace")
    failure = re.search(r"SOLR05_V2_JUNIT_FAILURE[^\n]*", log)
    after, exception = target_after(trace, final_seq)
    receipt = {
        "diagnostic_only_not_fuzz_trial": True,
        "test": manifest["test"],
        "identity_version": manifest["identity_version"],
        "plan": plan,
        "junit_exit": manifest["exit_code"],
        "junit_failure": failure.group(0) if failure else None,
        "elapsed_seconds": manifest["elapsed_seconds"],
        "strict": strict_sequence(plan, trace) and checked_target_identity(trace),
        "selected_guard_after_fault": after["SOLR-05"],
        "selected_guard_throw": exception["SOLR-05"],
        "applied": len(applied),
        "fault": {"seq": final_seq, **f},
        "same_replica_guard": [{"seq": e["seq"], **fields(e)} for e in checks],
        "later_same_core_distinct_replica_pending": [
            {"seq": e["seq"], **fields(e)} for e in later_same_core],
        "sha256": {p.name: sha256(p) for p in (manifest_path, trace_path, log_path)},
    }
    atomic_json(directory / "replay-audit.json", receipt)
    print(json.dumps({key: receipt[key] for key in (
        "strict", "selected_guard_after_fault", "selected_guard_throw",
        "junit_exit", "junit_failure", "applied")}, sort_keys=True))


if __name__ == "__main__":
    main()
