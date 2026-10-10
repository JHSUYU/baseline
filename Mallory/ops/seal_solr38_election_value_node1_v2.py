#!/usr/bin/env python3
"""Verify and seal SOLR-38's node1 election-value healthy diagnostic."""

import hashlib
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/SOLR-38-election-value-node1-v2"
ADAPTER = RAW.with_suffix(".adapter")
RAW_INDEX = RAW.with_suffix(".remote-sha256.txt")
ADAPTER_INDEX = RAW.with_suffix(".adapter-remote-sha256.txt")
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-38-election-value-healthy-node1-v2"
AGENT = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
GO = "62b2ae44514b8a3c18c2fe144953c329200ed64e1afedf079a0d4e2548c46b65"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_index(root, index):
    files = {}
    for line in index.read_text().splitlines():
        digest, name = line.split("  ", 1)
        name = name.removeprefix("./")
        if name in files or not name or ".." in Path(name).parts:
            raise RuntimeError(f"invalid remote file name: {name}")
        files[name] = digest
        if sha(root / name) != digest:
            raise RuntimeError(f"node1 file differs: {name}")
    if not files:
        raise RuntimeError("empty node1 SHA index")
    return files


def load(path):
    return json.loads(path.read_text())


def main():
    raw_files = verify_index(RAW, RAW_INDEX)
    adapter_files = verify_index(ADAPTER, ADAPTER_INDEX)
    result = load(RAW / "result.json")
    trial = load(RAW / "trials/r0000/result.json")
    pilot = load(RAW / "trials/r0000/pilot-result.json")
    config = load(RAW / "config.json")
    audit = load(RAW / "quality-audit.json")
    build = load(ADAPTER / "build-receipt.json")
    adapter_sha = sha(ADAPTER / "mallory-solr-adapter-v2.jar")
    junit = trial.get("junit_validation", {})
    if (result.get("status") != "calibration_complete"
            or result.get("fault_trials_completed") != 0
            or result.get("healthy_seed_valid") is not True
            or result.get("runtime_attestation", {}).get("valid") is not True
            or (junit.get("status"), junit.get("tests"), junit.get("failures"),
                junit.get("errors"), junit.get("skipped")) != ("passed", 1, 0, 0, 0)
            or pilot.get("agent_sha256") != AGENT
            or pilot.get("adapter_sha256") != adapter_sha
            or build.get("adapter_sha256") != adapter_sha
            or config.get("mapping", {}).get("value_diagnostic_adapter_sha256") != adapter_sha
            or audit.get("exact_target_checks") != 12
            or audit.get("value_witness_count") != 12
            or audit.get("strict_observed_paths") != 0
            or audit.get("full_promotion_authorized") is not False):
        raise RuntimeError("SOLR-38 v2 healthy diagnostic changed")

    for source, destination in ((RAW_INDEX, RAW / "remote-sha256.txt"),
                                (ADAPTER_INDEX, RAW / "adapter-remote-sha256.txt")):
        shutil.copy2(source, destination)
    saved_adapter = RAW / "adapter"
    if saved_adapter.exists():
        raise RuntimeError("adapter already copied into observation")
    shutil.copytree(ADAPTER, saved_adapter)
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-38 v2 evidence already sealed")
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
            raise RuntimeError("archive member verification failed")
    data = {
        "schema_version": 1, "case_id": "SOLR-38", "kind": "healthy_only",
        "source_host": "node1",
        "source_path": "/users/ZhenyuLi/baseline/data/mallory/solr38_election_value_healthy_v2_node1/SOLR-38/healthy",
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": result["status"], "duration_seconds": result["duration_seconds"],
        "junit_1_0_0": True, "fault_trials": 0,
        "agent_sha256": AGENT, "adapter_sha256": adapter_sha,
        "admission_go_sha256": GO,
        "remote_file_count": len(raw_files), "adapter_file_count": len(adapter_files),
        "remote_sha_index_sha256": sha(RAW_INDEX),
        "adapter_remote_sha_index_sha256": sha(ADAPTER_INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "quality_audit_sha256": sha(RAW / "quality-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members), "exact_target_checks": 12,
        "value_witness_count": 12, "strict_observed_paths": 0,
        "full_campaign_admitted": False,
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive),
                      "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
