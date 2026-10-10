#!/usr/bin/env python3
"""Seal the failed SOLR-39 Category healthy seed without admitting faults."""

import gzip
import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-39-category-healthy-node1-v1-invalid"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-39/next-test-mapping-v1/admission-healthy-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
EXPECTED_GO = "53f4d18d77b8a0b0a17421ea01f03173adc0cc5b62ed7542408a7d23f0c6198b"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/calibration_solr39_category_healthy_v1_node1/SOLR-39"
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1")
DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
        "#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")


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
            raise RuntimeError(f"invalid indexed name: {name}")
        remote[name] = digest
        if sha(RAW / name) != digest:
            raise RuntimeError(f"node1 raw differs: {name}")
    if not remote or sha(GO) != EXPECTED_GO:
        raise RuntimeError("raw SHA index or dispatch GO missing")
    result = load(RAW / "result.json")
    trial = load(RAW / "trials/r0000/result.json")
    pilot = load(RAW / "trials/r0000/pilot-result.json")
    junit_log = (RAW / "trials/r0000/junit.log").read_text(errors="replace")
    checks, doors, faults = [], [], []
    with gzip.open(RAW / "trials/r0000/events.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("type") == "TARGET_CHECK" and event.get("site") == CHECK:
                checks.append(event)
            if event.get("type") == "DOOR_OBSERVED" and event.get("site") == DOOR:
                doors.append(event)
            if event.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED"):
                faults.append(event)
    if (result["case_id"] != "SOLR-39"
            or result["status"] != "healthy_seed_invalid"
            or result["fault_trials_completed"] != 0
            or result["healthy_seed_valid"] is not False
            or result["new_bug"] is not None
            or trial["trial_id"] != 0 or trial["plan"]
            or trial["return_code"] != 1
            or trial["feedback"]["target_reached"] is not True
            or trial["feedback"]["target_threw"] is not False
            or trial["site_catalog_validation"]["valid"] is not True
            or pilot["junit"] != {"run": 1, "failures": 1, "ignored": 0}
            or "MALLORY_TEST_RESULT run=1 failures=1 ignored=0" not in junit_log
            or "Expected to find 1 docs but found 0" not in junit_log
            or len(checks) != 1 or checks[0]["node"] != "node1"
            or len(doors) != 13 or faults):
        raise RuntimeError("Category v1 invalid-healthy outcome changed")
    audit = {
        "schema_version": 1, "case_id": "SOLR-39",
        "status": "healthy_junit_failed_before_fault",
        "duration_seconds": result["duration_seconds"],
        "junit_tests": 1, "junit_failures": 1,
        "junit_failure": "Expected to find 1 docs but found 0",
        "exact_check_events": 1, "target_node": "node1",
        "typed_watcher_door_events": 13,
        "faults_matched_or_applied": 0,
        "fault_injection_performed": False,
        "healthy_admitted": False, "new_bug_confirmed": False,
    }
    (RAW / "invalid-healthy-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("Category v1 invalid evidence already sealed")
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
        "schema_version": 1, "case_id": "SOLR-39", "kind": "failed_healthy_seed",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        **audit,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "go_sha256": EXPECTED_GO, "result_sha256": sha(RAW / "result.json"),
        "invalid_healthy_audit_sha256": sha(RAW / "invalid-healthy-audit.json"),
        "trace_gzip_sha256": sha(RAW / "trials/r0000/events.jsonl.gz"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
