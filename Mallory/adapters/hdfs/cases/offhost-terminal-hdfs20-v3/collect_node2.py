#!/usr/bin/env python3
"""Seal a terminal HDFS campaign on node2 with all raw trial evidence."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

BASE = Path("/users/ZhenyuLi/baseline")
sys.path.insert(0, str(BASE))
from Mallory.dispatch.archive import ensure
from Mallory.dispatch.worker import atomic_json

HERE = BASE / "Mallory/adapters/hdfs/cases/offhost-terminal-hdfs20-v3"
MANIFEST = HERE / "cases.json"
TERMINAL = {"budget_exhausted", "queue_exhausted"}
FLOOR = 5 * 1024**3
HEADROOM = 128 * 1024**2


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha(path) for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != ".campaign.lock"}


def size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def settings(case: str, manifest_sha: str) -> tuple[dict, dict]:
    if sha(MANIFEST) != manifest_sha:
        raise RuntimeError("offhost collector manifest SHA changed")
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("owner_host") != "node2" or
            case not in manifest.get("cases", {})):
        raise RuntimeError("case missing from pinned offhost collector manifest")
    row = manifest["cases"][case]
    config = Path(row["config_path"])
    if not config.is_file() or sha(config) != row["config_sha256"]:
        raise RuntimeError("case config differs from pinned full campaign")
    if json.loads(config.read_text()).get("case_id") != case:
        raise RuntimeError("case ID/config mismatch")
    release = Path(manifest["core_release"])
    if sha(release / "manifest.json") != manifest["core_release_manifest_sha256"]:
        raise RuntimeError("frozen core release changed")
    return row, manifest


def terminal_ready(source: Path, case: str) -> bool:
    paths = (source / "checkpoint.json", source / "result.json")
    if not all(path.is_file() for path in paths):
        return False
    checkpoint, result = (json.loads(path.read_text()) for path in paths)
    if checkpoint.get("status") not in TERMINAL:
        return False
    if (result.get("status") != checkpoint.get("status") or
            checkpoint.get("running") is not None or
            result.get("case_id") != case or checkpoint.get("case_id") != case):
        raise RuntimeError("terminal checkpoint/result mismatch")
    return True


def seal_existing(case: str, row: dict, raw: dict[str, str]) -> dict:
    state = Path(row["node2_state_root"])
    publication = state / "publication"
    canonical = BASE / "data/mallory/cases" / case
    archive = publication / "evidence_archives/campaign" / f"{case}.tar.gz"
    archive_manifest = archive.with_name(f"{case}.tar.manifest.json")
    result_path = canonical / "result.json"
    audit_path = canonical / "offline-causal-audit.json"
    for path in (result_path, audit_path, archive, archive_manifest):
        if not path.is_file():
            raise RuntimeError(f"incomplete terminal publication: {path}")
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    packed = json.loads(archive_manifest.read_text())
    if (result.get("case_id") != case or result.get("status") not in TERMINAL or
            sha(canonical / "config.json") != row["config_sha256"] or
            audit.get("campaign_result_sha256") != sha(result_path) or
            packed.get("source_result_sha256") != raw.get("result.json") or
            packed.get("archive_sha256") != sha(archive) or
            result.get("evidence_archive", {}).get("sha256") != sha(archive) or
            sorted(packed.get("members", [])) != sorted(raw) or
            any(sha(canonical / name) != digest for name, digest in raw.items()
                if name != "result.json")):
        raise RuntimeError("terminal publication differs from locked raw evidence")
    receipt = {
        "schema_version": 1, "case_id": case, "status": result["status"],
        "raw_result_sha256": raw["result.json"],
        "canonical_result_sha256": sha(result_path),
        "config_sha256": row["config_sha256"], "audit_sha256": sha(audit_path),
        "report_gate_passed": audit.get("report_gate_passed"),
        "archive_path": str(archive), "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_manifest_path": str(archive_manifest),
        "archive_manifest_sha256": sha(archive_manifest),
        "files": tree(canonical), "case_bytes": size(canonical),
    }
    atomic_json(state / "terminal-publication.json", receipt)
    return receipt


def collect(case: str, row: dict, manifest: dict) -> dict:
    source = Path(row["source_output"])
    state = Path(row["node2_state_root"])
    publication = state / "publication"
    canonical = BASE / "data/mallory/cases" / case
    with (source / ".campaign.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not terminal_ready(source, case) or sha(source / "config.json") != row["config_sha256"]:
            raise RuntimeError("terminal source or pinned config changed")
        raw = tree(source)
        if canonical.exists():
            return seal_existing(case, row, raw)
        if shutil.disk_usage(BASE).free < FLOOR + 2 * size(source) + HEADROOM:
            raise RuntimeError("node2 disk reserve insufficient for raw copy and archive")
        staged = publication / "cases" / case
        if not staged.exists():
            temporary = staged.with_name(f".{case}.copy-{os.getpid()}")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, temporary, ignore=shutil.ignore_patterns(".campaign.lock"))
            if tree(temporary) != raw:
                raise RuntimeError("raw staging copy SHA mismatch")
            os.replace(temporary, staged)
        staged_hashes = tree(staged)
        if staged_hashes != raw:
            # Recovery after archive/result mutation is valid only with a
            # manifest that binds the original terminal result and files.
            archived_manifest = publication / "evidence_archives/campaign" / f"{case}.tar.manifest.json"
            if (not archived_manifest.is_file() or
                    json.loads(archived_manifest.read_text()).get("source_result_sha256") != raw["result.json"] or
                    any(staged_hashes.get(name) != digest for name, digest in raw.items()
                        if name != "result.json")):
                raise RuntimeError("staged evidence differs from terminal raw")
        atomic_json(state / "raw-copy-receipt.json", {
            "schema_version": 1, "case_id": case, "source": str(source),
            "config_sha256": row["config_sha256"], "files": raw})
        archived = ensure(publication, "campaign", case, reserve_bytes=FLOOR + HEADROOM)
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
        env["PYTHONPATH"] = f"{manifest['core_release']}:{BASE}"
        audit = subprocess.run(
            [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(staged),
             "--out", str(staged / "offline-causal-audit.json")],
            cwd=BASE, env=env, capture_output=True, text=True)
        atomic_json(state / "audit-execution.json", {
            "exit_code": audit.returncode, "stdout": audit.stdout,
            "stderr": audit.stderr, "result_sha256": sha(result_path)})
        if audit.returncode not in (0, 2):
            raise RuntimeError(f"frozen audit execution failed: {audit.stderr[:500]}")
        checked = json.loads((staged / "offline-causal-audit.json").read_text())
        if checked.get("campaign_result_sha256") != sha(result_path):
            raise RuntimeError("frozen audit/result hash mismatch")
        canonical.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, canonical)
        return seal_existing(case, row, raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--manifest-sha", required=True)
    parser.add_argument("--worker-session", required=True)
    args = parser.parse_args()
    row, manifest = settings(args.case, args.manifest_sha)
    state = Path(row["node2_state_root"])
    state.mkdir(parents=True, exist_ok=True)
    source = Path(row["source_output"])
    while True:
        if terminal_ready(source, args.case):
            try:
                receipt = collect(args.case, row, manifest)
            except BlockingIOError:
                pass
            except RuntimeError as exc:
                if "disk reserve" not in str(exc):
                    raise
                print(str(exc), flush=True)
            else:
                print(json.dumps({"status": "terminal_sealed", "case_id": args.case,
                                  "result_sha256": receipt["canonical_result_sha256"],
                                  "audit_sha256": receipt["audit_sha256"]}, sort_keys=True), flush=True)
                return
        elif subprocess.run(["tmux", "has-session", "-t", args.worker_session],
                            capture_output=True).returncode != 0:
            time.sleep(5)
            if not terminal_ready(source, args.case):
                raise RuntimeError("worker exited without terminal result")
            continue
        time.sleep(15)


if __name__ == "__main__":
    main()
