#!/usr/bin/env python3
"""Collect the pinned HDFS-11 v27 full run after its worker releases lane1."""

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
SOURCE = Path("/tmp/mallory-hdfs11-v27-full")
STATE = BASE / "data/mallory/dispatch/node0-hdfs11-v27-full"
STAGING_ROOT = STATE / "publication"
CASE = "HDFS-11"
DESTINATION = BASE / "data/mallory/cases" / CASE
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "b71bdaa9e6b765e677f88f196ea724c728b4986a42e1169a7c40e0c2ad797118"
FLOOR = 5 * 1024**3


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


def ready() -> bool:
    checkpoint = SOURCE / "checkpoint.json"
    result_path = SOURCE / "result.json"
    if not checkpoint.is_file() or not result_path.is_file():
        return False
    state = json.loads(checkpoint.read_text())
    result = json.loads(result_path.read_text())
    if state.get("status") not in {"budget_exhausted", "queue_exhausted"}:
        return False
    if (state.get("status") != result.get("status") or
            state.get("running") is not None):
        return False
    if state.get("case_id") != CASE or result.get("case_id") != CASE:
        raise RuntimeError("terminal checkpoint and result case IDs disagree")
    return True


def collect() -> None:
    lock_path = SOURCE / ".campaign.lock"
    with lock_path.open("a+b") as worker_lock:
        fcntl.flock(worker_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not ready():
            raise RuntimeError("campaign is no longer terminal under its worker lock")
        if sha(SOURCE / "config.json") != CONFIG_SHA:
            raise RuntimeError("running campaign config changed")
        if DESTINATION.exists():
            raise FileExistsError(f"canonical HDFS-11 already exists: {DESTINATION}")
        source_hashes = tree(SOURCE)
        bytes_needed = sum((SOURCE / name).stat().st_size for name in source_hashes)
        if shutil.disk_usage(BASE).free < FLOOR + bytes_needed + 64 * 1024**2:
            raise RuntimeError("disk reserve would be breached during collection")
        staged_case = STAGING_ROOT / "cases" / CASE
        if not staged_case.exists():
            temporary = staged_case.with_name(f".{CASE}.copy-{os.getpid()}")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(SOURCE, temporary, ignore=shutil.ignore_patterns(".campaign.lock"))
            if tree(temporary) != source_hashes:
                raise RuntimeError("staging copy hash mismatch")
            os.replace(temporary, staged_case)
        staged_hashes = tree(staged_case)
        staged_result = json.loads((staged_case / "result.json").read_text())
        if staged_result.get("evidence_archive"):
            if any(staged_hashes.get(name) != value for name, value in source_hashes.items()
                   if name != "result.json"):
                raise RuntimeError("staged trial evidence differs from terminal raw")
            manifest_path = STAGING_ROOT / "evidence_archives/campaign" / f"{CASE}.tar.manifest.json"
            if (not manifest_path.is_file() or
                    json.loads(manifest_path.read_text()).get("source_result_sha256") !=
                    source_hashes["result.json"]):
                raise RuntimeError("staged archive is not bound to terminal raw result")
        elif staged_hashes != source_hashes:
            raise RuntimeError("staged evidence differs from terminal raw")
        atomic_json(STATE / "raw-copy-receipt.json", {
            "schema_version": 1, "case_id": CASE, "source": str(SOURCE),
            "config_sha256": CONFIG_SHA, "files": source_hashes})

        archived = ensure(STAGING_ROOT, "campaign", CASE, reserve_bytes=FLOOR)
        result_path = staged_case / "result.json"
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
            [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(staged_case),
             "--out", str(staged_case / "offline-causal-audit.json")],
            cwd=BASE, env=env, text=True, capture_output=True)
        atomic_json(STATE / "audit-execution.json", {
            "exit_code": audit.returncode, "stdout": audit.stdout,
            "stderr": audit.stderr, "result_sha256": sha(result_path)})
        if audit.returncode not in (0, 2):
            raise RuntimeError(f"offline audit failed to execute: {audit.stderr}")
        audit_result = json.loads((staged_case / "offline-causal-audit.json").read_text())
        if audit_result.get("campaign_result_sha256") != sha(result_path):
            raise RuntimeError("audit/result hash mismatch")
        archive_dir = BASE / "data/mallory/evidence_archives/campaign"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for name in (f"{CASE}.tar.gz", f"{CASE}.tar.manifest.json"):
            source = STAGING_ROOT / "evidence_archives/campaign" / name
            target = archive_dir / name
            if target.exists():
                if sha(source) != sha(target):
                    raise RuntimeError(f"canonical archive conflict: {target}")
            else:
                shutil.copy2(source, target)
                if sha(source) != sha(target):
                    raise RuntimeError(f"archive copy hash mismatch: {target}")
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_case, DESTINATION)
        atomic_json(STATE / "terminal-publication.json", {
            "schema_version": 1, "case_id": CASE,
            "raw_result_sha256": source_hashes["result.json"],
            "canonical_result_sha256": sha(DESTINATION / "result.json"),
            "audit_sha256": sha(DESTINATION / "offline-causal-audit.json"),
            "archive_sha256": archived["archive_sha256"],
            "report_gate_passed": audit_result.get("report_gate_passed")})
        subprocess.run([sys.executable, "-m", "Mallory.report.build"], cwd=BASE,
                       check=True)


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
                print("HDFS-11 v27 terminal evidence published", flush=True)
                return
        elif subprocess.run(["tmux", "has-session", "-t", "mallory-node0-hdfs11-v27-full"],
                            capture_output=True).returncode != 0:
            raise RuntimeError("HDFS-11 full worker exited without a terminal result")
        time.sleep(15)


if __name__ == "__main__":
    main()
