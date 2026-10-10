#!/usr/bin/env python3
"""Seal SOLR-34 v6's bounded, target-absent fault bootstrap."""

import gzip
import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-34-fault-bootstrap-node1-v6"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-34/fault-bootstrap-node1-v6/admission-bootstrap-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
EXPECTED_GO = "6df5d75c2cebdd77cf329e6d631945f23ccd330819bd0036df14db8b1525ec33"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/solr34_fault_bootstrap_node1_v6/SOLR-34"
RESOURCE = "/collections/.sys.COORDINATOR-COLL-conf/state.json"


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
    if (result["case_id"] != "SOLR-34"
            or result["status"] != "budget_exhausted"
            or result["fault_trials_completed"] != 12
            or result["exact_exception_trials"] != 0
            or result["target_reached_trials"] != 0
            or result["new_bug"] is not None):
        raise RuntimeError("terminal result changed")

    trials = []
    for i in range(13):
        trial = RAW / f"trials/r{i:04d}"
        record = load(trial / "result.json")
        audit = record["case_audit"]
        junit = record["junit_validation"]
        if (record["trial_id"] != i or junit["status"] != "passed"
                or (junit["tests"], junit["failures"], junit["errors"]) != (1, 0, 0)):
            raise RuntimeError(f"trial/JUnit changed: {i}")
        counts = {"TARGET_CHECK": 0, "TARGET_THROW": 0,
                  "FAULT_MATCHED": 0, "FAULT_APPLIED": 0}
        with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row.get("type") in counts:
                    counts[row["type"]] += 1
        plan = record["plan"]
        if (counts["TARGET_CHECK"] or counts["TARGET_THROW"]
                or any(fault["point"].get("resource") != RESOURCE
                       or fault["point"].get("node") != "node5"
                       or fault["point"].get("epoch") != 0 for fault in plan)):
            raise RuntimeError(f"target/path changed: {i}")
        if i == 0:
            if (plan or audit["status"] != "eligible_healthy_bootstrap"
                    or audit["qualified_path_doors"] != 6):
                raise RuntimeError("healthy bootstrap changed")
        elif i == 11:
            if (len(plan) != 2 or audit["status"] != "fault_not_applied_once"
                    or counts["FAULT_APPLIED"] != 1):
                raise RuntimeError("one unmatched two-fault plan changed")
        elif (audit["status"] != "attributed" or audit["valid"] is not True
              or audit["target_after_fault"] is not False
              or audit["target_outcome"] != "target_absent"
              or len(audit["faults"]) != len(plan)
              or counts["FAULT_MATCHED"] != len(plan)
              or counts["FAULT_APPLIED"] != len(plan)):
            raise RuntimeError(f"attributed fault outcome changed: {i}")
        trials.append({"trial_id": i, "elapsed_seconds": record["elapsed_seconds"],
                       "junit_status": junit["status"], "faults_planned": len(plan),
                       "faults_applied": counts["FAULT_APPLIED"],
                       "audit_status": audit["status"],
                       "exact_check_events": counts["TARGET_CHECK"],
                       "exact_throw_events": counts["TARGET_THROW"],
                       "target_after_fault": audit.get("target_after_fault"),
                       "fault_ordinals": [fault["point"]["door_ordinal"] for fault in plan]})
    outcome = {
        "schema_version": 1, "case_id": "SOLR-34",
        "status": "bounded_bootstrap_budget_exhausted_target_absent",
        "duration_seconds": result["duration_seconds"],
        "healthy_qualified_path_doors": 6,
        "fault_trials_completed": 12,
        "fully_attributed_fault_trials": 11,
        "partially_applied_fault_trials": 1,
        "total_faults_applied": sum(t["faults_applied"] for t in trials),
        "exact_target_check_events": 0,
        "exact_target_throw_events": 0,
        "junit_passed_trials": 13,
        "new_bug_confirmed": False,
        "check_completed": False,
        "trials": trials,
    }
    (RAW / "bootstrap-outcome-audit.json").write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("v6 evidence already sealed")
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
        "schema_version": 1, "case_id": "SOLR-34", "kind": "bounded_bootstrap",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        **{key: value for key, value in outcome.items() if key != "trials"},
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "go_sha256": EXPECTED_GO, "result_sha256": sha(RAW / "result.json"),
        "bootstrap_outcome_audit_sha256": sha(RAW / "bootstrap-outcome-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
