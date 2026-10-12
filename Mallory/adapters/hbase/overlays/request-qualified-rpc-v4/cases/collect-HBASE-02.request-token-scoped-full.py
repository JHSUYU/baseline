#!/usr/bin/env python3
"""Collect and audit the terminal HBASE-02 scoped request-token full campaign.

Run this on node0 in tmux. It never replaces the canonical result.
"""

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

BASE = Path("/users/ZhenyuLi/baseline")
RELEASE_ID = "dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
RELEASE = BASE / "Mallory/dispatch/releases" / RELEASE_ID
CASE = BASE / "data/mallory/HBASE-02/campaigns/request-token-scoped-v4-full"
ARCHIVE = BASE / "data/mallory/evidence_archives/campaign_request_token_scoped_v4/HBASE-02.tar.gz"
RECEIPT = CASE.parent / "request-token-scoped-v4-full-receipt.json"
NODE0_AUDIT = CASE.parent / "request-token-scoped-v4-full-node0-audit.json"
REMOTE = "ZhenyuLi@node1"
DISK_FLOOR_BYTES = 5 * 1024**3
DISK_SAFETY_BYTES = 512 * 1024**2
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def command(argv, *, check=True, env=None):
    result = subprocess.run(argv, text=True, capture_output=True, env=env)
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} failed {result.returncode}: {result.stderr[-1000:]}")
    return result


def remote(command_text, *, check=True):
    return command(SSH + [command_text], check=check)


def terminal():
    result = remote(f"cat '{CASE}/result.json'", check=False)
    if result.returncode:
        return False
    try:
        status = json.loads(result.stdout)["status"]
    except (KeyError, ValueError):
        return False
    if status == "running":
        return False
    return remote("tmux has-session -t mallory-hbase02-request-token-scoped-v4-full 2>/dev/null",
                  check=False).returncode != 0


def precision_rows():
    """Use the frozen core's independent event-time replay, not a row-level flag."""
    audit = json.loads(NODE0_AUDIT.read_text())
    rows = []
    for trial in audit["trials"]:
        trial_id = int(Path(trial["result_path"]).parent.name[1:])
        if trial_id == 0:
            continue
        followups = trial.get("qualified_request_followups", [])
        valid = bool(trial.get("applied_identity_valid") and
                     trial.get("target_retained") and followups)
        rows.append({"trial_id": trial_id, "strict_postfault_request_path": valid,
                     "applied_identity_valid": trial.get("applied_identity_valid"),
                     "target_retained": trial.get("target_retained"),
                     "witnesses": followups})
    return rows


