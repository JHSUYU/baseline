#!/usr/bin/env python3
"""Verify and seal the SOLR-34 v4 node1 healthy observation."""

import hashlib
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/SOLR-34-path-node1-v4"
REMOTE_INDEX = RAW.with_suffix(".remote-sha256.txt")
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-34-path-healthy-node1-v4"
AGENT = "b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4"
GO = "1d6056f19c598366354f787173d782104e0765cf04035960d823f4b23b7c08eb"


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
    if not remote_files:
        raise RuntimeError("empty node1 raw index")

    result = load(RAW / "result.json")
    pilot = load(RAW / "trials/r0000/pilot-result.json")
    junit = load(RAW / "trials/r0000/junit-receipt.json")
    quality = load(RAW / "quality-audit.json")
    if (result.get("status") != "calibration_complete"
            or result.get("fault_trials_completed") != 0
            or result.get("bootstrap_seed_valid") is not True
            or result.get("healthy_seed_valid") is not False
            or pilot.get("agent_sha256") != AGENT
            or pilot.get("path_agent_preflight", {}).get("agent_sha256") != AGENT
            or (junit.get("status"), junit.get("tests"), junit.get("failures"),
                junit.get("errors"), junit.get("skipped")) != ("passed", 1, 0, 0, 0)
            or quality.get("status") != "passed_path_bootstrap"
            or quality.get("typed_path_door_count", 0) < 1
            or quality.get("target_check_count") != 0
            or quality.get("full_target_gate_passed") is not False):
        raise RuntimeError("SOLR-34 v4 healthy qualification changed")

    (RAW / "remote-sha256.txt").write_bytes(REMOTE_INDEX.read_bytes())
    note = {
        "case_id": "SOLR-34", "host": "node1", "mode": "healthy",
        "admission_go_sha256": GO,
        "first_shell_invocation": "permission_denied_pre_jvm",
        "first_shell_invocation_jvm_started": False,
        "first_shell_invocation_output_created": False,
        "executed_invocation": "bash run_node1.sh",
        "executed_invocation_count": 1,
    }
    (RAW / "admission-execution-note.json").write_text(
        json.dumps(note, indent=2, sort_keys=True) + "\n")
    members = {str(path.relative_to(RAW)): sha(path)
               for path in sorted(RAW.rglob("*")) if path.is_file()}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(path.exists() for path in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-34 v4 evidence already sealed")
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
        "schema_version": 1, "case_id": "SOLR-34", "kind": "healthy_only",
        "source_host": "node1",
        "source_path": "/users/ZhenyuLi/baseline/data/mallory/solr34_healthy_path_node1_v4/SOLR-34",
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": result["status"], "duration_seconds": result["duration_seconds"],
        "junit_1_0_0": True, "fault_trials": 0,
        "agent_sha256": AGENT, "admission_go_sha256": GO,
        "remote_file_count": len(remote_files),
        "remote_sha_index_sha256": sha(REMOTE_INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "quality_audit_sha256": sha(RAW / "quality-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
        "typed_path_door_count": quality["typed_path_door_count"],
        "target_check_count": 0, "full_campaign_admitted": False,
        "first_shell_invocation": "permission_denied_pre_jvm",
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": sha(archive),
                      "receipt_sha256": sha(receipt),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
