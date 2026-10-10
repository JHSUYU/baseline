#!/usr/bin/env python3
"""Seal the HDFS-33 map-window healthy observation after node2 SHA copy."""

import hashlib
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/HDFS-33-map-window-v1"
REMOTE_INDEX = RAW.with_suffix(".remote-sha-index.json")
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "HDFS-33-map-window-healthy-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    remote = json.loads(REMOTE_INDEX.read_text())
    for name, expected in remote["files"].items():
        path = RAW / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"remote evidence changed: {name}")
    result = json.loads((RAW / "result.json").read_text())
    if result.get("status") != "calibration_complete" or not result.get("healthy_seed_valid"):
        raise RuntimeError("healthy observation is not terminal and valid")
    audit_script = BASE / "Mallory/adapters/hdfs/cases/hdfs33-map-window-healthy-v1/audit_healthy.py"
    audit = json.loads(subprocess.check_output(
        ["python3", "-B", str(audit_script), str(RAW / "trials/r0000")], text=True))
    if not (audit["junit_1_0_0"] and audit["named_target_checks"] == 2
            and audit["remove_method_events"] == 0 and not audit["fault_campaign_admitted"]):
        raise RuntimeError("HDFS-33 quality result changed")
    (RAW / "map-window-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    (RAW / "remote-sha-index.json").write_bytes(REMOTE_INDEX.read_bytes())
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{PREFIX}.tar.gz"
    manifest = ARCHIVES / f"{PREFIX}.members.json"
    receipt = ARCHIVES / f"{PREFIX}.receipt.json"
    if archive.exists() or manifest.exists() or receipt.exists():
        raise RuntimeError("archive already exists")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as tar:
        for name in sorted(members):
            tar.add(RAW / name, arcname=f"{PREFIX}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as tar:
        found = {}
        for item in tar:
            if item.isfile():
                name = item.name.removeprefix(f"{PREFIX}/")
                found[name] = hashlib.sha256(tar.extractfile(item).read()).hexdigest()
        if found != members:
            raise RuntimeError("archive member verification failed")
    data = {
        "schema_version": 1, "case_id": "HDFS-33", "kind": "healthy_only",
        "status": result["status"], "source_host": "node2",
        "source_path": remote["source"],
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(remote["files"]),
        "remote_sha_index_sha256": sha(REMOTE_INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "map_window_audit_sha256": sha(RAW / "map-window-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
        "junit_1_0_0": audit["junit_1_0_0"],
        "named_target_checks": audit["named_target_checks"],
        "remove_method_events": audit["remove_method_events"],
        "fault_campaign_admitted": False,
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(receipt), "receipt_sha256": sha(receipt),
                      "archive_sha256": sha(archive), "members": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
