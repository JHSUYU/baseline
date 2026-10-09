#!/usr/bin/env python3
"""One fresh unchanged and one actor-aware healthy JUnit after V5 relocation.

These runs have no faults and never enter campaign state or its trial budget.
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from feedback import (CASES, actor_registrations, atomic_json,
                      checked_target_identity, events, fields, target_counts)
from migrate import MANIFEST, CAMPAIGN, CASE, digest, verify_manifest


RUN = CASE / "probe/run.py"
OUTPUT = CAMPAIGN / "node1-handoff-calibration"


def check_junit(directory: Path, *, original: bool) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    log = (directory / "junit.log").read_text(errors="replace")
    if (manifest["exit_code"] != 0 or manifest["original_classes"] != original or
            "SOLR103940_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR103940_JUNIT_ASSUMPTION" in log):
        raise RuntimeError(f"Healthy JUnit failed or skipped: {directory}")
    result = {"elapsed_seconds": manifest["elapsed_seconds"],
              "manifest_sha256": digest(directory / "manifest.json"),
              "junit_log_sha256": digest(directory / "junit.log"),
              "original_classes": original}
    if not original:
        trace = events(directory / "events.tsv")
        counts = target_counts(trace)
        registrations = actor_registrations(trace)
        roles = {item["role"] for item in registrations.values()}
        alias_io = [e for e in trace if e["kind"] == "IO_OBSERVED" and
                    len(e["parts"]) > 1 and e["parts"][1] == "/aliases.json" and
                    fields(e).get("actor", "").startswith("jetty:node")]
        if (any(counts[site] == 0 for site in CASES) or
                any(e["kind"] == "TARGET_EXCEPTION" for e in trace) or
                roles != {"node1", "node2", "node3", "node4"} or
                not checked_target_identity(trace) or not alias_io):
            raise RuntimeError("Healthy actor/target/alias I/O gate failed")
        result.update({"target_counts": counts, "registered_clients": len(registrations),
                       "roles": sorted(roles), "alias_io_registered": len(alias_io),
                       "trace_sha256": digest(directory / "events.tsv"),
                       "jacoco_sha256": digest(directory / "jacoco.exec")})
    return result


def main() -> None:
    frozen = json.loads(MANIFEST.read_text())
    verify_manifest(frozen)
    state = CAMPAIGN / "state.json"
    before = digest(state)
    if OUTPUT.exists():
        raise RuntimeError("handoff calibration already exists; preserve its raw evidence")
    OUTPUT.mkdir()
    results = {}
    for name, flags in (("original", ["--original"]),
                        ("actor", ["--coverage"])):
        directory = OUTPUT / name
        subprocess.run([sys.executable, str(RUN), str(directory), *flags], check=False)
        results[name] = check_junit(directory, original=name == "original")
        scratch = directory / "scratch"
        if scratch.exists():
            shutil.rmtree(scratch)
    if digest(state) != before:
        raise RuntimeError("Fault campaign state changed during healthy calibration")
    result = {"calibration_pass": True, "fault_budget_increment": 0,
              "checkpoint_state_sha256": before,
              "migration_manifest_sha256": digest(MANIFEST),
              "build_receipt_sha256": digest(CASE / "build-receipt.json"),
              "original": results["original"], "actor": results["actor"]}
    atomic_json(OUTPUT / "handoff-calibration.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
