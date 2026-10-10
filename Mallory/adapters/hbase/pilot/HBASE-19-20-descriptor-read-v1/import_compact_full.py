#!/usr/bin/env python3
"""Import a SHA-verified HBASE-19/20 terminal summary from node1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess


BASE = Path("/users/ZhenyuLi/baseline")
ROOT = BASE / "data/mallory"
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]
FLOOR = 5 * 1024**3 + 128 * 1024**2
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote(*args: str) -> bytes:
    return subprocess.run(SSH + [shlex.join(args)], check=True,
                          capture_output=True).stdout


def read_remote(path: Path, expected: str) -> bytes:
    data = remote("cat", str(path))
    if sha(data) != expected:
        raise ValueError(f"remote SHA mismatch: {path}")
    return data


def import_case(number: int) -> dict:
    if socket.gethostname().split(".")[0] != "node0":
        raise RuntimeError("compact import requires node0")
    case = f"HBASE-{number}"
    stem = f"{case}-descriptor-read-v1-full"
    campaign = ROOT / case / "campaigns/descriptor-read-v1-full"
    archives = ROOT / "evidence_archives/offhost_full"
    archive = archives / f"{stem}.tar.gz"
    manifest_path = archives / f"{stem}.manifest.json"
    seal_path = archives / f"{stem}.receipt.json"
    seal_bytes = remote("cat", str(seal_path))
    seal = json.loads(seal_bytes)
    if (seal.get("case_id") != case or seal.get("status") not in TERMINAL or
            not 0 < seal.get("fault_trials_completed", 0) <= 80 or
            seal.get("raw_host") != "node1" or
            seal.get("raw_path") != str(campaign)):
        raise ValueError("remote terminal seal identity mismatch")
    manifest_bytes = read_remote(manifest_path, seal["manifest_sha256"])
    manifest = json.loads(manifest_bytes)
    if (manifest.get("case_id") != case or
            manifest.get("member_count") != seal["member_count"] or
            len(manifest.get("members", [])) != seal["member_count"]):
        raise ValueError("remote archive manifest identity mismatch")
    archive_sha = remote("sha256sum", str(archive)).decode().split()[0]
    archive_bytes = int(remote("stat", "-c", "%s", str(archive)).decode().strip())
    if (archive_sha != seal["archive_sha256"] or
            archive_bytes != seal["archive_bytes"]):
        raise ValueError("remote archive differs from terminal seal")

    expected = {
        "result.json": seal["result_sha256"],
        "config.json": seal["config_sha256"],
        "checkpoint.json": seal["checkpoint_sha256"],
        "offline-causal-audit.json": seal["audit_sha256"],
    }
    members = {item["path"]: item for item in manifest["members"]}
    contents = {}
    for name, digest in expected.items():
        key = f"{case}/campaigns/descriptor-read-v1-full/{name}"
        if members.get(key, {}).get("sha256") != digest:
            raise ValueError(f"archive member SHA mismatch: {name}")
        contents[name] = read_remote(campaign / name, digest)
    result = json.loads(contents["result.json"])
    audit = json.loads(contents["offline-causal-audit.json"])
    if (result.get("case_id") != case or result.get("status") != seal["status"] or
            result.get("fault_trials_completed") != seal["fault_trials_completed"] or
            audit.get("case_id") != case or
            audit.get("campaign_result_sha256") != seal["result_sha256"]):
        raise ValueError("terminal summary or audit differs from seal")

    target = ROOT / "cases" / case
    receipt = {
        "schema_version": 1, "case_id": case,
        "kind": "sha_verified_compact_canonical_import",
        "status": seal["status"],
        "completed_campaign": True,
        "fault_trials_completed": seal["fault_trials_completed"],
        "result_sha256": seal["result_sha256"],
        "config_sha256": seal["config_sha256"],
        "checkpoint_sha256": seal["checkpoint_sha256"],
        "audit_sha256": seal["audit_sha256"],
        "node1_seal_sha256": sha(seal_bytes),
        "archive_sha256": archive_sha,
        "archive_bytes": archive_bytes,
        "manifest_sha256": seal["manifest_sha256"],
        "archive_member_count": seal["member_count"],
        "raw_host": "node1", "raw_path": str(campaign),
        "archive_path": str(archive),
    }
    contents["node1-terminal-seal.json"] = seal_bytes
    contents["canonical-import-receipt.json"] = (
        json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    if target.exists():
        if all((target / name).is_file() and
               (target / name).read_bytes() == data for name, data in contents.items()):
            return receipt
        raise FileExistsError(f"existing canonical directory differs: {target}")
    required = sum(len(data) for data in contents.values())
    if shutil.disk_usage(BASE).free < FLOOR + required:
        raise RuntimeError("node0 compact import below disk reserve")
    staging = target.with_name(f".{case}.importing")
    if staging.exists():
        raise FileExistsError(f"prior staged import exists: {staging}")
    staging.mkdir(parents=True)
    for name, data in contents.items():
        path = staging / name
        with path.open("wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    os.replace(staging, target)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=int, choices=(19, 20))
    args = parser.parse_args()
    print(json.dumps(import_case(args.case), sort_keys=True))