def main():
    if not CASE.parent.is_dir():
        CASE.parent.mkdir(parents=True)
    while not terminal():
        time.sleep(30)
    if RECEIPT.exists():
        print(json.dumps({"receipt": str(RECEIPT), "sha256": sha(RECEIPT),
                          "already_collected": True}), flush=True)
        return
    manifest = RELEASE / "manifest.json"
    command(["python3", "-m", "Mallory.dispatch.core_release", "--verify", str(manifest)])
    remote_release = remote(
        f"cd '{BASE}' && python3 -m Mallory.dispatch.core_release --verify '{manifest}'")
    if RELEASE_ID not in remote_release.stdout:
        raise RuntimeError("remote release differs")

    remote_audit = remote(
        f"cd '{BASE}' && PYTHONPATH='{RELEASE}:{BASE}' python3 -m Mallory.core.audit "
        f"--campaign '{CASE}' --out '{CASE}/offline-causal-audit.json'", check=False)
    if remote_audit.returncode not in (0, 2):
        raise RuntimeError(f"remote audit failed: {remote_audit.stderr[-1000:]}")

    remote_archive = ARCHIVE
    remote(f"mkdir -p '{ARCHIVE.parent}' && "
           f"if test ! -f '{remote_archive}'; then "
           f"tar --exclude=.campaign.lock -C '{CASE.parent}' -czf '{remote_archive}.tmp' "
           f"'{CASE.name}' && mv '{remote_archive}.tmp' '{remote_archive}'; fi")
    remote_sha = remote(f"sha256sum '{remote_archive}'").stdout.split()[0]
    archive_bytes = int(remote(f"stat -c %s '{remote_archive}'").stdout.strip())
    expanded_bytes = int(remote(f"du -sb '{CASE}'").stdout.split()[0])
    while True:
        free = shutil.disk_usage(BASE).free
        needed = (DISK_FLOOR_BYTES + DISK_SAFETY_BYTES
                  + (0 if ARCHIVE.exists() else archive_bytes)
                  + (0 if CASE.exists() else expanded_bytes))
        if free >= needed:
            break
        print(json.dumps({"status": "held_for_node0_disk", "free_bytes": free,
                          "required_bytes": needed, "remote_archive_bytes": archive_bytes,
                          "remote_expanded_bytes": expanded_bytes}), flush=True)
        time.sleep(60)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        temporary = Path(str(ARCHIVE) + ".tmp")
        command(["scp", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
                 "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                 f"{REMOTE}:{remote_archive}", str(temporary)])
        if sha(temporary) != remote_sha:
            raise RuntimeError("archive differs after copy")
        os.replace(temporary, ARCHIVE)
    if sha(ARCHIVE) != remote_sha:
        raise RuntimeError("existing local archive differs from node1")

    with tarfile.open(ARCHIVE, "r:gz") as archive:
        members = archive.getmembers()
        if not members or any(
                (not (m.isdir() or m.isfile()) or
                 not (m.name == CASE.name or m.name.startswith(CASE.name + "/")) or
                 ".." in Path(m.name).parts)
                for m in members):
            raise RuntimeError("archive member is unsafe")
        if CASE.exists():
            for member in members:
                if not member.isfile():
                    continue
                local = CASE.parent / member.name
                if local.exists():
                    archived = archive.extractfile(member)
                    if archived is None:
                        raise RuntimeError(f"archive member cannot be read: {member.name}")
                    expected = hashlib.sha256(archived.read()).hexdigest()
                    if sha(local) != expected:
                        raise RuntimeError(f"existing local evidence differs: {local}")
        archive.extractall(CASE.parent)
    file_sha = {str(p.relative_to(CASE)): sha(p)
                for p in sorted(CASE.rglob("*")) if p.is_file()}
    source_result_sha = remote(f"sha256sum '{CASE}/result.json'").stdout.split()[0]
    if file_sha["result.json"] != source_result_sha:
        raise RuntimeError("terminal result differs after copy")

    env = dict(os.environ, PYTHONPATH=f"{RELEASE}:{BASE}")
    node0_audit_result = command(
        ["python3", "-m", "Mallory.core.audit", "--campaign", str(CASE),
         "--out", str(NODE0_AUDIT)], check=False, env=env)
    if node0_audit_result.returncode not in (0, 2):
        raise RuntimeError(f"node0 audit failed: {node0_audit_result.stderr[-1000:]}")
    result = json.loads((CASE / "result.json").read_text())
    audit = json.loads((CASE / "offline-causal-audit.json").read_text())
    node0_audit = json.loads(NODE0_AUDIT.read_text())
    rows = precision_rows()
    receipt = {
        "schema_version": 1, "case_id": "HBASE-02",
        "campaign": "request-token-scoped-v4-full", "terminal_status": result["status"],
        "core_release_id": RELEASE_ID, "core_manifest_sha256": sha(manifest),
        "archive_sha256": sha(ARCHIVE), "archive_path": str(ARCHIVE),
        "result_sha256": file_sha["result.json"],
        "remote_audit_sha256": file_sha["offline-causal-audit.json"],
        "node0_audit_sha256": sha(NODE0_AUDIT),
        "remote_report_gate_passed": audit.get("report_gate_passed"),
        "node0_report_gate_passed": node0_audit.get("report_gate_passed"),
        "applied_fault_identity_valid": node0_audit.get("applied_fault_identity_valid"),
        "fault_trials_completed": result.get("fault_trials_completed"),
        "precision_retained_trials": sum(row["strict_postfault_request_path"] for row in rows),
        "precision_trials": rows, "files_sha256": file_sha,
    }
    receipt["eligible_for_canonical_review"] = bool(
        audit.get("report_gate_passed") and node0_audit.get("report_gate_passed")
        and node0_audit.get("applied_fault_identity_valid")
        and receipt["precision_retained_trials"] > 0)
    temporary_receipt = Path(str(RECEIPT) + ".tmp")
    temporary_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_receipt, RECEIPT)
    print(json.dumps({"receipt": str(RECEIPT), "sha256": sha(RECEIPT),
                      "eligible_for_canonical_review":
                      receipt["eligible_for_canonical_review"]}), flush=True)


if __name__ == "__main__":
    main()
