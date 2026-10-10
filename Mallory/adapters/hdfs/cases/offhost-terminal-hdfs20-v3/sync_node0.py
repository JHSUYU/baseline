#!/usr/bin/env python3
"""Import only a SHA-verified terminal HDFS summary; raw remains on node2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/offhost-terminal-hdfs20-v3"
MANIFEST = HERE / "cases.json"
KEY = Path("/users/ZhenyuLi/.ssh/id_ed25519_nodes")
FLOOR = 5 * 1024**3
HEADROOM = 128 * 1024**2
FILES = ("config.json", "result.json", "offline-causal-audit.json")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ssh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
         "ZhenyuLi@node2", *args], capture_output=True, text=True, timeout=120)


def remote_size(path: Path) -> int:
    result = ssh("stat", "-c", "%s", str(path))
    if result.returncode:
        raise RuntimeError(f"node2 file size unavailable: {path}: {result.stderr[:200]}")
    return int(result.stdout.strip())


def fetch(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    transport = f"ssh -i {KEY} -o IdentitiesOnly=yes -o BatchMode=yes"
    subprocess.run(["rsync", "-a", "-e", transport,
                    f"ZhenyuLi@node2:{source}", str(destination)],
                   check=True, timeout=180)


def settings(case: str, manifest_sha: str) -> dict:
    if sha(MANIFEST) != manifest_sha:
        raise RuntimeError("offhost collector manifest SHA changed")
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("owner_host") != "node2" or
            case not in manifest.get("cases", {})):
        raise RuntimeError("case missing from pinned offhost collector manifest")
    row = manifest["cases"][case]
    path = Path(row["config_path"])
    if not path.is_file() or sha(path) != row["config_sha256"]:
        raise RuntimeError("local config differs from pinned full campaign")
    if json.loads(path.read_text()).get("case_id") != case:
        raise RuntimeError("case ID/config mismatch")
    return row


def receipt_or_none(case: str, row: dict) -> dict | None:
    remote_state = Path(row["node2_state_root"])
    result = ssh("cat", str(remote_state / "terminal-publication.json"))
    if result.returncode:
        if "No such file" in result.stderr:
            return None
        raise RuntimeError(f"node2 terminal receipt unavailable: {result.stderr[:300]}")
    receipt = json.loads(result.stdout)
    files = receipt.get("files", {})
    if (receipt.get("schema_version") != 1 or receipt.get("case_id") != case or
            receipt.get("config_sha256") != row["config_sha256"] or
            receipt.get("status") not in {"budget_exhausted", "queue_exhausted"} or
            not all(isinstance(files.get(name), str) for name in FILES) or
            files["config.json"] != row["config_sha256"] or
            files["result.json"] != receipt.get("canonical_result_sha256") or
            files["offline-causal-audit.json"] != receipt.get("audit_sha256")):
        raise RuntimeError("node2 receipt is not a complete pinned terminal case")
    return receipt


def verify_archive(case: str, row: dict, receipt: dict) -> None:
    remote_state = Path(row["node2_state_root"])
    archive = Path(receipt["archive_path"])
    archive_manifest = Path(receipt["archive_manifest_path"])
    expected = remote_state / "publication/evidence_archives/campaign"
    if (archive != expected / f"{case}.tar.gz" or
            archive_manifest != expected / f"{case}.tar.manifest.json"):
        raise RuntimeError("node2 archive path escapes pinned publication")
    result = ssh("sha256sum", str(archive), str(archive_manifest))
    if result.returncode:
        raise RuntimeError(f"node2 archive digest unavailable: {result.stderr[:300]}")
    hashes = [line.split(maxsplit=1)[0] for line in result.stdout.splitlines()]
    if hashes != [receipt.get("archive_sha256"), receipt.get("archive_manifest_sha256")]:
        raise RuntimeError("node2 archive or manifest changed")
    if remote_size(archive) != receipt.get("archive_bytes"):
        raise RuntimeError("node2 archive size changed")


def publish(case: str, row: dict, receipt: dict) -> dict:
    canonical = BASE / "data/mallory/cases" / case
    remote_state = Path(row["node2_state_root"])
    remote_case = BASE / "data/mallory/cases" / case
    state = Path(row["node0_state_root"])
    if canonical.exists():
        existing = canonical / "sync-receipt.json"
        if (existing.is_file() and
                json.loads(existing.read_text()).get("result_sha256") ==
                receipt["canonical_result_sha256"]):
            return json.loads(existing.read_text())
        raise FileExistsError(f"canonical {case} conflicts with terminal receipt")
    verify_archive(case, row, receipt)
    inputs = {name: remote_case / name for name in FILES}
    inputs.update({
        f"{case}.tar.manifest.json": Path(receipt["archive_manifest_path"]),
        "remote-publication-receipt.json": remote_state / "terminal-publication.json",
        "raw-copy-receipt.json": remote_state / "raw-copy-receipt.json",
    })
    needed = sum(remote_size(path) for path in inputs.values())
    if shutil.disk_usage(BASE).free < FLOOR + needed + HEADROOM:
        raise RuntimeError("node0 sparse import would breach 5 GiB + 128 MiB reserve")
    staging = state / "import" / case
    staging.mkdir(parents=True, exist_ok=True)
    for name, source in inputs.items():
        fetch(source, staging / name)
    if any(sha(staging / name) != receipt["files"][name] for name in FILES):
        raise RuntimeError("sparse result/config/audit SHA mismatch")
    if sha(staging / f"{case}.tar.manifest.json") != receipt["archive_manifest_sha256"]:
        raise RuntimeError("archive manifest SHA mismatch")
    imported = json.loads((staging / "remote-publication-receipt.json").read_text())
    raw = json.loads((staging / "raw-copy-receipt.json").read_text())
    packed = json.loads((staging / f"{case}.tar.manifest.json").read_text())
    if (imported != receipt or raw.get("case_id") != case or
            raw.get("config_sha256") != row["config_sha256"] or
            raw.get("files", {}).get("result.json") != receipt["raw_result_sha256"] or
            packed.get("case_id") != case or packed.get("phase") != "campaign" or
            packed.get("source_result_sha256") != receipt["raw_result_sha256"] or
            packed.get("archive_sha256") != receipt["archive_sha256"] or
            sorted(packed.get("members", [])) != sorted(raw.get("files", {}))):
        raise RuntimeError("archive manifest is not bound to complete raw evidence")
    result = json.loads((staging / "result.json").read_text())
    audit = json.loads((staging / "offline-causal-audit.json").read_text())
    if (result.get("case_id") != case or result.get("status") != receipt["status"] or
            result.get("evidence_archive", {}).get("sha256") != receipt["archive_sha256"] or
            audit.get("campaign_result_sha256") != receipt["canonical_result_sha256"]):
        raise RuntimeError("sparse result/audit not bound to remote archive")
    if shutil.disk_usage(BASE).free < FLOOR + HEADROOM:
        raise RuntimeError("node0 reserve fell below publication floor")
    sync = {
        "schema_version": 1, "case_id": case, "status": receipt["status"],
        "mode": "sha_verified_offhost_raw_sparse_summary", "owner_host": "node2",
        "remote_case": str(remote_case), "remote_archive": receipt["archive_path"],
        "result_sha256": receipt["canonical_result_sha256"],
        "audit_sha256": receipt["audit_sha256"],
        "config_sha256": row["config_sha256"],
        "remote_archive_sha256": receipt["archive_sha256"],
        "remote_archive_manifest_sha256": receipt["archive_manifest_sha256"],
        "remote_raw_file_count": len(raw["files"]),
        "remote_raw_result_sha256": receipt["raw_result_sha256"],
        "report_gate_passed": audit.get("report_gate_passed"),
    }
    (staging / "sync-receipt.json").write_text(json.dumps(sync, sort_keys=True, indent=2) + "\n")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, canonical)
    state.mkdir(parents=True, exist_ok=True)
    (state / "terminal-sync.json").write_text(json.dumps(sync, sort_keys=True, indent=2) + "\n")
    return sync


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--manifest-sha", required=True)
    args = parser.parse_args()
    row = settings(args.case, args.manifest_sha)
    Path(row["node0_state_root"]).mkdir(parents=True, exist_ok=True)
    while True:
        receipt = receipt_or_none(args.case, row)
        if receipt is not None:
            try:
                sync = publish(args.case, row, receipt)
            except RuntimeError as exc:
                if "reserve" not in str(exc):
                    raise
                print(str(exc), flush=True)
            else:
                print(json.dumps({"status": "sparse_published", "case_id": args.case,
                                  "result_sha256": sync["result_sha256"]}, sort_keys=True), flush=True)
                return
        time.sleep(30)


if __name__ == "__main__":
    main()
