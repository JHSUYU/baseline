"""Move terminal replay scratch to a verified archive on a different host.

Result, event, log, and audit files remain in place.  The receipt records every
removed scratch file so that the archive can restore its exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time

from .worker import atomic_json


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


REMOTE_VERIFY = r'''
import hashlib,json,os,pathlib,sys,tarfile
temporary=pathlib.Path(sys.argv[1])
final=pathlib.Path(sys.argv[2])
manifest_path=pathlib.Path(sys.argv[3])
expected=json.load(sys.stdin)
def digest_stream(stream):
    h=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
actual={}
with tarfile.open(temporary,'r:gz') as packed:
    for member in packed:
        if not member.isfile() or member.name in actual or member.name not in expected['files']:
            raise RuntimeError('unexpected archive member')
        source=packed.extractfile(member)
        actual[member.name]={'sha256':digest_stream(source),'bytes':member.size}
if actual!=expected['files']: raise RuntimeError('remote scratch bytes differ from source manifest')
with temporary.open('rb') as stream: os.fsync(stream.fileno())
archive_sha=digest_stream(temporary.open('rb'))
if final.exists():
    if digest_stream(final.open('rb'))!=archive_sha: raise RuntimeError('existing remote archive differs')
    temporary.unlink()
else: os.replace(temporary,final)
expected['archive_sha256']=archive_sha
expected['archive_bytes']=final.stat().st_size
manifest_path.write_text(json.dumps(expected,sort_keys=True,indent=2)+'\n')
print(json.dumps({'archive_sha256':archive_sha,'archive_bytes':final.stat().st_size,
                  'manifest_sha256':digest_stream(manifest_path.open('rb'))}))
'''


def _ssh(host: str, key: Path, argv: list[str]) -> list[str]:
    return ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            host, shlex.join(argv)]


def pack(data_root: Path, campaign: Path, name: str, host: str, key: Path,
         remote_root: Path) -> dict:
    data_root = data_root.resolve()
    campaign = campaign.resolve()
    if (not campaign.is_relative_to(data_root) or not name or
            "/" in name or ".." in name):
        raise ValueError("invalid replay path or archive name")
    result_path = campaign / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    sync_path = campaign / "sync-receipt.json"
    if (result.get("status") not in ("budget_exhausted", "queue_exhausted") or
            not sync_path.is_file()):
        raise ValueError("replay is not terminal and SHA-synced")
    files = sorted(path for path in campaign.glob("trials/*/scratch/**/*")
                   if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise ValueError("replay has no regular scratch files")
    members = {str(path.relative_to(campaign)): {
        "sha256": digest(path), "bytes": path.stat().st_size} for path in files}
    manifest = {"schema_version": 1,
                "campaign_relative": str(campaign.relative_to(data_root)),
                "result_sha256": digest(result_path),
                "sync_receipt_sha256": digest(sync_path),
                "files": members}
    receipt_dir = data_root / "evidence_archives/offhost_scratch"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{name}.receipt.json"
    if receipt_path.exists():
        raise RuntimeError("offhost scratch receipt already exists")
    temporary = remote_root / f".{name}.{os.getpid()}.tmp"
    final = remote_root / f"{name}.scratch.tar.gz"
    remote_manifest = remote_root / f"{name}.manifest.json"
    subprocess.run(_ssh(host, key, ["mkdir", "-p", str(remote_root)]), check=True)
    sink = subprocess.Popen(_ssh(host, key, ["sh", "-c",
                                  f"cat > {shlex.quote(str(temporary))}"]),
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=sink.stdin, mode="w|gz") as packed:
            for path in files:
                packed.add(path, arcname=str(path.relative_to(campaign)), recursive=False)
        sink.stdin.close()
        stderr = sink.stderr.read().decode("utf-8", errors="replace")
        if sink.wait() != 0:
            raise RuntimeError(f"remote scratch archive stream failed: {stderr[:300]}")
    except BaseException:
        if sink.poll() is None:
            sink.terminate()
        raise
    verified = subprocess.run(
        _ssh(host, key, ["python3", "-c", REMOTE_VERIFY,
                         str(temporary), str(final), str(remote_manifest)]),
        input=json.dumps(manifest), capture_output=True, text=True, timeout=1800)
    if verified.returncode:
        raise RuntimeError(f"remote scratch verification failed: {verified.stderr[:500]}")
    remote = json.loads(verified.stdout)
    receipt = {**manifest, "remote_host": host, "remote_archive": str(final),
               "remote_manifest": str(remote_manifest), **remote,
               "state": "verified_archive_prune_pending", "created_at": time.time()}
    atomic_json(receipt_path, receipt)
    for path in files:
        relative = str(path.relative_to(campaign))
        if (path.is_symlink() or digest(path) != members[relative]["sha256"] or
                path.stat().st_size != members[relative]["bytes"]):
            raise RuntimeError(f"scratch changed before removal: {relative}")
        path.unlink()
    receipt["state"] = "compacted"
    receipt["reclaimed_bytes"] = sum(row["bytes"] for row in members.values())
    receipt["removed_files"] = len(files)
    receipt["completed_at"] = time.time()
    atomic_json(receipt_path, receipt)
    return receipt


def restore_members(campaign: Path, packed, expected: dict) -> int:
    """Restore exact scratch bytes without overwriting any differing local file."""
    seen = set()
    restored = 0
    with tarfile.open(fileobj=packed, mode="r|gz") as archive:
        for member in archive:
            relative = Path(member.name)
            if (not member.isfile() or relative.is_absolute() or
                    ".." in relative.parts or member.name not in expected or
                    member.name in seen or
                    not member.name.startswith("trials/") or
                    "/scratch/" not in member.name):
                raise ValueError("unsafe or unexpected scratch archive member")
            seen.add(member.name)
            destination = campaign / relative
            if any(parent.is_symlink() for parent in destination.parents
                   if parent == campaign or campaign in parent.parents):
                raise ValueError("scratch restore path contains a symlink")
            row = expected[member.name]
            if member.size != row["bytes"]:
                raise ValueError("archived scratch size changed")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("archived scratch member is unreadable")
            if destination.exists():
                if destination.is_symlink() or digest(destination) != row["sha256"]:
                    raise ValueError("existing scratch differs from archive")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".mallory-restore-",
                                             dir=destination.parent,
                                             delete=False) as temporary:
                staged = Path(temporary.name)
                shutil.copyfileobj(source, temporary, 1024 * 1024)
            try:
                if (staged.stat().st_size != row["bytes"] or
                        digest(staged) != row["sha256"]):
                    raise ValueError("restored scratch differs from receipt")
                os.replace(staged, destination)
                restored += 1
            finally:
                staged.unlink(missing_ok=True)
    if seen != set(expected):
        raise ValueError("scratch archive omitted receipt members")
    return restored


def restore(data_root: Path, receipt_path: Path, key: Path) -> int:
    """Stream a verified off-host archive back without a local archive copy."""
    data_root = data_root.resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    campaign = data_root / receipt["campaign_relative"]
    if (receipt.get("state") != "compacted" or
            not campaign.resolve().is_relative_to(data_root) or
            digest(campaign / "result.json") != receipt["result_sha256"] or
            digest(campaign / "sync-receipt.json") != receipt["sync_receipt_sha256"]):
        raise ValueError("offhost scratch receipt is not bound to this replay")
    host = receipt["remote_host"]
    archive = receipt["remote_archive"]
    manifest = receipt["remote_manifest"]
    check = subprocess.run(_ssh(host, key, ["sha256sum", archive, manifest]),
                           capture_output=True, text=True, timeout=300, check=True)
    lines = check.stdout.splitlines()
    if (len(lines) != 2 or lines[0].split()[0] != receipt["archive_sha256"] or
            lines[1].split()[0] != receipt["manifest_sha256"]):
        raise ValueError("remote scratch archive or manifest hash changed")
    source = subprocess.Popen(_ssh(host, key, ["cat", archive]), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    try:
        restored = restore_members(campaign, source.stdout, receipt["files"])
        source.stdout.close()
        if source.wait() != 0:
            raise RuntimeError("remote scratch archive stream failed")
        return restored
    finally:
        if source.poll() is None:
            source.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-receipt", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--host")
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--remote-root", type=Path)
    args = parser.parse_args()
    if args.restore_receipt:
        print(json.dumps({"restored_files": restore(
            args.data_root, args.restore_receipt, args.ssh_key)}))
        return 0
    if not all((args.campaign, args.name, args.host, args.remote_root)):
        parser.error("pack requires campaign, name, host, and remote root")
    row = pack(args.data_root, args.campaign, args.name, args.host,
               args.ssh_key, args.remote_root)
    print(json.dumps({key: row[key] for key in
                      ("remote_archive", "archive_sha256", "archive_bytes",
                       "reclaimed_bytes", "removed_files", "state")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
