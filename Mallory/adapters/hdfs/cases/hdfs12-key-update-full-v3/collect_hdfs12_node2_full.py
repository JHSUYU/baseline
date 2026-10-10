#!/usr/bin/env python3
"""Archive terminal HDFS-12 raw evidence on node2; never publish a live case."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from Mallory.dispatch.archive import ensure
from Mallory.dispatch.worker import atomic_json


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/tmp/mallory-hdfs12-key-update-v3-full")
STATE = BASE / "data/mallory/dispatch/node2-hdfs12-v3-full"
STAGING_ROOT = STATE / "publication"
CASE = "HDFS-12"
DESTINATION = BASE / "data/mallory/cases" / CASE
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "e695aefef696f08613b4de570f43e786895dae4ee6e1d1099334f52b2ea7248d"
FLOOR = 5 * 1024**3
HEADROOM = 128 * 1024**2
SESSION = "mallory-node2-hdfs12-v3-full"
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha(path)
            for path in sorted(root.rglob("*")) if path.is_file()
            and path.name != ".campaign.lock"}


def bytes_in(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def ready() -> bool:
    result_path, checkpoint_path = SOURCE / "result.json", SOURCE / "checkpoint.json"
    if not result_path.is_file() or not checkpoint_path.is_file():
        return False
    checkpoint, result = (json.loads(path.read_text()) for path in
                          (checkpoint_path, result_path))
    if checkpoint.get("status") not in TERMINAL:
        return False
    if (result.get("status") != checkpoint.get("status") or
            checkpoint.get("running") is not None or
            result.get("case_id") != CASE or checkpoint.get("case_id") != CASE):
        raise RuntimeError("terminal checkpoint/result mismatch")
    return True


def seal_existing(source_hashes: dict[str, str]) -> None:
    """Recover a case moved to canonical just before receipt creation."""
    result_path = DESTINATION / "result.json"
    audit_path = DESTINATION / "offline-causal-audit.json"
    archive = STAGING_ROOT / "evidence_archives/campaign/HDFS-12.tar.gz"
    manifest = STAGING_ROOT / "evidence_archives/campaign/HDFS-12.tar.manifest.json"
    if not all(path.is_file() for path in (result_path, audit_path, archive, manifest)):
        raise RuntimeError("terminal canonical missing result, audit, or archive")
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    packed = json.loads(manifest.read_text())
    if (result.get("case_id") != CASE or result.get("status") not in TERMINAL or
            sha(DESTINATION / "config.json") != CONFIG_SHA or
            audit.get("campaign_result_sha256") != sha(result_path) or
            packed.get("source_result_sha256") != source_hashes.get("result.json") or
            packed.get("archive_sha256") != sha(archive) or
            result.get("evidence_archive", {}).get("sha256") != sha(archive) or
            sorted(packed.get("members", [])) != sorted(source_hashes) or
            any(sha(DESTINATION / name) != digest for name, digest in source_hashes.items()
                if name != "result.json")):
        raise RuntimeError("terminal canonical differs from locked raw evidence")
    atomic_json(STATE / "terminal-publication.json", {
        "schema_version": 1, "case_id": CASE, "status": result["status"],
        "raw_result_sha256": source_hashes["result.json"],
        "canonical_result_sha256": sha(result_path),
        "config_sha256": CONFIG_SHA, "audit_sha256": sha(audit_path),
        "report_gate_passed": audit.get("report_gate_passed"),
        "archive_path": str(archive), "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_manifest_path": str(manifest),
        "archive_manifest_sha256": sha(manifest),
        "files": tree(DESTINATION), "case_bytes": bytes_in(DESTINATION)})


def collect() -> None:
    with (SOURCE / ".campaign.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not ready() or sha(SOURCE / "config.json") != CONFIG_SHA:
            raise RuntimeError("terminal source or pinned config changed")
        source_hashes = tree(SOURCE)
        if DESTINATION.exists():
            seal_existing(source_hashes)
            return
        source_bytes = bytes_in(SOURCE)
        # Copy + compressed archive may each approach the original raw size.
        if shutil.disk_usage(BASE).free < FLOOR + 2 * source_bytes + HEADROOM:
            raise RuntimeError("node2 disk reserve insufficient for copy and archive")
        staged = STAGING_ROOT / "cases" / CASE
        if not staged.exists():
            temporary = staged.with_name(f".{CASE}.copy-{os.getpid()}")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SOURCE, temporary, ignore=shutil.ignore_patterns(".campaign.lock"))
            if tree(temporary) != source_hashes:
                raise RuntimeError("staging copy hash mismatch")
            os.replace(temporary, staged)
        staged_hashes = tree(staged)
        staged_result = json.loads((staged / "result.json").read_text())
        if staged_result.get("evidence_archive"):
            if any(staged_hashes.get(name) != digest for name, digest in source_hashes.items()
                   if name != "result.json"):
                raise RuntimeError("staged trial evidence differs from terminal raw")
            manifest = STAGING_ROOT / "evidence_archives/campaign/HDFS-12.tar.manifest.json"
            if (not manifest.is_file() or
                    json.loads(manifest.read_text()).get("source_result_sha256") !=
                    source_hashes["result.json"]):
                raise RuntimeError("staged archive not bound to terminal raw result")
        elif staged_hashes != source_hashes:
            raise RuntimeError("staging copy differs from terminal raw evidence")
        atomic_json(STATE / "raw-copy-receipt.json", {
            "schema_version": 1, "case_id": CASE, "source": str(SOURCE),
            "config_sha256": CONFIG_SHA, "files": source_hashes})
        archived = ensure(STAGING_ROOT, "campaign", CASE, reserve_bytes=FLOOR + HEADROOM)
        result_path = staged / "result.json"
        result = json.loads(result_path.read_text())
        result["evidence_archive"] = {
            "bytes": archived["archive_bytes"],
            "manifest_path": archived["manifest_relative"],
            "manifest_sha256": archived["manifest_sha256"],
            "path": archived["archive_relative"],
            "sha256": archived["archive_sha256"]}
        atomic_json(result_path, result)
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{RELEASE}:{BASE}"
        audit = subprocess.run(
            [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(staged),
             "--out", str(staged / "offline-causal-audit.json")],
            cwd=BASE, env=env, capture_output=True, text=True)
        atomic_json(STATE / "audit-execution.json", {
            "exit_code": audit.returncode, "stdout": audit.stdout,
            "stderr": audit.stderr, "result_sha256": sha(result_path)})
        if audit.returncode not in (0, 2):
            raise RuntimeError(f"frozen audit execution failed: {audit.stderr[:500]}")
        audit_result = json.loads((staged / "offline-causal-audit.json").read_text())
        if audit_result.get("campaign_result_sha256") != sha(result_path):
            raise RuntimeError("audit/result hash mismatch")
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, DESTINATION)
        seal_existing(source_hashes)


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    while True:
        if ready():
            try:
                collect()
            except BlockingIOError:
                pass
            except RuntimeError as exc:
                if "disk reserve" not in str(exc):
                    raise
                print(str(exc), flush=True)
            else:
                print("HDFS-12 terminal raw archived and audited on node2", flush=True)
                return
        elif subprocess.run(["tmux", "has-session", "-t", SESSION],
                            capture_output=True).returncode != 0:
            # A just-exited worker may still have a final atomic result rename pending.
            time.sleep(5)
            if not ready():
                raise RuntimeError("HDFS-12 worker exited without terminal result")
            continue
        time.sleep(15)


if __name__ == "__main__":
    main()
