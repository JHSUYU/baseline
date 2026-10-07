#!/usr/bin/env python3
"""Archive and stream-verify a naturally stopped HDFS-28 alternate ledger."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "campaign.lock"
STATE = ROOT / "checkpoint.json"
AUDIT = ROOT / "raw-audit.json"
MANIFEST = ROOT / "terminal-raw-manifest.json"
ARCHIVE = ROOT / "terminal-raw.tar.zst"
RECEIPT = ROOT / "terminal-archive-receipt.json"
EXCLUDE = {MANIFEST.name, ARCHIVE.name, RECEIPT.name,
           "campaign.lock", "terminal-archive.log"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def durable(path: Path, data: bytes) -> None:
    pending = path.with_name(path.name + ".tmp")
    with pending.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def inventory() -> list[dict]:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if (not path.is_file() or path.is_symlink() or
                any(part in ("scratch", "__pycache__") for part in path.relative_to(ROOT).parts) or
                path.name in EXCLUDE or path.name.endswith(".tmp")):
            continue
        rows.append({"path": path.relative_to(ROOT).as_posix(),
                     "bytes": path.stat().st_size, "sha256": sha(path)})
    return rows


def build() -> None:
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_bytes = STATE.read_bytes()
        state = json.loads(state_bytes)
        audit_bytes = AUDIT.read_bytes()
        audit = json.loads(audit_bytes)
        if (state["active"] is not None or
                state["stop_reason"] != "effective_budget_met_pending_independent_audit" or
                len(state["completed"]) != 395 or
                len([trial for trial in state["completed"]
                     if trial["exact_order_applied"] and
                     trial["post_fault_target_checks"]["HDFS-28"]]) != 80 or
                audit["errors"] or audit["completed_attempts"] != 395 or
                audit["checkpoint_sha256"] != hashlib.sha256(state_bytes).hexdigest()):
            raise RuntimeError("not the independently audited natural terminal ledger")
        if ARCHIVE.exists() or MANIFEST.exists() or RECEIPT.exists():
            raise RuntimeError("terminal archive already exists")
        rows = inventory()
        if not rows or STATE.read_bytes() != state_bytes or AUDIT.read_bytes() != audit_bytes:
            raise RuntimeError("terminal ledger changed during inventory")
        manifest = {"schema": 1, "scope": "entire alternate case directory excluding ephemeral scratch, pycache, lock and archive outputs",
                    "checkpoint_sha256": hashlib.sha256(state_bytes).hexdigest(),
                    "raw_audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
                    "files": rows}
        durable(MANIFEST, encoded(manifest))
        partial = ARCHIVE.with_name(ARCHIVE.name + ".partial")
        if partial.exists():
            raise RuntimeError("stale partial archive requires manual review")
        process = subprocess.Popen(["zstd", "-3", "-T2", "-q", "-o", str(partial)],
                                   stdin=subprocess.PIPE)
        assert process.stdin is not None
        with tarfile.open(fileobj=process.stdin, mode="w|") as tar:
            for row in rows:
                tar.add(ROOT / row["path"], arcname=row["path"], recursive=False)
            tar.add(MANIFEST, arcname=MANIFEST.name, recursive=False)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("zstd failed")
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        partial.replace(ARCHIVE)
        receipt = {"schema": 1, "archive_sha256": sha(ARCHIVE),
                   "archive_bytes": ARCHIVE.stat().st_size,
                   "manifest_sha256": sha(MANIFEST), "files": len(rows),
                   "raw_bytes": sum(row["bytes"] for row in rows),
                   "checkpoint_sha256": manifest["checkpoint_sha256"],
                   "raw_audit_sha256": manifest["raw_audit_sha256"]}
        durable(RECEIPT, encoded(receipt))
        print(json.dumps(receipt, sort_keys=True), flush=True)


def verify() -> None:
    receipt = json.loads(RECEIPT.read_text())
    manifest = json.loads(MANIFEST.read_text())
    if (sha(ARCHIVE) != receipt["archive_sha256"] or
            sha(MANIFEST) != receipt["manifest_sha256"]):
        raise RuntimeError("archive or manifest SHA mismatch")
    expected = {row["path"]: row for row in manifest["files"]}
    expected[MANIFEST.name] = {"path": MANIFEST.name,
                               "bytes": MANIFEST.stat().st_size,
                               "sha256": receipt["manifest_sha256"]}
    process = subprocess.Popen(["zstd", "-dc", str(ARCHIVE)], stdout=subprocess.PIPE)
    assert process.stdout is not None
    seen = set()
    with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
        for member in tar:
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise RuntimeError("unexpected or duplicate archive member " + member.name)
            digest = hashlib.sha256()
            size = 0
            stream = tar.extractfile(member)
            assert stream is not None
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            if (size != expected[member.name]["bytes"] or
                    digest.hexdigest() != expected[member.name]["sha256"]):
                raise RuntimeError("archived file differs: " + member.name)
            seen.add(member.name)
    process.stdout.close()
    if process.wait() != 0 or seen != set(expected):
        raise RuntimeError("archive stream failed or missed files")
    print(json.dumps({"archive_sha256": receipt["archive_sha256"],
                      "verified_files": len(seen), "raw_files": receipt["files"],
                      "errors": 0}, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build == args.verify:
        parser.error("choose exactly one of --build or --verify")
    build() if args.build else verify()
