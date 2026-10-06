#!/usr/bin/env python3
"""Audit and archive the two HDFS-17967 outbound-path controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile


HERE = Path(__file__).resolve().parent
RUNS = {
    "write_healthy": "write-probe-01",
    "write_fault": "write-fault-01",
    "replace_healthy": "replace-probe-01",
    "replace_fault": "replace-fault-01",
}
FILES = ("manifest.json", "junit.log", "outbound_trace.tsv",
         "key_trace.jsonl", "jacoco.exec")


def summarize(name: str, directory: str) -> dict:
    path = HERE / directory
    manifest = json.loads((path / "manifest.json").read_text())
    events = [(fields[1], fields[2], int(fields[3]), fields[4])
              for row in (path / "outbound_trace.tsv").read_text().splitlines()
              if len(fields := row.split("\t")) == 5]
    key_events = [json.loads(row) for row in (path / "key_trace.jsonl").read_text().splitlines()]
    log = (path / "junit.log").read_text()
    path_name = "writeBlock" if name.startswith("write") else "replaceBlock"
    fault = name.endswith("fault")
    applied = [event for event in events if event[0] == "FAULT_APPLIED"]
    assert manifest["returncode"] == 0, name
    assert f"Original JUnit {manifest['test'].split('#')[1]}" in log, name
    assert any(event[0] == "SASL_ATTEMPT" and event[1] == path_name
               for event in events), name
    assert len(applied) == int(fault), name
    if fault:
        assert applied[0][1:3] == (path_name, 1), name
        assert f"HDFS-17967 control at outbound SASL setup {path_name}:1" in log, name
        failure = ("Exception transferring block" if path_name == "writeBlock"
                   else "reportedBlock move is failed")
        assert failure in log, name
    return {
        "directory": directory,
        "junit_returncode": manifest["returncode"],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "injected_outbound_faults": len(applied),
        "outbound_sasl_attempts_on_path": sum(event[0] == "SASL_ATTEMPT"
                                              and event[1] == path_name for event in events),
        "selected_allkeys_guard_checks": sum(event.get("event") == "TARGET_CHECK"
                                               for event in key_events),
        "selected_allkeys_guard_throws": sum(event.get("event") == "TARGET_THROW"
                                               for event in key_events),
        "operation_path_error_logged": bool(fault),
    }


def main() -> None:
    runs = {name: summarize(name, directory) for name, directory in RUNS.items()}
    archive = HERE / "evidence" / "hdfs17967-outbound-controls.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as out:
        for directory in RUNS.values():
            for filename in FILES:
                file = HERE / directory / filename
                if file.is_file():
                    out.add(file, arcname=f"{directory}/{filename}")
        out.add(HERE / "build" / "build.json", arcname="instrumentation/build.json")
    result = {
        "classification": "known_bug_path_control_not_new_bug",
        "upstream_issue": "HDFS-17967",
        "hadoop_version": "3.4.3",
        "runs": runs,
        "evidence_archive": archive.relative_to(HERE).as_posix(),
        "evidence_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "graphchecker_runtime": False,
        "note": "Synthetic outbound SASL exception; original JUnits recover at a higher layer. "
                "This control demonstrates missing local retries but not a new failure or "
                "an actual allKeys.get(keyId) miss."
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
