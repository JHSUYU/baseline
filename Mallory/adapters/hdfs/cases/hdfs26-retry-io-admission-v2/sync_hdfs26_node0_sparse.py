#!/usr/bin/env python3
"""Publish only SHA-verified terminal HDFS-26 summaries on node0.

The full trial tree and its gzip archive stay on node2. The node0 checklist
receives a result and offline audit only after the owner host seals them.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


BASE = Path("/users/ZhenyuLi/baseline")
STATE = BASE / "data/mallory/dispatch/node0-hdfs26-v2-full"
CANONICAL = BASE / "data/mallory/cases/HDFS-26"
REMOTE_STATE = BASE / "data/mallory/dispatch/node2-hdfs26-v2-full"
REMOTE_CASE = BASE / "data/mallory/cases/HDFS-26"
KEY = Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes")
CONFIG_SHA = "453b54f8af9418271d10c812565ec92637e7dc3a2207750fe60555f0d22e2879"
FLOOR = 5 * 1024**3
HEADROOM = 128 * 1024**2
FILES = {
    "config.json": "config.json",
    "result.json": "result.json",
    "offline-causal-audit.json": "offline-causal-audit.json",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ssh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
         "ZhenyuLi@node2", *args], capture_output=True, text=True, timeout=120)


def remote_receipt() -> dict | None:
    result = ssh("cat", str(REMOTE_STATE / "terminal-publication.json"))
    if result.returncode:
        if "No such file" in result.stderr:
            return None
        raise RuntimeError(f"node2 terminal receipt unavailable: {result.stderr[:300]}")
    receipt = json.loads(result.stdout)
    if (receipt.get("schema_version") != 1 or receipt.get("case_id") != "HDFS-26"
            or receipt.get("config_sha256") != CONFIG_SHA
            or receipt.get("status") not in {"budget_exhausted", "queue_exhausted"}):
        raise ValueError("node2 receipt is not the pinned terminal HDFS-26 campaign")
    expected = receipt.get("files")
    if (not isinstance(expected, dict) or
            any(not isinstance(expected.get(name), str) for name in FILES)):
        raise ValueError("node2 per-file SHA receipt incomplete")
    if (expected["config.json"] != CONFIG_SHA or
            expected["result.json"] != receipt.get("canonical_result_sha256") or
            expected["offline-causal-audit.json"] != receipt.get("audit_sha256")):
        raise ValueError("node2 case hashes disagree with terminal receipt")
    return receipt


def remote_size(path: Path) -> int:
    result = ssh("stat", "-c", "%s", str(path))
    if result.returncode:
        raise RuntimeError(f"node2 file size unavailable: {path}: {result.stderr[:200]}")
    return int(result.stdout.strip())


def verify_remote_archive(receipt: dict) -> None:
    archive = Path(receipt["archive_path"])
    manifest = Path(receipt["archive_manifest_path"])
    expected_dir = REMOTE_STATE / "publication/evidence_archives/campaign"
    if (archive != expected_dir / "HDFS-26.tar.gz" or
            manifest != expected_dir / "HDFS-26.tar.manifest.json"):
        raise ValueError("node2 archive path escapes the pinned publication")
    result = ssh("sha256sum", str(archive), str(manifest))
    if result.returncode:
        raise RuntimeError(f"node2 archive digest unavailable: {result.stderr[:300]}")
    hashes = [line.split(maxsplit=1)[0] for line in result.stdout.splitlines()]
    if hashes != [receipt.get("archive_sha256"), receipt.get("archive_manifest_sha256")]:
        raise ValueError("node2 archive or manifest changed after publication")
    if remote_size(archive) != receipt.get("archive_bytes"):
        raise ValueError("node2 archive size changed after publication")


def fetch(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    transport = f"ssh -i {KEY} -o IdentitiesOnly=yes -o BatchMode=yes"
    subprocess.run(["rsync", "-a", "-e", transport,
                    f"ZhenyuLi@node2:{source}", str(destination)],
                   check=True, timeout=180)


def publish(receipt: dict) -> None:
    if CANONICAL.exists():
        existing = CANONICAL / "sync-receipt.json"
        if (existing.is_file() and
                json.loads(existing.read_text()).get("result_sha256") ==
                receipt["canonical_result_sha256"]):
            return
        raise FileExistsError(f"canonical HDFS-26 conflicts with terminal receipt: {CANONICAL}")
    verify_remote_archive(receipt)
    remote_inputs = {name: REMOTE_CASE / name for name in FILES}
    remote_inputs.update({
        "HDFS-26.tar.manifest.json": Path(receipt["archive_manifest_path"]),
        "remote-publication-receipt.json": REMOTE_STATE / "terminal-publication.json",
        "raw-copy-receipt.json": REMOTE_STATE / "raw-copy-receipt.json",
    })
    needed = sum(remote_size(path) for path in remote_inputs.values())
    if shutil.disk_usage(BASE).free < FLOOR + needed + HEADROOM:
        raise RuntimeError("node0 sparse import would breach 5 GiB + 128 MiB reserve")
    staging = STATE / "import" / "HDFS-26"
    staging.mkdir(parents=True, exist_ok=True)
    for name, source in remote_inputs.items():
        fetch(source, staging / name)
    if any(sha(staging / name) != receipt["files"][name] for name in FILES):
        raise ValueError("node0 sparse result/config/audit SHA mismatch")
    if sha(staging / "HDFS-26.tar.manifest.json") != receipt["archive_manifest_sha256"]:
        raise ValueError("node0 archive manifest SHA mismatch")
    imported_receipt = json.loads((staging / "remote-publication-receipt.json").read_text())
    if imported_receipt != receipt:
        raise ValueError("node0 publication receipt changed during import")
    raw_receipt = json.loads((staging / "raw-copy-receipt.json").read_text())
    manifest = json.loads((staging / "HDFS-26.tar.manifest.json").read_text())
    if (raw_receipt.get("case_id") != "HDFS-26" or
            raw_receipt.get("config_sha256") != CONFIG_SHA or
            raw_receipt.get("files", {}).get("result.json") != receipt["raw_result_sha256"] or
            manifest.get("case_id") != "HDFS-26" or
            manifest.get("phase") != "campaign" or
            manifest.get("source_result_sha256") != receipt["raw_result_sha256"] or
            manifest.get("archive_sha256") != receipt["archive_sha256"] or
            sorted(manifest.get("members", [])) != sorted(raw_receipt.get("files", {}))):
        raise ValueError("node2 archive manifest is not bound to complete raw file list")
    result = json.loads((staging / "result.json").read_text())
    audit = json.loads((staging / "offline-causal-audit.json").read_text())
    if (result.get("case_id") != "HDFS-26" or result.get("status") != receipt["status"] or
            result.get("evidence_archive", {}).get("sha256") != receipt["archive_sha256"] or
            audit.get("campaign_result_sha256") != receipt["canonical_result_sha256"]):
        raise ValueError("sparse result/audit is not bound to remote raw archive")
    if shutil.disk_usage(BASE).free < FLOOR + HEADROOM:
        raise RuntimeError("node0 reserve fell below publication floor")
    sync = {
        "schema_version": 1, "case_id": "HDFS-26", "status": receipt["status"],
        "mode": "sha_verified_offhost_raw_sparse_summary",
        "owner_host": "node2", "remote_case": str(REMOTE_CASE),
        "remote_archive": receipt["archive_path"],
        "result_sha256": receipt["canonical_result_sha256"],
        "audit_sha256": receipt["audit_sha256"], "config_sha256": CONFIG_SHA,
        "remote_archive_sha256": receipt["archive_sha256"],
        "remote_archive_manifest_sha256": receipt["archive_manifest_sha256"],
        "remote_raw_file_count": len(raw_receipt["files"]),
        "remote_raw_result_sha256": receipt["raw_result_sha256"],
        "report_gate_passed": audit.get("report_gate_passed"),
    }
    (staging / "sync-receipt.json").write_text(json.dumps(sync, sort_keys=True, indent=2) + "\n")
    CANONICAL.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, CANONICAL)
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "terminal-sync.json").write_text(json.dumps(sync, sort_keys=True, indent=2) + "\n")


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    while True:
        receipt = remote_receipt()
        if receipt is not None:
            try:
                publish(receipt)
            except RuntimeError as exc:
                if "reserve" not in str(exc):
                    raise
                print(str(exc), flush=True)
            else:
                print("HDFS-26 compact terminal case published on node0", flush=True)
                return
        time.sleep(30)


if __name__ == "__main__":
    main()
