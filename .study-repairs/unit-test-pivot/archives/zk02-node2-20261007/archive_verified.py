#!/usr/bin/env python3
"""Archive completed legacy ZK02 traces, mirror, verify, then remove raw copies.

This operates only on the 26 raw attempt traces and schedules left in the
completed node2 GraphChecker campaign. It leaves the prior 248-entry manifest
untouched, writes one immutable SHA receipt per file on both hosts, and can
resume after a failed transfer. No active campaign may use this path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
SCP = ["scp", "-3", "-q", "-i", str(KEY), "-o", "IdentitiesOnly=yes",
       "-o", "BatchMode=yes"]
CASE = Path("/users/ZhenyuLi/zk02-unit/campaign/results/ZOOKEEPER-02")
MIRROR = Path("/users/ZhenyuLi/zk02-archive-mirror-20261007")
RECEIPT_ROOT = CASE / "archive-v2-receipts"
FILES = {"runtime_trace.jsonl", "schedule.jsonl"}


def remote(host: str, command: str, *, check: bool = True) -> str:
    result = subprocess.run(SSH + [f"ZhenyuLi@{host}", command], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise RuntimeError(f"{host}: {command}\n{result.stderr}")
    return result.stdout.strip()


def q(path: Path | str) -> str:
    return shlex.quote(str(path))


def sha(host: str, path: Path) -> str:
    return remote(host, f"sha256sum {q(path)}").split()[0]


def file_bytes(host: str, path: Path) -> int:
    return int(remote(host, f"stat -c %s {q(path)}"))


def raw_files() -> list[Path]:
    code = ("import json; from pathlib import Path; "
            f"r=Path({str(CASE)!r})/'trials'; "
            f"print(json.dumps(sorted(str(p) for p in r.glob('*/attempt-*/trace/*') "
            f"if p.name in {sorted(FILES)!r})))")
    return [Path(item) for item in json.loads(remote("node2", "python3 -c " + q(code)))]


def write_receipt(host: str, path: Path, row: dict) -> None:
    existing = remote(host, f"test -f {q(path)} && cat {q(path)}", check=False)
    if existing:
        saved = json.loads(existing)
        if any(saved.get(key) != row[key] for key in
               ("original", "original_sha256", "original_bytes", "archive",
                "archive_sha256", "archive_bytes", "mirror")):
            raise RuntimeError(f"immutable receipt differs: {host}:{path}")
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(row, tmp, sort_keys=True, indent=2)
        tmp.write("\n")
        local = Path(tmp.name)
    try:
        remote(host, f"mkdir -p {q(path.parent)}")
        subprocess.run(SCP[:1] + SCP[2:] + [str(local),
                       f"ZhenyuLi@{host}:{path}.part"], check=True)
        remote(host, f"mv {q(str(path) + '.part')} {q(path)}")
        if hashlib.sha256(remote(host, f"cat {q(path)}").encode().rstrip(b"\n") + b"\n").hexdigest() != hashlib.sha256(local.read_bytes()).hexdigest():
            raise RuntimeError(f"receipt copy differs: {host}:{path}")
    finally:
        local.unlink(missing_ok=True)


def one(raw: Path) -> dict:
    relative = raw.relative_to(CASE)
    archive = Path(str(raw) + ".zst")
    mirror = MIRROR / (str(relative) + ".zst")
    receipt_rel = Path(str(relative) + ".json")
    if remote("node2", f"test -f {q(raw)} && echo yes", check=False) != "yes":
        raise RuntimeError(f"raw disappeared before verification: {raw}")
    original_sha = sha("node2", raw)
    original_bytes = file_bytes("node2", raw)
    if remote("node2", f"test -f {q(archive)} && echo yes", check=False) != "yes":
        part = Path(str(archive) + ".part")
        remote("node2", f"nice -n 15 ionice -c3 zstd -1 -T1 -f -q -o {q(part)} {q(raw)}")
        remote("node2", f"zstd -t -q {q(part)} && mv {q(part)} {q(archive)}")
    remote("node2", f"zstd -t -q {q(archive)}")
    extracted_sha = remote("node2", f"bash -o pipefail -c {q('zstd -dc ' + q(archive) + ' | sha256sum')}").split()[0]
    if extracted_sha != original_sha:
        raise RuntimeError(f"decompressed data differs: {raw}")
    archive_sha = sha("node2", archive)
    archive_bytes = file_bytes("node2", archive)
    remote("node1", f"mkdir -p {q(mirror.parent)}")
    mirror_part = Path(str(mirror) + ".part")
    subprocess.run(SCP + [f"ZhenyuLi@node2:{archive}",
                          f"ZhenyuLi@node1:{mirror_part}"], check=True)
    if sha("node1", mirror_part) != archive_sha:
        raise RuntimeError(f"mirror archive differs: {mirror_part}")
    remote("node1", f"mv {q(mirror_part)} {q(mirror)}")
    row = {"schema": "zk02-legacy-verified-archive-v2", "original": str(raw),
           "original_sha256": original_sha, "original_bytes": original_bytes,
           "archive": str(archive), "archive_sha256": archive_sha,
           "archive_bytes": archive_bytes, "mirror": str(mirror),
           "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    write_receipt("node2", RECEIPT_ROOT / receipt_rel, row)
    write_receipt("node1", MIRROR / "receipts" / receipt_rel, row)
    if remote("node2", f"lsof {q(raw)}", check=False):
        raise RuntimeError(f"raw file is open; preserving: {raw}")
    remote("node2", f"python3 -c {q('from pathlib import Path; Path(' + repr(str(raw)) + ').unlink()')}")
    print(json.dumps({"archived": str(relative), "original_bytes": original_bytes,
                      "archive_bytes": archive_bytes, "sha256": original_sha}), flush=True)
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    paths = raw_files()
    print(json.dumps({"raw_files": len(paths), "path": str(CASE / "trials"),
                      "mode": "run" if args.run else "inventory"}), flush=True)
    if not args.run:
        return
    processes = remote("node2", "lsof +D " + q(CASE / "trials"), check=False)
    if processes:
        raise RuntimeError("an active process has a ZK02 trial file open:\n" + processes)
    legacy_sha = sha("node2", CASE / "archive-manifest.jsonl")
    for path in paths:
        one(path)
    inventory_code = ("import json; from pathlib import Path; "
                      f"r=Path({str(RECEIPT_ROOT)!r}); "
                      "print(json.dumps([json.loads(p.read_text()) for p in "
                      "sorted(r.rglob('*.json'))]))")
    receipts = json.loads(remote("node2", "python3 -c " + q(inventory_code)))
    if len(receipts) != 52 or raw_files():
        raise RuntimeError(f"expected 52 verified receipts and no raw files; got {len(receipts)}")
    manifest = CASE / "archive-v2-manifest.jsonl"
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in receipts)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp.write(content)
        local = Path(tmp.name)
    try:
        for host, dest in (("node2", manifest), ("node1", MIRROR / "archive-v2-manifest.jsonl")):
            if remote(host, f"test -f {q(dest)} && echo yes", check=False) == "yes":
                if sha(host, dest) != hashlib.sha256(content.encode()).hexdigest():
                    raise RuntimeError(f"immutable manifest differs: {host}:{dest}")
                continue
            subprocess.run(SCP[:1] + SCP[2:] + [str(local), f"ZhenyuLi@{host}:{dest}.part"], check=True)
            remote(host, f"mv {q(str(dest) + '.part')} {q(dest)}")
            if sha(host, dest) != hashlib.sha256(content.encode()).hexdigest():
                raise RuntimeError(f"manifest mirror differs: {host}:{dest}")
    finally:
        local.unlink(missing_ok=True)
    if sha("node2", CASE / "archive-manifest.jsonl") != legacy_sha:
        raise RuntimeError("legacy archive manifest changed")
    print(json.dumps({"complete": True, "files": len(receipts),
                      "manifest_sha256": hashlib.sha256(content.encode()).hexdigest(),
                      "legacy_manifest_sha256": legacy_sha,
                      "node2_free_bytes": int(remote("node2", "df -B1 --output=avail " + q(CASE) + " | tail -1"))}), flush=True)


if __name__ == "__main__":
    main()
