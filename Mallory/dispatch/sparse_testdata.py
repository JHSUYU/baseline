"""Verify sparse remote test data before pruning an expanded local copy.

The terminal result, audit, event traces, and logs remain local.  A receipt
lists every removed file and allows byte-for-byte restoration from the
untouched remote campaign tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

from .worker import atomic_json


REMOTE_TREE = r'''
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); files={}
def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()
for path in sorted(root.glob('trials/r*/test-data/**/*')):
    if path.is_symlink(): raise ValueError('symlink in test-data')
    if path.is_file():
        files[str(path.relative_to(root))]={'bytes':path.stat().st_size,
                                            'sha256':sha(path)}
print(json.dumps({'files':files,'result_sha256':sha(root/'result.json'),
                  'audit_sha256':sha(root/'offline-causal-audit.json')},sort_keys=True))
'''


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def members(root: Path) -> dict[str, dict]:
    found = {}
    for path in sorted(root.glob("trials/r*/test-data/**/*")):
        if path.is_symlink():
            raise ValueError(f"symlink in test-data: {path}")
        if path.is_file():
            found[str(path.relative_to(root))] = {
                "bytes": path.stat().st_size, "sha256": sha(path)}
    return found


def ssh(host: str, key: Path, *args: str) -> list[str]:
    return ["ssh", "-i", str(key), "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", host, shlex.join(args)]


def checked_relative(name: str) -> Path:
    relative = Path(name)
    if (relative.is_absolute() or ".." in relative.parts or
            len(relative.parts) < 4 or relative.parts[0] != "trials" or
            relative.parts[2] != "test-data" or
            not relative.parts[1].startswith("r")):
        raise ValueError(f"unsafe test-data member: {name}")
    return relative


def compact(root: Path, receipt_path: Path, host: str, key: Path) -> dict:
    if receipt_path.exists():
        raise ValueError("receipt already exists; inspect or restore it")
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    result_sha, audit_sha = sha(result_path), sha(audit_path)
    if (result.get("status") not in ("calibration_complete", "budget_exhausted",
                                     "queue_exhausted") or
            audit.get("report_gate_passed") is not True or
            audit.get("campaign_result_sha256") != result_sha or
            audit.get("case_id") != result.get("case_id")):
        raise ValueError("terminal result and passing audit do not bind")
    local = members(root)
    if not local:
        raise ValueError("no local trial test-data files")
    remote = json.loads(subprocess.run(
        ssh(host, key, "python3", "-c", REMOTE_TREE, str(root)),
        capture_output=True, text=True, check=True, timeout=600).stdout)
    if (local != remote["files"] or
            remote["result_sha256"] != result_sha or
            remote["audit_sha256"] != audit_sha):
        raise ValueError("local test data or result/audit differs from remote")
    receipt = {"schema_version": 1, "state": "verified_remote_prune_pending",
               "case_id": result["case_id"], "local_root": str(root),
               "remote_host": host, "remote_root": str(root),
               "result_sha256": result_sha, "audit_sha256": audit_sha,
               "files": local, "verified_at": time.time()}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(receipt_path, receipt)
    allocated = 0
    for name, expected in local.items():
        path = root / checked_relative(name)
        if (path.is_symlink() or path.stat().st_size != expected["bytes"] or
                sha(path) != expected["sha256"]):
            raise ValueError(f"local test data changed before prune: {name}")
        allocated += path.stat().st_blocks * 512
        path.unlink()
    for folder in sorted(root.glob("trials/r*/test-data/**/*"), reverse=True):
        if folder.is_dir():
            folder.rmdir()
    for folder in sorted(root.glob("trials/r*/test-data")):
        folder.rmdir()
    receipt.update(state="compacted", removed_files=len(local),
                   reclaimed_allocated_bytes=allocated,
                   reclaimed_logical_bytes=sum(row["bytes"] for row in local.values()),
                   completed_at=time.time())
    atomic_json(receipt_path, receipt)
    return receipt


def restore(receipt_path: Path, destination_root: Path, key: Path) -> int:
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("state") != "compacted":
        raise ValueError("receipt is not compacted")
    root = Path(receipt["local_root"])
    if (sha(root / "result.json") != receipt["result_sha256"] or
            sha(root / "offline-causal-audit.json") != receipt["audit_sha256"]):
        raise ValueError("terminal result or audit changed")
    restored = 0
    for name, expected in receipt["files"].items():
        relative = checked_relative(name)
        destination = destination_root / relative
        if destination.exists():
            if (destination.is_symlink() or
                    destination.stat().st_size != expected["bytes"] or
                    sha(destination) != expected["sha256"]):
                raise ValueError(f"existing test-data member differs: {name}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            staged = Path(stream.name)
            transfer = subprocess.run(
                ssh(receipt["remote_host"], key, "cat",
                    str(Path(receipt["remote_root"]) / relative)),
                stdout=stream, stderr=subprocess.PIPE)
        try:
            if (transfer.returncode or staged.stat().st_size != expected["bytes"] or
                    sha(staged) != expected["sha256"]):
                raise ValueError(f"offhost restore failed: {name}")
            os.replace(staged, destination)
            restored += 1
        finally:
            staged.unlink(missing_ok=True)
    return restored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--host", default="node2")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--restore-to", type=Path)
    args = parser.parse_args()
    if args.restore_to:
        print(json.dumps({"restored_files": restore(
            args.receipt, args.restore_to.resolve(), args.ssh_key)}))
    else:
        if args.campaign is None:
            parser.error("--campaign is required unless restoring")
        receipt = compact(args.campaign.resolve(), args.receipt.resolve(),
                          args.host, args.ssh_key)
        print(json.dumps({key: receipt[key] for key in
                          ("state", "removed_files", "reclaimed_allocated_bytes",
                           "reclaimed_logical_bytes")}))


if __name__ == "__main__":
    main()
