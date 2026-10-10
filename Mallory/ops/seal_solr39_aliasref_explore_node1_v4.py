#!/usr/bin/env python3
"""Seal SOLR-39's one-fault outside-closure exploratory node1 trial."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
NAME = "SOLR-39-exact-alias-reference-node1-v4"
RAW = BASE / "data/mallory/pilot_observations" / NAME
INDEX = RAW.with_suffix(".remote-sha256.txt")
GO = BASE / "Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-explore-node1-v4/admission-explore-node1.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
EXPECTED_GO = "4a4e758ad5cd848eeb9689dda095626a93963c77145fb3cd2c9ed6c7fe280369"
AGENT_SHA = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
SOURCE = "/users/ZhenyuLi/baseline/data/mallory/pilots/SOLR-39-exact-alias-reference-node1-v4"


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
    summary = load(RAW / "pilot-summary.json")
    audit = load(RAW / "fault-audit.json")
    result = load(RAW / "trials/r0001/result.json")
    config = load(RAW / "config.json")
    if (summary["case_id"] != "SOLR-39"
            or summary["closure_admission"] != "outside_closure_exploratory_only"
            or summary["status"] != "target_lost_or_manager_path_unqualified"
            or summary["fault_trials_completed"] != 1
            or summary["strict_injected_trials"] != 1
            or summary["strict_target_trials"] != 0
            or summary["exact_exception_trials"] != 0
            or summary["new_bug"] is not None
            or summary["admission_receipt_sha256"] != EXPECTED_GO
            or audit["healthy_event_time_graph_path_from_door"] is not False
            or audit["strict_fault_effective"] is not True
            or audit["matched_fault_events"] != 1
            or audit["applied_fault_events"] != 1
            or audit["unexpected_applied_faults"] != 0
            or audit["fault_node"] != "node1" or audit["fault_epoch"] != 0
            or audit["fault_door_seq"] >= audit["fault_applied_seq"]
            or audit["postfault_exact_target_checks_global"] != 3
            or audit["postfault_exact_target_checks_on_injected_actor"] != 0
            or audit["target_retained_same_manager"] is not False
            or audit["target_exception_candidate"] is not False
            or audit["identity_markers"] != 306
            or audit["paired_field_events"] != 306
            or audit["transform_errors"] != 0
            or result["feedback"]["all_faults_effective"] is not True
            or result["feedback"]["target_reached"] is not False
            or result["site_catalog_validation"]["valid"] is not True
            or result["junit_validation"]["status"] != "passed"
            or (result["junit_validation"]["tests"], result["junit_validation"]["failures"],
                result["junit_validation"]["errors"]) != (1, 0, 0)
            or config["budget"]["trials"] != 1
            or sha(Path(config["agent_jar"])) != AGENT_SHA):
        raise RuntimeError("SOLR-39 v4 exploratory outcome changed")

    shutil.copy2(INDEX, RAW / "remote-sha256.txt")
    shutil.copy2(GO, RAW / "admission-go.json")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("v4 evidence already sealed")
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
        "schema_version": 1, "case_id": "SOLR-39",
        "kind": "outside_closure_one_fault_exploratory_pilot",
        "source_host": "node1", "source_path": SOURCE,
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": summary["status"], "duration_seconds": summary["duration_seconds"],
        "junit_1_0_0": True, "fault_trials_completed": 1,
        "strict_injected_trials": 1, "strict_target_trials": 0,
        "exact_exception_trials": 0, "new_bug_confirmed": False,
        "healthy_event_time_graph_path_from_door": False,
        "postfault_exact_target_checks_global": 3,
        "postfault_exact_target_checks_on_injected_actor": 0,
        "fault_id": audit["planned_fault_id"],
        "fault_door_seq": audit["fault_door_seq"],
        "fault_applied_seq": audit["fault_applied_seq"],
        "prepublication_owner_ref": audit["prepublication_owner_ref"],
        "prepublication_aliases_ref": audit["prepublication_aliases_ref"],
        "prepublication_zk_version": audit["prepublication_zk_version"],
        "agent_sha256": AGENT_SHA, "admission_go_sha256": EXPECTED_GO,
        "remote_file_count": len(remote), "remote_sha_index_sha256": sha(INDEX),
        "pilot_summary_sha256": sha(RAW / "pilot-summary.json"),
        "fault_audit_sha256": sha(RAW / "fault-audit.json"),
        "trial_result_sha256": sha(RAW / "trials/r0001/result.json"),
        "trace_gzip_sha256": result["events_evidence"]["gzip_sha256"],
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
    }, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive), "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
