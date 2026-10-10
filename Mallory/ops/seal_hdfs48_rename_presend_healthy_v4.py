#!/usr/bin/env python3
"""Seal the single HDFS-48 rename pre-send healthy observation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/HDFS-48-rename-presend-v4"
REMOTE_INDEX = Path(str(RAW) + ".remote-sha-index.json")
REMOTE_AUDIT = Path(str(RAW) + ".strict-audit.json")
QUALITY = BASE / "data/mallory/quality_reviews"
STRICT_AUDIT = QUALITY / "HDFS-48-rename-presend-v4.strict-audit.json"
OFFLINE_AUDIT = QUALITY / "HDFS-48-rename-presend-v4.offline-audit.json"
GO = BASE / "Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v4/admission-healthy-node2.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "HDFS-48-rename-presend-healthy-v4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main() -> None:
    index = json.loads(REMOTE_INDEX.read_text())
    if (index.get("source_host") != "node2" or
            index.get("source") != "/tmp/mallory-hdfs48-rename-presend-node2-healthy-v4" or
            len(index.get("files", {})) != 13):
        raise RuntimeError("unexpected remote source index")
    for name, expected in index["files"].items():
        path = RAW / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"node2 evidence changed: {name}")

    result = json.loads((RAW / "result.json").read_text())
    trial = json.loads((RAW / "trials/r0000/result.json").read_text())
    audit = json.loads(STRICT_AUDIT.read_text())
    remote_audit = json.loads(REMOTE_AUDIT.read_text())
    offline = json.loads(OFFLINE_AUDIT.read_text())
    go = json.loads(GO.read_text())
    if (result.get("status") != "calibration_complete" or
            result.get("healthy_seed_valid") is not True or
            trial.get("junit_validation", {}).get("status") != "passed" or
            (trial["junit_validation"].get("tests"),
             trial["junit_validation"].get("failures"),
             trial["junit_validation"].get("errors")) != (1, 0, 0)):
        raise RuntimeError("healthy JUnit/result changed")
    for name, report in (("local", audit), ("node2", remote_audit)):
        if (report.get("healthy_gate_passed") is not True or report.get("errors") or
                report.get("named_nn0_target_checks") != 1 or
                report.get("direct_client_setup_checks") != 1 or
                report.get("exact_named_rename_doors") != 1 or
                report.get("offline_causal_gate_passed") is not True or
                len(report.get("strict_method_correlation_path_witnesses", [])) != 1):
            raise RuntimeError(f"{name} strict healthy audit failed")
    if offline.get("report_gate_passed") is not True:
        raise RuntimeError("offline causal audit failed")
    if (go.get("go") is not True or go.get("case_id") != "HDFS-48" or
            go.get("host") != "node2" or go.get("mode") != "healthy" or
            go.get("config_sha256") != sha(RAW / "config.json")):
        raise RuntimeError("healthy dispatch receipt changed")

    shutil.copy2(REMOTE_INDEX, RAW / "remote-sha-index.json")
    shutil.copy2(STRICT_AUDIT, RAW / "strict-healthy-audit.json")
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{PREFIX}.tar.gz"
    manifest = ARCHIVES / f"{PREFIX}.members.json"
    receipt = ARCHIVES / f"{PREFIX}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("HDFS-48 v4 archive already exists")
    write_json(manifest, {"schema_version": 1, "files": members})
    with tarfile.open(archive, "w:gz") as tar:
        for name in sorted(members):
            tar.add(RAW / name, arcname=f"{PREFIX}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as tar:
        found = {item.name.removeprefix(f"{PREFIX}/"):
                 hashlib.sha256(tar.extractfile(item).read()).hexdigest()
                 for item in tar if item.isfile()}
    if found != members:
        raise RuntimeError("archive member verification failed")
    receipt_data = {
        "schema_version": 1, "case_id": "HDFS-48", "kind": "healthy_only",
        "status": result["status"], "source_host": "node2",
        "source_path": index["source"],
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(index["files"]),
        "remote_sha_index_sha256": sha(REMOTE_INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "strict_audit_sha256": sha(STRICT_AUDIT),
        "node2_strict_audit_sha256": sha(REMOTE_AUDIT),
        "offline_causal_audit_sha256": sha(OFFLINE_AUDIT),
        "admission_go_sha256": sha(GO),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
        "junit": {"tests": 1, "failures": 0, "errors": 0},
        "named_nn0_target_checks": 1,
        "exact_named_rename_doors": 1,
        "strict_method_correlation_path_witnesses": audit["strict_method_correlation_path_witnesses"],
        "fault_trials_completed": 0,
        "new_bug": False,
    }
    write_json(receipt, receipt_data)
    print(json.dumps({"receipt_sha256": sha(receipt), "archive_sha256": sha(archive),
                      "members": len(members), "healthy_gate_passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
