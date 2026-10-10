#!/usr/bin/env python3
"""Attest and losslessly SHA-seal the SOLR-37 exact-reference healthy trial."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path("/users/ZhenyuLi/baseline")
CASE = BASE / "Mallory/adapters/solr/cases/SOLR-37/exact-reference-edge-node0-v3"
RAW = BASE / "data/mallory/solr37_exact_reference_edge_healthy_v3_node0/SOLR-37/healthy"
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "SOLR-37-exact-reference-healthy-node0-v3"
ARCHIVE = ARCHIVES / f"{PREFIX}.tar.gz"
MEMBERS = ARCHIVES / f"{PREFIX}.members.json"
RECEIPT = ARCHIVES / f"{PREFIX}.receipt.json"
DISK_FLOOR = 7_650_410_496


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def attest() -> tuple[dict, dict]:
    result = read(RAW / "result.json")
    checkpoint = read(RAW / "checkpoint.json")
    trial = read(RAW / "trials/r0000/result.json")
    pilot = read(RAW / "trials/r0000/pilot-result.json")
    audit = read(RAW / "strict-reference-audit.json")
    admission = read(CASE / "admission-healthy-node0.json")
    junit = result["healthy_junit_validation"]
    trace = RAW / "trials/r0000/events.jsonl.gz"
    if not (
        result["case_id"] == checkpoint["case_id"] == pilot["case_id"] == "SOLR-37"
        and result["status"] == checkpoint["status"] == "calibration_complete"
        and checkpoint["completed_trials"] == [0]
        and checkpoint["running"] is None
        and result["calibration_only"] is True
        and result["healthy_seed_valid"] is True
        and result["fault_trials_completed"] == 0
        and result["target_reached_trials"] == 0
        and result["exact_exception_trials"] == 0
        and result["new_bug"] is not True
        and junit["status"] == "passed"
        and (junit["tests"], junit["failures"], junit["errors"], junit["skipped"]) == (1, 0, 0, 0)
        and trial["junit_validation"] == junit
        and trial["return_code"] == 0
        and trial["timed_out"] is False
        and trial["plan"] == []
        and trial["feedback"]["target_reached"] is True
        and trial["feedback"]["target_threw"] is False
        and trial["feedback"]["trace_truncated"] is False
        and trial["events_evidence"]["gzip_sha256"] == sha(trace)
        and pilot["exit_code"] == 0
        and pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
        and pilot["target_check_count"] == audit["target_count"] == 188
        and pilot["target_throw_count"] == 0
        and audit["door_count"] == 705
        and audit["strict_witness_count"] == 188
        and audit["candidate_state_edges"] == 0
        and audit["eligible_for_fault_pilot"] is True
        and all(len(item["state_edges"]) >= 2 for item in audit["strict_witness_sample"])
        and junit["junit_log_sha256"] == sha(RAW / "trials/r0000/junit.log")
        and read(RAW / "config.json") == read(CASE / "config-healthy-node0.json")
        and admission["go"] is True
        and admission["case_id"] == "SOLR-37"
        and admission["host"] == "node0"
        and admission["mode"] == "healthy"
        and admission["intended_output"] == str(RAW)
        and admission["config_sha256"] == sha(CASE / "config-healthy-node0.json")
        and admission["runner_sha256"] == sha(CASE / "run_campaign.py")
    ):
        raise RuntimeError("SOLR-37 v3 terminal result, exact-reference audit, or admission mismatch")
    return result, audit


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError("SOLR-37 v3 seal already exists")
    result, audit = attest()
    files = sorted(path for path in RAW.rglob("*") if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise RuntimeError("raw evidence empty or symlinked")
    archive_prefix = "solr37_exact_reference_edge_healthy_v3_node0/SOLR-37/healthy/"
    members = [{"path": archive_prefix + path.relative_to(RAW).as_posix(),
                "bytes": path.stat().st_size, "sha256": sha(path)} for path in files]
    if shutil.disk_usage(BASE).free < DISK_FLOOR + sum(row["bytes"] for row in members):
        raise RuntimeError("archive would breach node0 disk reserve")
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    temporary = ARCHIVE.with_name(ARCHIVE.name + ".tmp")
    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path, row in zip(files, members):
                info = tarfile.TarInfo(row["path"])
                info.size = row["bytes"]
                info.mode = 0o600
                info.mtime = 0
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
        with tarfile.open(temporary, "r:gz") as archive:
            packed = archive.getmembers()
            if [item.name for item in packed] != [row["path"] for row in members]:
                raise RuntimeError("archive member list mismatch")
            for item, row in zip(packed, members):
                if not item.isfile() or item.size != row["bytes"]:
                    raise RuntimeError("archive member size mismatch")
                digest = hashlib.sha256()
                with archive.extractfile(item) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != row["sha256"]:
                    raise RuntimeError("archive member SHA mismatch")
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    write(MEMBERS, {"schema_version": 1, "case_id": "SOLR-37",
                    "scope": "exact_reference_healthy_diagnostic", "member_count": len(members),
                    "members": members, "archive_sha256": sha(ARCHIVE)})
    receipt = {"schema_version": 1, "case_id": "SOLR-37",
               "scope": "exact_reference_healthy_diagnostic",
               "status": result["status"], "duration_seconds": result["duration_seconds"],
               "junit": "1/0/0/0", "exact_target_checks": 188,
               "exact_target_throws": 0, "fault_trials_completed": 0,
               "full_campaign_admitted": False, "new_bug": False,
               "strict_witness_count": audit["strict_witness_count"],
               "named_door_count": audit["door_count"],
               "observed_state_edges": audit["observed_state_edges"],
               "candidate_state_edges": audit["candidate_state_edges"],
               "eligible_for_separate_fault_pilot_review": True,
               "archive_sha256": sha(ARCHIVE),
               "member_manifest_sha256": sha(MEMBERS), "member_count": len(members),
               "result_sha256": sha(RAW / "result.json"),
               "trial_result_sha256": sha(RAW / "trials/r0000/result.json"),
               "trace_sha256": sha(RAW / "trials/r0000/events.jsonl.gz"),
               "strict_audit_sha256": sha(RAW / "strict-reference-audit.json"),
               "junit_log_sha256": sha(RAW / "trials/r0000/junit.log"),
               "admission_receipt_sha256": sha(CASE / "admission-healthy-node0.json"),
               "runner_sha256": sha(CASE / "run_campaign.py"),
               "config_sha256": sha(CASE / "config-healthy-node0.json"),
               "agent_sha256": sha(CASE / "agent/release/mallory-agent.jar"),
               "adapter_sha256": sha(CASE / "adapter/release/adapter.jar"),
               "all_archive_members_verified": True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(seal(), sort_keys=True))
