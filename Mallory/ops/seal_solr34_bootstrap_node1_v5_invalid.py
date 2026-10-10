#!/usr/bin/env python3
"""Seal SOLR-34 v5's pre-fault site-catalog failure without promoting it."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/pilot_observations/SOLR-34-fault-bootstrap-node1-v5-invalid"
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-34/fault-bootstrap-node1-v5/admission-bootstrap-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-34-fault-bootstrap-node1-v5-invalid"
EXPECTED_GO = "269b7cc46b8fb560ecca4aea0338eaa194d2f618e32ca4de503cae01929d8258"
REGION = ("org.apache.solr.servlet.CoordinatorHttpSolrCall#getCore"
          "(Lorg/apache/solr/servlet/CoordinatorHttpSolrCall$Factory;"
          "Lorg/apache/solr/servlet/HttpSolrCall;Ljava/lang/String;Z)"
          "Lorg/apache/solr/core/SolrCore;")


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
        raise RuntimeError("node1 SHA index or GO missing")
    result = load(RAW / "result.json")
    trial = load(RAW / "trials/r0000/result.json")
    sites = [json.loads(line) for line in (RAW / "trials/r0000/sites.jsonl").read_text().splitlines()]
    actual = {row.get("site") for row in sites}
    audit = {
        "schema_version": 1, "case_id": "SOLR-34",
        "status": "invalid_healthy_catalog_before_fault",
        "expected_new_throw": REGION + "@143:throw:1",
        "observed_new_throw": REGION + "@143:throw:2",
        "check_woven": REGION + "@139:branch:6" in actual,
        "rethrow_woven": REGION + "@140:throw:1" in actual,
        "new_throw_woven_with_different_ordinal": REGION + "@143:throw:2" in actual,
        "junit_passed": trial.get("junit_validation", {}).get("status") == "passed",
        "fault_trials_completed": result.get("fault_trials_completed"),
        "new_bug_confirmed": False,
    }
    if (result.get("status") != "healthy_seed_invalid"
            or result.get("fault_trials_completed") != 0
            or trial.get("case_audit", {}).get("status") != "exact_site_catalog_missing"
            or trial.get("site_catalog_validation", {}).get("missing_throw_site") != audit["expected_new_throw"]
            or not all(audit[key] for key in (
                "check_woven", "rethrow_woven", "new_throw_woven_with_different_ordinal", "junit_passed"))):
        raise RuntimeError("SOLR-34 v5 pre-fault outcome changed")
    (RAW / "catalog-failure-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("v5 invalid evidence already sealed")
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
        "schema_version": 1, "case_id": "SOLR-34", "kind": "failed_admission",
        "source_host": "node1", "source_path": "/users/ZhenyuLi/baseline/data/mallory/solr34_fault_bootstrap_node1_v5/SOLR-34",
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": audit["status"], "duration_seconds": result["duration_seconds"],
        "junit_1_0_0": True, "fault_trials_completed": 0, "new_bug_confirmed": False,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "go_sha256": EXPECTED_GO, "result_sha256": sha(RAW / "result.json"),
        "catalog_failure_audit_sha256": sha(RAW / "catalog-failure-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
