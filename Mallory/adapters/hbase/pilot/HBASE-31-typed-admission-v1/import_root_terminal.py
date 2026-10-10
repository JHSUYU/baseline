#!/usr/bin/env python3
"""Copy only the original HBASE-31 terminal summary/audit under node0 floor."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


ROOT = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CASE = ROOT / "data/mallory/cases/HBASE-31"
REMOTE = "ZhenyuLi@node1"
REMOTE_CASE = "/users/ZhenyuLi/baseline/data/mallory/cases/HBASE-31"
REMOTE_SEAL = "/users/ZhenyuLi/baseline/data/mallory/evidence_archives/campaign/HBASE-31.terminal-seal.json"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]
FLOOR = 5 * 1024**3
SAFETY = 128 * 1024**2


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(path: str) -> bytes:
    return subprocess.run(SSH + [shlex.join(["cat", path])],
                          check=True, capture_output=True).stdout


def place(path: Path, data: bytes) -> None:
    if path.exists():
        if sha(path.read_bytes()) != sha(data):
            raise RuntimeError(f"existing canonical file differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    if temporary.exists():
        raise RuntimeError(f"stale temporary canonical file: {temporary}")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def main() -> None:
    seal_bytes = fetch(REMOTE_SEAL)
    seal = json.loads(seal_bytes)
    if (seal.get("case_id") != "HBASE-31" or
            seal.get("status") != "budget_exhausted" or
            seal.get("completed_fault_trials") != 80 or
            seal.get("audit_report_gate_passed") is not True or
            seal.get("selected_target_throws") != 0):
        raise RuntimeError("remote terminal seal invalid")
    files = {
        "result.json": (f"{REMOTE_CASE}/result.json", seal["result_sha256"]),
        "config.json": (f"{REMOTE_CASE}/config.json", seal["config_sha256"]),
        "offline-causal-audit.json": (f"{REMOTE_CASE}/offline-causal-audit.json",
                                      seal["audit_sha256"]),
        "terminal-seal.json": (REMOTE_SEAL, sha(seal_bytes)),
    }
    contents = {name: fetch(path) for name, (path, _) in files.items()}
    if any(sha(contents[name]) != expected for name, (_, expected) in files.items()):
        raise RuntimeError("remote compact file SHA mismatch")
    missing_bytes = sum(len(contents[name]) for name in files if not (CASE / name).exists())
    free = shutil.disk_usage(ROOT).free
    if free < FLOOR + SAFETY + missing_bytes:
        raise RuntimeError(f"node0 compact import held by disk floor: free={free}, "
                           f"needed={FLOOR + SAFETY + missing_bytes}")
    for name, data in contents.items():
        place(CASE / name, data)
    result = json.loads((CASE / "result.json").read_text())
    audit = json.loads((CASE / "offline-causal-audit.json").read_text())
    if (result["status"] != "budget_exhausted" or
            audit["campaign_result_sha256"] != seal["result_sha256"] or
            result["fault_trials_completed"] != 80):
        raise RuntimeError("canonical compact summary/audit differs")
    receipt = {
        "schema_version": 1, "case_id": "HBASE-31",
        "kind": "original_full_compact_canonical_import",
        "status": result["status"],
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": result["fault_trials_completed"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "selected_target_throws": result["exact_exception_trials"],
        "result_sha256": seal["result_sha256"],
        "audit_sha256": seal["audit_sha256"],
        "config_sha256": seal["config_sha256"],
        "remote_archive_sha256": seal["archive_sha256"],
        "remote_archive_manifest_sha256": seal["archive_manifest_sha256"],
        "remote_terminal_seal_sha256": sha(seal_bytes),
        "remote_archive_host": "node1",
        "remote_raw_case": REMOTE_CASE,
        "remote_archive": "/users/ZhenyuLi/baseline/data/mallory/evidence_archives/campaign/HBASE-31.tar.gz",
        "node0_compact_only": True,
        "node0_disk_free_bytes_before_import": free,
        "node0_disk_floor_bytes": FLOOR,
        "node0_safety_bytes": SAFETY,
        "source_gap_receipt_sha256": seal["source_gap_receipt_sha256"],
        "bug_claim": False,
    }
    place(CASE / "canonical-import-receipt.json",
          (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
    print(json.dumps({"status": receipt["status"],
                      "fault_trials_completed": receipt["fault_trials_completed"],
                      "duration_seconds": receipt["duration_seconds"],
                      "result_sha256": receipt["result_sha256"],
                      "receipt_sha256": sha((CASE / "canonical-import-receipt.json").read_bytes())}))


if __name__ == "__main__":
    main()
