#!/usr/bin/env python3
"""SHA-seal the single HDFS-31 map-state diagnostic healthy run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/HDFS-31-map-state-v3"
REMOTE_INDEX = Path(str(RAW) + ".remote-sha-index.json")
AUDIT = Path(str(RAW) + ".map-audit.json")
GO = BASE / "Mallory/adapters/hdfs/cases/hdfs31-map-state-healthy-v3/admission-healthy-node2.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "HDFS-31-map-state-healthy-v3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main() -> None:
    index = json.loads(REMOTE_INDEX.read_text())
    if (index.get("source_host") != "node2" or
            index.get("source") != "/tmp/mallory-hdfs-31-map-healthy-v3" or
            len(index.get("files", {})) != 12):
        raise RuntimeError("unexpected node2 SHA index")
    for name, expected in index["files"].items():
        path = RAW / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"node2 raw changed: {name}")
    result = json.loads((RAW / "result.json").read_text())
    trial = json.loads((RAW / "trials/r0000/result.json").read_text())
    audit = json.loads(AUDIT.read_text())
    go = json.loads(GO.read_text())
    if (result.get("status") != "calibration_complete" or
            result.get("healthy_seed_valid") is not True or
            trial.get("junit_validation", {}).get("status") != "passed" or
            (trial["junit_validation"].get("tests"),
             trial["junit_validation"].get("failures"),
             trial["junit_validation"].get("errors")) != (1, 0, 0)):
        raise RuntimeError("healthy JUnit/result changed")
    if (audit.get("status") != "healthy_map_evidence" or
            audit.get("healthy_junit_passed") is not True or
            audit.get("named_target_events") != 1 or
            audit.get("matching_sampled_state_pairs") != 1 or
            audit.get("target_exception_candidate") is not False):
        raise RuntimeError("map diagnostic quality changed")
    if (go.get("go") is not True or go.get("case_id") != "HDFS-31" or
            go.get("config_sha256") != sha(RAW / "config.json")):
        raise RuntimeError("healthy dispatch GO changed")
    shutil.copy2(REMOTE_INDEX, RAW / "remote-sha-index.json")
    shutil.copy2(AUDIT, RAW / "map-state-audit.json")
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{PREFIX}.tar.gz"
    manifest = ARCHIVES / f"{PREFIX}.members.json"
    receipt = ARCHIVES / f"{PREFIX}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("HDFS-31 v3 archive already exists")
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
    write_json(receipt, {
        "schema_version": 1, "case_id": "HDFS-31", "kind": "healthy_only",
        "status": result["status"], "source_host": "node2", "source_path": index["source"],
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(index["files"]),
        "remote_sha_index_sha256": sha(REMOTE_INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "map_state_audit_sha256": sha(AUDIT),
        "admission_go_sha256": sha(GO),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
        "junit": {"tests": 1, "failures": 0, "errors": 0},
        "named_target_events": 1,
        "matching_sampled_state_pairs": 1,
        "observed_causal_removal_path": False,
        "fault_trials_completed": 0,
        "new_bug": False,
    })
    print(json.dumps({"receipt_sha256": sha(receipt), "archive_sha256": sha(archive),
                      "members": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
