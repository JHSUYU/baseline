#!/usr/bin/env python3
"""Seal SOLR-39's exact Aliases-reference healthy diagnostic."""

import hashlib
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/SOLR-39-aliasref-node1-healthy-v1"
REMOTE = RAW.with_suffix(".remote-sha-index.json")
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-39-aliasref-healthy-node1-v1"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    index = json.loads(REMOTE.read_text())
    for name, digest in index["files"].items():
        p = RAW / name
        if not p.is_file() or sha(p) != digest:
            raise RuntimeError(f"node1 raw changed: {name}")
    result = json.loads((RAW / "result.json").read_text())
    if (result.get("status") != "calibration_complete" or
            result.get("duration_seconds") != 29.016 or
            not result.get("healthy_seed_valid") or
            result.get("fault_trials_completed") != 0):
        raise RuntimeError("SOLR-39 healthy result changed")
    audit_script = BASE / "Mallory/adapters/solr/cases/SOLR-39/exact-alias-reference-node1-v1/audit_identity.py"
    audit = json.loads(subprocess.check_output(
        ["python3", "-B", str(audit_script), str(RAW / "trials/r0000")], text=True))
    if (audit.get("exact_target_checks") != 4 or audit.get("paired_field_events") != 0 or
            audit.get("status") != "no_qualified_path" or audit.get("fault_injection_performed")):
        raise RuntimeError("SOLR-39 identity audit changed")
    (RAW / "alias-reference-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    (RAW / "remote-sha-index.json").write_bytes(REMOTE.read_bytes())
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(p.exists() for p in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-39 healthy archive already exists")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as out:
        for name in sorted(members):
            out.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as saved:
        found = {}
        for item in saved:
            if item.isfile():
                name = item.name.removeprefix(f"{NAME}/")
                found[name] = hashlib.sha256(saved.extractfile(item).read()).hexdigest()
        if found != members:
            raise RuntimeError("archive member verification failed")
    data = {
        "schema_version": 1, "case_id": "SOLR-39", "kind": "healthy_only",
        "status": result["status"], "source_host": "node1",
        "source_path": index["source"], "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(index["files"]),
        "remote_sha_index_sha256": sha(REMOTE), "result_sha256": sha(RAW / "result.json"),
        "identity_audit_sha256": sha(RAW / "alias-reference-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members), "exact_target_checks": 4,
        "paired_field_events": 0, "fault_campaign_admitted": False,
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt_sha256": sha(receipt), "archive_sha256": sha(archive),
                      "members": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
