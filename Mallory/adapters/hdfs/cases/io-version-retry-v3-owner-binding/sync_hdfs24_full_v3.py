#!/usr/bin/env python3
"""Sync a terminal, SHA-verified HDFS-24 v3 case from node2 to node0."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


BASE = Path("/users/ZhenyuLi/baseline")
STATE = BASE / "data/mallory/dispatch/node0-hdfs24-v3-full"
CANONICAL = BASE / "data/mallory/cases/HDFS-24"
LOCAL_ARCHIVES = BASE / "data/mallory/evidence_archives/campaign"
REMOTE_STATE = BASE / "data/mallory/dispatch/node2-hdfs24-v3-full"
REMOTE_CASE = BASE / "data/mallory/cases/HDFS-24"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "f8cf3c0f58559f66c52d1b734534f0438d8046acc8f2b1c0031c3f5ec0331884"
KEY = Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes")
FLOOR = 5 * 1024**3


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def files(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha(path) for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != ".campaign.lock"}


def remote_receipt() -> dict | None:
    command = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
               "ZhenyuLi@node2", "cat", str(REMOTE_STATE / "terminal-publication.json")]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if result.returncode:
        if "No such file" in result.stderr:
            return None
        raise RuntimeError(f"node2 publication receipt unavailable: {result.stderr[:300]}")
    receipt = json.loads(result.stdout)
    if receipt.get("case_id") != "HDFS-24" or receipt.get("config_sha256") != CONFIG_SHA:
        raise ValueError("node2 receipt belongs to a different configuration")
    if receipt.get("status") not in {"budget_exhausted", "queue_exhausted"}:
        raise ValueError("node2 case is not terminal")
    return receipt


def rsync(source: Path, destination: Path, *, directory: bool = False) -> None:
    ssh = f"ssh -i {KEY} -o IdentitiesOnly=yes -o BatchMode=yes"
    remote = f"ZhenyuLi@node2:{source}{'/' if directory else ''}"
    destination.mkdir(parents=True, exist_ok=True) if directory else destination.parent.mkdir(parents=True, exist_ok=True)
    command = ["rsync", "-a", "-e", ssh]
    if directory:
        command += ["--exclude", ".campaign.lock"]
    subprocess.run(command + [remote, str(destination)], check=True, timeout=600)


def publish(receipt: dict) -> None:
    if CANONICAL.exists():
        raise FileExistsError(f"canonical HDFS-24 already exists: {CANONICAL}")
    expected = receipt.get("files")
    if not isinstance(expected, dict) or not expected or "result.json" not in expected:
        raise ValueError("node2 per-file hashes missing")
    required = receipt.get("case_bytes", 0) + receipt.get("archive_bytes", 0)
    if not isinstance(required, int) or required <= 0:
        raise ValueError("node2 case/archive size receipt missing")
    if shutil.disk_usage(BASE).free < FLOOR + required + 64 * 1024**2:
        raise RuntimeError("node0 disk reserve insufficient for copy")
    imported = STATE / "import/HDFS-24"
    rsync(REMOTE_CASE, imported, directory=True)
    if files(imported) != expected:
        raise ValueError("remote case files differ from SHA-bound publication receipt")
    if sha(imported / "result.json") != receipt["canonical_result_sha256"] or \
            sha(imported / "offline-causal-audit.json") != receipt["audit_sha256"] or \
            sha(imported / "config.json") != CONFIG_SHA:
        raise ValueError("node2 result/audit/config digest mismatch")
    incoming = STATE / "import/evidence_archives/campaign"
    archive = incoming / "HDFS-24.tar.gz"
    manifest = incoming / "HDFS-24.tar.manifest.json"
    rsync(Path(receipt["archive_path"]), archive)
    rsync(Path(receipt["archive_manifest_path"]), manifest)
    if sha(archive) != receipt["archive_sha256"] or \
            sha(manifest) != receipt["archive_manifest_sha256"]:
        raise ValueError("node2 evidence archive digest mismatch")
    if shutil.disk_usage(BASE).free < FLOOR + sum(p.stat().st_size for p in (archive, manifest)) + 64 * 1024**2:
        raise RuntimeError("node0 disk reserve insufficient for publication")
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{RELEASE}:{BASE}"
    check = subprocess.run(
        [sys.executable, "-m", "Mallory.core.audit", "--campaign", str(imported),
         "--out", str(STATE / "node0-offline-causal-audit.json")],
        cwd=BASE, env=env, capture_output=True, text=True)
    if check.returncode not in (0, 2):
        raise RuntimeError(f"node0 frozen audit execution failed: {check.stderr[:500]}")
    cross_audit = json.loads((STATE / "node0-offline-causal-audit.json").read_text())
    if cross_audit.get("campaign_result_sha256") != expected["result.json"]:
        raise ValueError("node0 audit/result digest mismatch")
    LOCAL_ARCHIVES.mkdir(parents=True, exist_ok=True)
    for source in (archive, manifest):
        target = LOCAL_ARCHIVES / source.name
        if target.exists():
            if sha(target) != sha(source):
                raise FileExistsError(f"conflicting canonical evidence archive: {target}")
        else:
            shutil.copy2(source, target)
            if sha(target) != sha(source):
                raise ValueError("archive copy changed during publication")
    CANONICAL.parent.mkdir(parents=True, exist_ok=True)
    os.replace(imported, CANONICAL)
    final = {"schema_version": 1, "case_id": "HDFS-24", "status": receipt["status"],
             "config_sha256": CONFIG_SHA, "result_sha256": sha(CANONICAL / "result.json"),
             "audit_sha256": sha(CANONICAL / "offline-causal-audit.json"),
             "archive_sha256": sha(LOCAL_ARCHIVES / "HDFS-24.tar.gz"),
             "files": files(CANONICAL),
             "node0_audit_gate_passed": cross_audit.get("report_gate_passed")}
    (STATE / "terminal-sync.json").write_text(json.dumps(final, indent=2, sort_keys=True) + "\n")
    subprocess.run([sys.executable, "-m", "Mallory.report.build"], cwd=BASE, check=True)


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    while True:
        receipt = remote_receipt()
        if receipt is not None:
            publish(receipt)
            print("HDFS-24 v3 terminal case published on node0", flush=True)
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
