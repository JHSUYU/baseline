#!/usr/bin/env python3
"""Archive/stream-verify the stopped shared original-JUnit HDFS-28 ledger."""
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
STATE = ROOT / "checkpoint.json"
AUDIT = ROOT / "raw-audit.json"
LOCK = ROOT / "campaign.lock"
MANIFEST = ROOT / "shared-terminal-raw-manifest.json"
ARCHIVE = ROOT / "shared-terminal-raw.tar.zst"
RECEIPT = ROOT / "shared-terminal-archive-receipt.json"
EXCLUDE_FILES = {LOCK.name, MANIFEST.name, ARCHIVE.name, RECEIPT.name,
                 "shared-terminal-archive.log"}
EXCLUDE_DIRS = {"fallback28-junit-v1", "scratch", "__pycache__"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def durable(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def inventory() -> list[dict]:
    output = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if (not path.is_file() or path.is_symlink() or
                any(part in EXCLUDE_DIRS for part in rel.parts) or
                path.name in EXCLUDE_FILES or
                path.name.endswith((".tmp", ".partial"))):
            continue
        output.append({"path": rel.as_posix(), "bytes": path.stat().st_size,
                       "sha256": digest(path)})
    return output


def build() -> None:
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        frozen = STATE.read_bytes()
        state = json.loads(frozen)
        audit_bytes = AUDIT.read_bytes()
        audit = json.loads(audit_bytes)
        valid = [t for t in state["completed"] if t["exact_order_applied"]
                 and t["post_fault_target_checks"]["HDFS-28"]]
        if (state["active"] is not None or
                state["stop_reason"] not in
                ("attempt_cap_inconclusive", "queue_exhausted_inconclusive",
                 "effective_budget_met_pending_independent_audit") or
                len(state["completed"]) > state["attempt_cap"] or
                audit["errors"] or
                audit["completed_attempts"] != len(state["completed"]) or
                audit["checkpoint_sha256"] != hashlib.sha256(frozen).hexdigest() or
                audit["effective_by_case"]["HDFS-28"] != len(valid) or
                audit["target_exception_candidates"]):
            raise RuntimeError("shared ledger is not a clean audited terminal")
        if MANIFEST.exists() or ARCHIVE.exists() or RECEIPT.exists():
            raise RuntimeError("shared terminal archive already exists")
        rows = inventory()
        if not rows or STATE.read_bytes() != frozen or AUDIT.read_bytes() != audit_bytes:
            raise RuntimeError("shared terminal files changed during inventory")
        manifest = {"schema": 1,
                    "scope": "shared HA original JUnit only; excludes alternate ledger, ephemeral scratch, Python cache, lock and archive outputs",
                    "checkpoint_sha256": hashlib.sha256(frozen).hexdigest(),
                    "raw_audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
                    "attempts": len(state["completed"]), "effective_hdfs28": len(valid),
                    "files": rows}
        durable(MANIFEST, encoded(manifest))
        partial = ARCHIVE.with_name(ARCHIVE.name + ".partial")
        if partial.exists():
            raise RuntimeError("stale partial shared archive requires review")
        process = subprocess.Popen(["zstd", "-3", "-T2", "-q", "-o", str(partial)],
                                   stdin=subprocess.PIPE)
        assert process.stdin is not None
        with tarfile.open(fileobj=process.stdin, mode="w|") as tar:
            for row in rows:
                tar.add(ROOT / row["path"], arcname=row["path"], recursive=False)
            tar.add(MANIFEST, arcname=MANIFEST.name, recursive=False)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("shared zstd failed")
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        partial.replace(ARCHIVE)
        receipt = {"schema": 1, "archive_sha256": digest(ARCHIVE),
                   "archive_bytes": ARCHIVE.stat().st_size,
                   "manifest_sha256": digest(MANIFEST),
                   "files": len(rows), "raw_bytes": sum(row["bytes"] for row in rows),
                   "checkpoint_sha256": manifest["checkpoint_sha256"],
                   "raw_audit_sha256": manifest["raw_audit_sha256"],
                   "attempts": manifest["attempts"],
                   "effective_hdfs28": manifest["effective_hdfs28"]}
        durable(RECEIPT, encoded(receipt))
        print(json.dumps(receipt, sort_keys=True), flush=True)


def verify() -> None:
    receipt = json.loads(RECEIPT.read_text())
    manifest = json.loads(MANIFEST.read_text())
    if (digest(ARCHIVE) != receipt["archive_sha256"] or
            digest(MANIFEST) != receipt["manifest_sha256"]):
        raise RuntimeError("shared archive or manifest SHA mismatch")
    expected = {row["path"]: row for row in manifest["files"]}
    expected[MANIFEST.name] = {"path": MANIFEST.name,
                               "bytes": MANIFEST.stat().st_size,
                               "sha256": receipt["manifest_sha256"]}
    seen = set()
    process = subprocess.Popen(["zstd", "-dc", str(ARCHIVE)], stdout=subprocess.PIPE)
    assert process.stdout is not None
    with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
        for member in tar:
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise RuntimeError("unexpected or duplicate shared member " + member.name)
            stream = tar.extractfile(member)
            assert stream is not None
            h = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
                size += len(chunk)
            if (size != expected[member.name]["bytes"] or
                    h.hexdigest() != expected[member.name]["sha256"]):
                raise RuntimeError("shared member differs: " + member.name)
            seen.add(member.name)
    process.stdout.close()
    if process.wait() != 0 or seen != set(expected):
        raise RuntimeError("shared archive stream incomplete")
    print(json.dumps({"archive_sha256": receipt["archive_sha256"],
                      "raw_files": receipt["files"], "verified_files": len(seen),
                      "errors": 0}, sort_keys=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.build == args.verify:
        parser.error("choose exactly one of --build or --verify")
    build() if args.build else verify()
