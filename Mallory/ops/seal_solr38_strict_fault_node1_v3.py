#!/usr/bin/env python3
"""Seal the bounded SOLR-38 strict-path pilot as evidence, not a completed check."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-38-strict-fault-node1-v3"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-38/election-strict-pilot-node1-v3/admission-strict-pilot-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
EXPECTED_GO = "3ca21aee57e64133f662e659247a3af77bea96e79e659546e4d5f0082a2b78d6"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/solr38_strict_fault_v3_node1/SOLR-38/pilot"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    remote = {}
    for line in INDEX.read_text().splitlines():
        digest, name = line.split("  ", 1)
        name = name.removeprefix("./")
        if name in remote or not name or ".." in Path(name).parts:
            raise RuntimeError(f"invalid remote index path: {name}")
        remote[name] = digest
        if sha(RAW / name) != digest:
            raise RuntimeError(f"node1 raw differs: {name}")
    if not remote or sha(GO) != EXPECTED_GO:
        raise RuntimeError("raw SHA index or dispatch GO missing")

    result = load(RAW / "result.json")
    audit = load(RAW / "offline-causal-audit.json")
    trials = [load(RAW / f"trials/r{i:04d}/result.json") for i in range(3)]
    audit_trials = audit["trials"]
    if (result["case_id"] != "SOLR-38" or result["status"] != "queue_exhausted"
            or result["fault_trials_completed"] != 2
            or result["exact_exception_trials"] != 0
            or result["new_bug"] is not None
            or audit["campaign_result_sha256"] != sha(RAW / "result.json")
            or audit["healthy_closure_proven"] is not True
            or audit["report_gate_passed"] is not False
            or audit["trial_count"] != 3 or len(audit_trials) != 3
            or any(trial["junit_validation"]["status"] != "passed"
                   or trial["junit_validation"]["tests"] != 1
                   or trial["junit_validation"]["failures"] != 0
                   or trial["junit_validation"]["errors"] != 0
                   for trial in trials)
            or any(len(item["faults"]) != 1
                   or item["faults"][0]["matched_receipts"] != 1
                   or item["faults"][0]["applied_receipts"] != 1
                   or item["same_actor_target_after_fault"] is not False
                   or item["same_actor_target_followups"]
                   for item in audit_trials[1:])
            or audit_trials[1]["closure_edges_consistent"] is not False):
        raise RuntimeError("SOLR-38 v3 terminal pilot outcome changed")

    outcome = {
        "schema_version": 1,
        "case_id": "SOLR-38",
        "status": "bounded_pilot_not_check_completion",
        "terminal_status": result["status"],
        "duration_seconds": result["duration_seconds"],
        "healthy_strict_closure_proven": True,
        "fault_trials_completed": 2,
        "exact_typed_matched_and_applied_trials": 2,
        "same_actor_target_after_fault_trials": 0,
        "exact_target_exception_trials": 0,
        "junit_passed_trials": 3,
        "offline_report_gate_passed": False,
        "offline_gate_failure": "r0001 closure edge fingerprint mismatch; no same-actor postfault target",
        "new_bug_confirmed": False,
    }
    (RAW / "pilot-outcome-audit.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-38 v3 evidence already sealed")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as output:
        for name in sorted(members):
            output.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as saved:
        found = {}
        for item in saved:
            if item.isfile():
                name = item.name.removeprefix(f"{NAME}/")
                found[name] = hashlib.sha256(saved.extractfile(item).read()).hexdigest()
        if found != members:
            raise RuntimeError("archive member mismatch")
    receipt.write_text(json.dumps({
        "schema_version": 1, "case_id": "SOLR-38", "kind": "bounded_pilot",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        **outcome,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "go_sha256": EXPECTED_GO, "result_sha256": sha(RAW / "result.json"),
        "offline_causal_audit_sha256": sha(RAW / "offline-causal-audit.json"),
        "pilot_outcome_audit_sha256": sha(RAW / "pilot-outcome-audit.json"),
        "trace_sha256_by_trial": {f"r{i:04d}": sha(RAW / f"trials/r{i:04d}/events.jsonl.gz")
                                  for i in range(3)},
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
