#!/usr/bin/env python3
"""Verify and seal SOLR-39's one-fault exact-reference node1 pilot."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/pilot_observations/SOLR-39-exact-alias-reference-node1-v3"
REMOTE_INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-fault-node1-v3/admission-one-fault-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-39-exact-alias-reference-fault-node1-v3"
GO_SHA = "4f36e1f60ecf0575070b5ac7e24909c486da2722703b9a1b4e2a6411ff860262"
AGENT_SHA = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    remote_files = {}
    for line in REMOTE_INDEX.read_text().splitlines():
        digest, name = line.split("  ", 1)
        name = name.removeprefix("./")
        if name in remote_files or not name or ".." in Path(name).parts:
            raise RuntimeError(f"invalid remote file name: {name}")
        remote_files[name] = digest
        if sha(RAW / name) != digest:
            raise RuntimeError(f"node1 raw differs: {name}")
    if not remote_files or sha(GO) != GO_SHA:
        raise RuntimeError("remote index or dispatch GO unavailable")
    summary = load(RAW / "pilot-summary.json")
    audit = load(RAW / "fault-audit.json")
    result = load(RAW / "trials/r0001/result.json")
    config = load(RAW / "config.json")
    if (summary.get("case_id") != "SOLR-39"
            or summary.get("status") != "target_lost_or_manager_path_unqualified"
            or summary.get("fault_trials_completed") != 1
            or summary.get("strict_injected_trials") != 1
            or summary.get("strict_target_trials") != 0
            or summary.get("exact_exception_trials") != 0
            or summary.get("new_bug") is not None
            or summary.get("admission_receipt_sha256") != GO_SHA
            or audit.get("strict_fault_effective") is not True
            or audit.get("matched_fault_events") != 1
            or audit.get("applied_fault_events") != 1
            or audit.get("unexpected_applied_faults") != 0
            or audit.get("target_retained_same_manager") is not False
            or audit.get("target_exception_candidate") is not False
            or audit.get("identity_markers") != audit.get("paired_field_events")
            or result.get("feedback", {}).get("all_faults_effective") is not True
            or result.get("feedback", {}).get("target_reached") is not False
            or result.get("site_catalog_validation", {}).get("valid") is not True
            or result.get("junit_validation", {}).get("status") != "passed"
            or result.get("junit_validation", {}).get("tests") != 1
            or config.get("budget", {}).get("trials") != 1
            or sha(Path(config["agent_jar"])) != AGENT_SHA):
        raise RuntimeError("SOLR-39 v3 pilot qualification changed")

    shutil.copy2(REMOTE_INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-39 v3 pilot evidence already sealed")
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
            raise RuntimeError("archive members differ from manifest")
    data = {
        "schema_version": 1, "case_id": "SOLR-39", "kind": "one_fault_pilot",
        "source_host": "node1",
        "source_path": "/users/ZhenyuLi/baseline/data/mallory/pilots/SOLR-39-exact-alias-reference-node1-v3",
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": summary["status"], "duration_seconds": summary["duration_seconds"],
        "junit_1_0_0": True, "fault_trials_completed": 1,
        "strict_injected_trials": 1, "strict_target_trials": 0,
        "exact_exception_trials": 0, "new_bug_confirmed": False,
        "fault_id": audit["planned_fault_id"],
        "fault_applied_seq": audit["fault_applied_seq"],
        "fault_door_seq": audit["fault_door_seq"],
        "agent_sha256": AGENT_SHA, "admission_go_sha256": GO_SHA,
        "remote_file_count": len(remote_files),
        "remote_sha_index_sha256": sha(REMOTE_INDEX),
        "pilot_summary_sha256": sha(RAW / "pilot-summary.json"),
        "fault_audit_sha256": sha(RAW / "fault-audit.json"),
        "trial_result_sha256": sha(RAW / "trials/r0001/result.json"),
        "trace_gzip_sha256": result["events_evidence"]["gzip_sha256"],
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive),
                      "receipt_sha256": sha(receipt),
                      "member_count": len(members),
                      "trace_gzip_sha256": data["trace_gzip_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
