#!/usr/bin/env python3
"""Archive and independently restore-check every HDFS-32 V3 raw artifact."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ARCHIVE_DIR = HERE / "archive"
RECEIPT = ARCHIVE_DIR / "raw-v3-archive-receipt.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def durable(path: Path, data: bytes) -> None:
    pending = path.with_name(path.name + ".tmp")
    with pending.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def main() -> None:
    checkpoint = HERE / "checkpoint.json"
    inventory_file = HERE / "raw-inventory.json"
    audit_file = HERE / "audit-v3.json"
    terminal_file = HERE / "terminal-v3.json"
    state = json.loads(checkpoint.read_text())
    inventory = json.loads(inventory_file.read_text())
    terminal = json.loads(terminal_file.read_text())
    files = inventory["files"]
    if (state.get("case") != "HDFS-32" or state.get("active") is not None
            or state.get("stop_reason") != "effective_budget_met_pending_independent_audit"
            or inventory["errors"] or len(files) != inventory["raw_file_count"]
            or inventory["checkpoint_sha256"] != sha(checkpoint)
            or inventory["semantic_audit_sha256"] != sha(audit_file)
            or terminal["checkpoint_sha256"] != sha(checkpoint)
            or terminal["raw_inventory_sha256"] != sha(inventory_file)):
        raise RuntimeError("terminal and raw inventory are not stable or consistent")
    paths = sorted(files)
    for name in paths:
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or
                relative.parts[0] not in ("healthy-a", "healthy-b", "pilot-01", "runs") or
                not (HERE / relative).is_file() or (HERE / relative).is_symlink()):
            raise RuntimeError("invalid raw inventory path: " + name)
        if ((HERE / relative).stat().st_size != files[name]["bytes"] or
                sha(HERE / relative) != files[name]["sha256"]):
            raise RuntimeError("raw file changed since inventory: " + name)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    archive = ARCHIVE_DIR / ("raw-v3-" + sha(checkpoint)[:16] + ".tar.zst")
    if RECEIPT.exists():
        old = json.loads(RECEIPT.read_text())
        if (old["checkpoint_sha256"] != sha(checkpoint) or
                old["archive_sha256"] != sha(archive) or
                old["file_count"] != len(files)):
            raise RuntimeError("existing archive receipt conflicts with terminal run")
        print(json.dumps(old, sort_keys=True))
        return
    if archive.exists():
        raise RuntimeError("unreceipted archive already exists")
    with tempfile.TemporaryDirectory(prefix="hdfs32-archive-", dir=ARCHIVE_DIR) as temp:
        temp_dir = Path(temp)
        listing = temp_dir / "paths.nul"
        listing.write_bytes(b"\0".join(p.encode() for p in paths) + b"\0")
        pending = temp_dir / "raw.tar.zst"
        subprocess.run(["tar", "--zstd", "-cf", str(pending), "-C", str(HERE),
                        "--null", "-T", str(listing)], check=True)
        restored = temp_dir / "restored"
        restored.mkdir()
        subprocess.run(["tar", "--zstd", "-xf", str(pending), "-C", str(restored)],
                       check=True)
        actual = sorted(str(p.relative_to(restored)) for p in restored.rglob("*")
                        if p.is_file())
        if actual != paths:
            raise RuntimeError("restored archive file set differs from raw inventory")
        for name in paths:
            restored_file = restored / name
            if (restored_file.stat().st_size != files[name]["bytes"] or
                    sha(restored_file) != files[name]["sha256"]):
                raise RuntimeError("restored archive SHA mismatch: " + name)
        if (sha(checkpoint) != inventory["checkpoint_sha256"] or
                sha(inventory_file) != terminal["raw_inventory_sha256"]):
            raise RuntimeError("terminal metadata changed during archiving")
        pending.replace(archive)
    receipt = {"schema": 1, "case": "HDFS-32", "archive": str(archive),
               "archive_sha256": sha(archive), "archive_bytes": archive.stat().st_size,
               "checkpoint_sha256": sha(checkpoint),
               "raw_inventory_sha256": sha(inventory_file),
               "terminal_receipt_sha256": sha(terminal_file),
               "file_count": len(files), "raw_total_bytes": inventory["raw_total_bytes"],
               "restore_sha_verified": True}
    durable(RECEIPT, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
