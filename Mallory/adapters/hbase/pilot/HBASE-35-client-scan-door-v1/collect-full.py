#!/usr/bin/env python3
"""Seal a naturally terminal HBASE-35 campaign while retaining raw data on node1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile


BASE = Path("/users/ZhenyuLi/baseline")
CAMPAIGN = BASE / "data/mallory/HBASE-35/campaigns/client-scan-v1-full"
ARCHIVE_DIR = BASE / "data/mallory/evidence_archives/offhost_full"
ARCHIVE = ARCHIVE_DIR / "HBASE-35-client-scan-v1-full.tar.gz"
MANIFEST = ARCHIVE_DIR / "HBASE-35-client-scan-v1-full.manifest.json"
RECEIPT = ARCHIVE_DIR / "HBASE-35-client-scan-v1-full.receipt.json"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def write_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as target:
        json.dump(value, target, sort_keys=True, indent=2)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    temp.replace(path)


def verify_terminal() -> tuple[dict, dict]:
    result, checkpoint = read_json(CAMPAIGN / "result.json"), read_json(CAMPAIGN / "checkpoint.json")
    assert result["case_id"] == checkpoint["case_id"] == "HBASE-35"
    assert result["status"] == checkpoint["status"] and result["status"] in TERMINAL
    assert result["calibration_only"] is False
    assert result["healthy_seed_valid"] is True
    faults = int(result["fault_trials_completed"])
    assert 0 < faults <= 80
    assert len(checkpoint["completed_trials"]) == faults + 1
    junit = result["healthy_junit_validation"]
    assert junit["status"] == "passed" and junit["tests"] == junit["succeeded"] == 1
    assert junit["failures"] == junit["errors"] == 0
    assert result["target_node_named"] is True
    return result, checkpoint


def run_audit() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{RELEASE}:{BASE}"
    completed = subprocess.run(
        [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(CAMPAIGN),
         "--out", str(CAMPAIGN / "offline-causal-audit.json")],
        cwd=BASE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, check=False,
    )
    (CAMPAIGN / "offline-audit.log").write_text(completed.stdout)
    if completed.returncode not in (0, 2):
        raise RuntimeError(f"offline audit failed ({completed.returncode}): {completed.stdout[-1000:]}")
    audit = read_json(CAMPAIGN / "offline-causal-audit.json")
    assert audit["case_id"] == "HBASE-35"
    return completed.returncode


def seal() -> None:
    assert CAMPAIGN.is_dir() and not ARCHIVE.exists() and not MANIFEST.exists() and not RECEIPT.exists()
    result, _ = verify_terminal()
    audit_exit = run_audit()
    files = sorted(p for p in CAMPAIGN.rglob("*") if p.is_file())
    assert files and not any(p.is_symlink() for p in files)
    members = [{"path": p.relative_to(BASE / "data/mallory").as_posix(),
                "bytes": p.stat().st_size, "sha256": sha(p)} for p in files]
    manifest = {"schema_version": 1, "case_id": "HBASE-35", "source_root": str(CAMPAIGN),
                "member_count": len(members), "logical_bytes": sum(m["bytes"] for m in members),
                "members": members}
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    temporary_archive = ARCHIVE.with_name(ARCHIVE.name + ".tmp")
    with tarfile.open(temporary_archive, "w:gz") as tar:
        for path in files:
            tar.add(path, arcname=path.relative_to(BASE / "data/mallory").as_posix(), recursive=False)
    with tarfile.open(temporary_archive, "r:gz") as tar:
        names = [m.name for m in tar.getmembers()]
        assert names == [m["path"] for m in members]
        for info, expected in zip(tar.getmembers(), members):
            assert info.isfile() and info.size == expected["bytes"]
            stream = tar.extractfile(info)
            assert stream is not None
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            assert digest.hexdigest() == expected["sha256"]
    temporary_archive.replace(ARCHIVE)
    write_json(MANIFEST, manifest)
    receipt = {
        "schema_version": 1, "case_id": "HBASE-35", "status": result["status"],
        "fault_trials_completed": result["fault_trials_completed"],
        "duration_seconds": result["duration_seconds"],
        "exact_exception_trials": result["exact_exception_trials"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "result_sha256": sha(CAMPAIGN / "result.json"),
        "checkpoint_sha256": sha(CAMPAIGN / "checkpoint.json"),
        "config_sha256": sha(CAMPAIGN / "config.json"),
        "audit_sha256": sha(CAMPAIGN / "offline-causal-audit.json"),
        "audit_exit_code": audit_exit,
        "collector_sha256": sha(Path(__file__)),
        "archive_sha256": sha(ARCHIVE), "archive_bytes": ARCHIVE.stat().st_size,
        "manifest_sha256": sha(MANIFEST), "member_count": len(members),
        "raw_host": "node1", "raw_path": str(CAMPAIGN),
    }
    write_json(RECEIPT, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", action="store_true", required=True)
    args = parser.parse_args()
    seal()
