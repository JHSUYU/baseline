#!/usr/bin/env python3
"""Offload only archived, reproducible HDFS-32 coverage text after full SHA audit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"
INVENTORY = HERE / "raw-inventory.json"
TERMINAL = HERE / "terminal-v3.json"
ARCHIVE_RECEIPT = ARCHIVE / "raw-v3-archive-receipt.json"
MIRROR_PROOF = ARCHIVE / "node0-mirror-proof.json"
INTENT = ARCHIVE / "coverage-prune-intent.json"
RECEIPT = ARCHIVE / "coverage-prune-receipt.json"
COVERAGE = {"covered_lines.txt", "covered_probes.txt",
            "covered_methods.txt", "covered_branch_counts.txt"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def durable(path: Path, value: dict) -> None:
    pending = path.with_name(path.name + ".tmp")
    with pending.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> None:
    state = json.loads((HERE / "checkpoint.json").read_text())
    inventory = json.loads(INVENTORY.read_text())
    terminal = json.loads(TERMINAL.read_text())
    archive_receipt = json.loads(ARCHIVE_RECEIPT.read_text())
    proof = json.loads(MIRROR_PROOF.read_text())
    archive = Path(archive_receipt["archive"])
    if (state.get("case") != "HDFS-32" or state.get("active") is not None
            or state.get("stop_reason") != "effective_budget_met_pending_independent_audit"
            or inventory["errors"] or not archive_receipt["restore_sha_verified"]
            or inventory["checkpoint_sha256"] != sha(HERE / "checkpoint.json")
            or terminal["raw_inventory_sha256"] != sha(INVENTORY)
            or archive_receipt["raw_inventory_sha256"] != sha(INVENTORY)
            or archive_receipt["terminal_receipt_sha256"] != sha(TERMINAL)
            or proof["mirror_host"] != "node0"
            or proof["node2_archive_receipt_sha256"] != sha(ARCHIVE_RECEIPT)
            or proof["archive_sha256"] != archive_receipt["archive_sha256"]
            or proof["archive_bytes"] != archive_receipt["archive_bytes"]
            or proof["checkpoint_sha256"] != sha(HERE / "checkpoint.json")
            or not archive.is_file() or sha(archive) != proof["archive_sha256"]):
        raise RuntimeError("terminal, archive, and node0 mirror proof disagree")
    files = inventory["files"]
    selected = sorted(name for name in files if Path(name).name in COVERAGE)
    if len(selected) != 4 * 148:
        raise RuntimeError("unexpected coverage-file count")
    for name in files:
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts
                or relative.parts[0] not in ("healthy-a", "healthy-b", "pilot-01", "runs")):
            raise RuntimeError("invalid inventory path: " + name)
    intent = {"schema": 1, "case": "HDFS-32", "scope": "derived_coverage_text_only",
              "checkpoint_sha256": sha(HERE / "checkpoint.json"),
              "raw_inventory_sha256": sha(INVENTORY),
              "archive_receipt_sha256": sha(ARCHIVE_RECEIPT),
              "node0_mirror_proof_sha256": sha(MIRROR_PROOF),
              "archive_sha256": sha(archive),
              "selected_paths": selected,
              "selected_files": len(selected),
              "selected_bytes": sum(files[name]["bytes"] for name in selected),
              "kept_raw_kinds": ["manifest.json", "fault-plan.tsv", "runtime_trace.jsonl",
                                 "junit.log", "jacoco.exec", "driver.log"]}
    if RECEIPT.exists():
        old = json.loads(RECEIPT.read_text())
        if old != intent or any((HERE / name).exists() for name in selected):
            raise RuntimeError("existing prune receipt conflicts with inventory")
        print(json.dumps({"already_pruned": True, "files": len(selected),
                          "bytes": intent["selected_bytes"]}, sort_keys=True))
        return
    if INTENT.exists() and json.loads(INTENT.read_text()) != intent:
        raise RuntimeError("existing prune intent conflicts with inventory")
    # Reopen the compressed archive and verify every recorded raw artifact,
    # rather than trusting just the original archive receipt.
    with tempfile.TemporaryDirectory(prefix="hdfs32-verify-", dir=ARCHIVE) as temporary:
        restored = Path(temporary)
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(restored)],
                       check=True)
        actual = sorted(str(path.relative_to(restored)) for path in restored.rglob("*")
                        if path.is_file())
        if actual != sorted(files):
            raise RuntimeError("restored archive path set differs from raw inventory")
        for name in actual:
            path = restored / name
            if (path.stat().st_size != files[name]["bytes"]
                    or sha(path) != files[name]["sha256"]):
                raise RuntimeError("restored archive SHA mismatch: " + name)
    for name in selected:
        source = HERE / name
        if source.exists() and (source.is_symlink()
                                or source.stat().st_size != files[name]["bytes"]
                                or sha(source) != files[name]["sha256"]):
            raise RuntimeError("expanded coverage file changed: " + name)
        if not source.exists() and not INTENT.exists():
            raise RuntimeError("expanded coverage file missing before prune: " + name)
    if not INTENT.exists():
        durable(INTENT, intent)
    for name in selected:
        (HERE / name).unlink(missing_ok=True)
    if any((HERE / name).exists() for name in selected):
        raise RuntimeError("coverage text remained after prune")
    durable(RECEIPT, intent)
    print(json.dumps({"verified_raw_files": len(files), "pruned_files": len(selected),
                      "pruned_bytes": intent["selected_bytes"],
                      "archive_sha256": intent["archive_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
