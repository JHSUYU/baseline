#!/usr/bin/env python3
"""Verify and archive the terminal HDFS-48 one-fault campaign."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/campaigns/HDFS-48-rename-presend-full-v5"
INDEX = Path(str(RAW) + ".remote-sha-index.json")
GO = BASE / "Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v5/admission-one-fault-node2.json"
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "HDFS-48-rename-presend-full-v5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    index = read(INDEX)
    if (index.get("source_host") != "node2"
            or index.get("source") != "/tmp/mallory-hdfs48-rename-presend-node2-full-v5"
            or len(index.get("files", {})) != 23):
        raise RuntimeError("unexpected node2 evidence index")
    for name, expected in index["files"].items():
        path = RAW / name
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError(f"node2 evidence changed: {name}")

    result = read(RAW / "result.json")
    checkpoint = read(RAW / "checkpoint.json")
    audit = read(RAW / "v5-strict-audit.json")
    offline = read(RAW / "offline-causal-audit.json")
    go = read(GO)
    if (result.get("case_id") != "HDFS-48"
            or result.get("status") != "budget_exhausted"
            or result.get("healthy_seed_valid") is not True
            or result.get("fault_trials_completed") != 1
            or result.get("strict_injected_trials") != 1
            or result.get("strict_target_trials") != 1
            or result.get("exact_exception_trials") != 0
            or result.get("new_bug") is True
            or checkpoint.get("completed_trials") != [0, 1]
            or checkpoint.get("status") != "budget_exhausted"):
        raise RuntimeError("terminal campaign result changed")
    for name in ("r0000", "r0001"):
        junit = read(RAW / "trials" / name / "result.json").get("junit_validation", {})
        if (junit.get("status") != "passed" or
                (junit.get("tests"), junit.get("failures"), junit.get("errors")) != (1, 0, 0)):
            raise RuntimeError(f"{name} JUnit is not 1/0/0")
    path = audit.get("fault_path", {})
    if (audit.get("strict_gate_passed") is not True
            or audit.get("core_offline_causal_gate_passed") is not True
            or audit.get("errors")
            or audit.get("campaign_result_sha256") != sha(RAW / "result.json")
            or path.get("classification") != "strict_postfault_retry_rpc_target"
            or not path.get("target_check_id")
            or path.get("target_throw_ids")
            or audit.get("pending_call_cleanup_warning_observed") is not False
            or offline.get("report_gate_passed") is not True):
        raise RuntimeError("strict postfault path or offline audit failed")
    if (go.get("go") is not True or go.get("case_id") != "HDFS-48"
            or go.get("host") != "node2"
            or go.get("mode") != "bounded_one_fault_full"
            or go.get("config_sha256") != sha(RAW / "config.json")
            or go.get("intended_output") != index["source"]):
        raise RuntimeError("dispatch GO does not match raw campaign")

    shutil.copy2(INDEX, RAW / "remote-sha-index.json")
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{PREFIX}.tar.gz"
    manifest = ARCHIVES / f"{PREFIX}.members.json"
    receipt = ARCHIVES / f"{PREFIX}.receipt.json"
    if any(p.exists() for p in (archive, manifest, receipt)):
        raise RuntimeError("HDFS-48 v5 archive already exists")
    write(manifest, {"schema_version": 1, "files": members})
    with tarfile.open(archive, "w:gz") as tar:
        for name in sorted(members):
            tar.add(RAW / name, arcname=f"{PREFIX}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as tar:
        found = {item.name.removeprefix(f"{PREFIX}/"):
                 hashlib.sha256(tar.extractfile(item).read()).hexdigest()
                 for item in tar if item.isfile()}
    if found != members:
        raise RuntimeError("archive member SHA mismatch")
    write(receipt, {
        "schema_version": 1, "case_id": "HDFS-48", "kind": "bounded_one_fault_full",
        "completion_criterion": "natural_one_fault_budget_terminal",
        "status": result["status"], "source_host": "node2", "source_path": index["source"],
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(index["files"]),
        "remote_sha_index_sha256": sha(INDEX),
        "result_sha256": sha(RAW / "result.json"),
        "config_sha256": sha(RAW / "config.json"),
        "checkpoint_sha256": sha(RAW / "checkpoint.json"),
        "strict_audit_sha256": sha(RAW / "v5-strict-audit.json"),
        "offline_causal_audit_sha256": sha(RAW / "offline-causal-audit.json"),
        "admission_go_sha256": sha(GO),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members),
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": 1, "strict_injected_trials": 1,
        "strict_target_trials": 1, "exact_exception_trials": 0,
        "postfault_path_classification": path["classification"],
        "junit": {"healthy": "1/0/0", "fault": "1/0/0"},
        "pending_call_cleanup_warning_observed": False,
        "new_bug": False,
    })
    print(json.dumps({"receipt_sha256": sha(receipt), "archive_sha256": sha(archive),
                      "member_count": len(members), "strict_gate_passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
