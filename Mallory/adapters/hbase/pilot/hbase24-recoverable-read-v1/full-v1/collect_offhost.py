#!/usr/bin/env python3
"""Seal HBASE-24 terminal SHA evidence on node1 and collect it on node0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys

BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CAMPAIGN = BASE / "data/mallory/cases/HBASE-24/campaigns/recoverable-read-v1-full"
OFFHOST = BASE / "data/mallory/evidence_archives/offhost_full"
STEM = "HBASE-24-recoverable-read-v1-full"
MANIFEST = OFFHOST / f"{STEM}.manifest.json"
RECEIPT = OFFHOST / f"{STEM}.receipt.json"
RAW_COPY = OFFHOST / STEM
SUMMARY_COPY = OFFHOST / f"{STEM}-terminal"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=4", "ZhenyuLi@node1"]
SCP = ["scp", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
RSYNC_SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
FLOOR = 5 * 1024**3
SAFETY = 512 * 1024**2
SUMMARY_FILES = ("result.json", "checkpoint.json", "config.json",
                 "offline-causal-audit.json", "terminal-verdict.json",
                 "campaign-exit.txt", "audit-exit.txt")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    if temporary.exists():
        raise RuntimeError(f"prior temporary file exists: {temporary}")
    with temporary.open("w") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.rename(path)


def check_stage() -> dict:
    collector = read(HERE / "collector-stage-receipt.json")
    if collector["collector_sha256"] != sha(Path(__file__)):
        raise RuntimeError("collector SHA differs from frozen stage")
    if collector["full_stage_receipt_sha256"] != sha(HERE / "stage-receipt.json"):
        raise RuntimeError("full stage receipt SHA changed")
    stage = read(HERE / "stage-receipt.json")
    if collector["config_sha256"] != stage["config_sha256"] or (
        collector["config_sha256"] != sha(HERE / "config.json")
    ):
        raise RuntimeError("full config SHA changed")
    return collector


def terminal() -> tuple[dict, dict, dict, dict]:
    stage = read(HERE / "stage-receipt.json")
    result = read(CAMPAIGN / "result.json")
    checkpoint = read(CAMPAIGN / "checkpoint.json")
    audit = read(CAMPAIGN / "offline-causal-audit.json")
    verdict = read(CAMPAIGN / "terminal-verdict.json")
    status = result["status"]
    count = result["fault_trials_completed"]
    if not (result["case_id"] == checkpoint["case_id"] == audit["case_id"] ==
            verdict["case_id"] == "HBASE-24" and
            status == checkpoint["status"] == audit["terminal_status"] == verdict["status"] and
            status in ("budget_exhausted", "queue_exhausted") and
            result["calibration_only"] is False and 0 < count <= 80 and
            len(checkpoint["completed_trials"]) == count + 1 and
            audit["trial_count"] == count + 1 and
            read(CAMPAIGN / "config.json") == read(HERE / "config.json") and
            sha(HERE / "config.json") == stage["config_sha256"] and
            audit["campaign_result_sha256"] == sha(CAMPAIGN / "result.json") and
            verdict["campaign_result_sha256"] == sha(CAMPAIGN / "result.json") and
            verdict["offline_audit_sha256"] == sha(CAMPAIGN / "offline-causal-audit.json")):
        raise RuntimeError("HBASE-24 natural terminal or SHA chain invalid")
    return result, checkpoint, audit, verdict


def list_files() -> dict[str, dict]:
    files = {}
    for path in sorted(CAMPAIGN.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"symlink in terminal evidence: {path}")
        if path.is_file():
            files[path.relative_to(CAMPAIGN).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": sha(path)}
    return files


def seal_node1() -> None:
    if socket.gethostname().split(".")[0] != "node1":
        raise RuntimeError("terminal sealing requires node1")
    check_stage()
    result, _, audit, _ = terminal()
    files = list_files()
    if not all(name in files for name in SUMMARY_FILES):
        raise RuntimeError("required terminal files missing")
    manifest = {
        "schema_version": 1, "case_id": "HBASE-24", "kind": "full_terminal_file_sha_manifest",
        "status": result["status"], "fault_trials_completed": result["fault_trials_completed"],
        "duration_seconds": result["duration_seconds"],
        "audit_report_gate_passed": audit["report_gate_passed"],
        "file_count": len(files), "logical_bytes": sum(f["bytes"] for f in files.values()),
        "files": files, "campaign_path": str(CAMPAIGN),
        "collector_sha256": sha(Path(__file__)),
        "full_stage_receipt_sha256": sha(HERE / "stage-receipt.json"),
    }
    if MANIFEST.exists():
        if read(MANIFEST) != manifest:
            raise RuntimeError("existing node1 terminal manifest differs")
    else:
        write_atomic(MANIFEST, manifest)
    print(json.dumps({"manifest_sha256": sha(MANIFEST), "manifest": manifest}, sort_keys=True))


def remote(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(SSH + [shlex.join(command)], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def copy_small(name: str, destination: Path, expected: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(destination) != expected["sha256"] or destination.stat().st_size != expected["bytes"]:
            raise RuntimeError(f"existing offhost file differs: {destination}")
        return
    temporary = destination.with_name("." + destination.name + ".tmp")
    if temporary.exists():
        raise RuntimeError(f"prior temporary copy exists: {temporary}")
    subprocess.run(SCP + [f"ZhenyuLi@node1:{CAMPAIGN / name}", str(temporary)], check=True)
    if sha(temporary) != expected["sha256"] or temporary.stat().st_size != expected["bytes"]:
        raise RuntimeError(f"offhost file SHA differs: {name}")
    temporary.rename(destination)


def check_copy(destination: Path, files: dict[str, dict]) -> None:
    actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*")
              if path.is_file()}
    if actual != set(files):
        raise RuntimeError("offhost raw file set differs from node1 manifest")
    for name, expected in files.items():
        path = destination / name
        if path.is_symlink() or path.stat().st_size != expected["bytes"] or (
            sha(path) != expected["sha256"]
        ):
            raise RuntimeError(f"offhost raw SHA differs: {name}")


def collect_node0() -> None:
    if socket.gethostname().split(".")[0] != "node0":
        raise RuntimeError("offhost collection requires node0")
    check_stage()
    sealed = json.loads(remote([sys.executable, str(Path(__file__)), "--seal-node1"]).stdout)
    expected_sha = sealed["manifest_sha256"]
    manifest = sealed["manifest"]
    OFFHOST.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists():
        if sha(MANIFEST) != expected_sha:
            raise RuntimeError("existing offhost manifest differs")
    else:
        temporary = MANIFEST.with_name("." + MANIFEST.name + ".tmp")
        if temporary.exists():
            raise RuntimeError("prior temporary manifest exists")
        subprocess.run(SCP + [f"ZhenyuLi@node1:{MANIFEST}", str(temporary)], check=True)
        if sha(temporary) != expected_sha:
            raise RuntimeError("offhost manifest SHA differs")
        temporary.rename(MANIFEST)
    if read(MANIFEST) != manifest:
        raise RuntimeError("offhost manifest content differs")

    for name in SUMMARY_FILES:
        copy_small(name, SUMMARY_COPY / name, manifest["files"][name])
    free = shutil.disk_usage(BASE).free
    full_copy = RAW_COPY.is_dir()
    if full_copy:
        check_copy(RAW_COPY, manifest["files"])
    elif free >= FLOOR + SAFETY + manifest["logical_bytes"]:
        temporary = RAW_COPY.with_name("." + RAW_COPY.name + ".tmp")
        if temporary.exists():
            raise RuntimeError("prior temporary raw copy exists")
        temporary.mkdir(parents=True)
        subprocess.run(["rsync", "-az", "--checksum", "-e", RSYNC_SSH,
                        f"ZhenyuLi@node1:{CAMPAIGN}/", str(temporary) + "/"], check=True)
        check_copy(temporary, manifest["files"])
        temporary.rename(RAW_COPY)
        full_copy = True
    receipt = {
        "schema_version": 1, "case_id": "HBASE-24", "kind": "offhost_full_terminal_collection",
        "status": manifest["status"], "fault_trials_completed": manifest["fault_trials_completed"],
        "duration_seconds": manifest["duration_seconds"],
        "audit_report_gate_passed": manifest["audit_report_gate_passed"],
        "manifest_sha256": expected_sha, "file_count": manifest["file_count"],
        "logical_bytes": manifest["logical_bytes"], "result_sha256": manifest["files"]["result.json"]["sha256"],
        "audit_sha256": manifest["files"]["offline-causal-audit.json"]["sha256"],
        "verdict_sha256": manifest["files"]["terminal-verdict.json"]["sha256"],
        "config_sha256": manifest["files"]["config.json"]["sha256"],
        "full_raw_copy_on_node0": full_copy, "terminal_summary_on_node0": True,
        "node0_free_bytes_before_raw_copy": free, "node0_floor_bytes": FLOOR,
        "node0_safety_bytes": SAFETY, "remote_raw_path": str(CAMPAIGN),
        "collector_sha256": sha(Path(__file__)),
    }
    if RECEIPT.exists():
        if read(RECEIPT) != receipt:
            raise RuntimeError("existing offhost receipt differs")
    else:
        write_atomic(RECEIPT, receipt)
    print(json.dumps({"status": receipt["status"], "fault_trials_completed":
                      receipt["fault_trials_completed"], "full_raw_copy_on_node0": full_copy,
                      "receipt_sha256": sha(RECEIPT)}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seal-node1", action="store_true")
    mode.add_argument("--collect-node0", action="store_true")
    args = parser.parse_args()
    if args.seal_node1:
        seal_node1()
    else:
        collect_node0()
