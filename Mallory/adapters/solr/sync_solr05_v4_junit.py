#!/usr/bin/env python3
"""Durably collect and audit the fixed-core SOLR-05 v4 JUnit-gated rerun separately."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/mallory"
FINAL = DATA / "replays/SOLR-05-v4-junit"
REMOTE = "/users/ZhenyuLi/.mallory-worktrees/solr-campaign-v4-junit/SOLR-05"
HOST = "ZhenyuLi@node2"
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", HOST]
TERMINAL = {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "healthy_node_identity_missing", "healthy_seed_ambiguous",
            "healthy_no_injectable_door", "healthy_attestation_failed",
            "fault_trials_not_attested"}

REMOTE_MANIFEST = r'''
import hashlib, json
from pathlib import Path
root = Path("/users/ZhenyuLi/.mallory-worktrees/solr-campaign-v4-junit/SOLR-05")
files = {}
for path in sorted(root.rglob("*")):
    if path.is_symlink():
        raise ValueError("symlink in case evidence: " + str(path))
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        files[str(path.relative_to(root))] = digest.hexdigest()
result = json.loads((root / "result.json").read_text())
print(json.dumps({"status": result.get("status"), "case_id": result.get("case_id"),
                  "files": files}, sort_keys=True))
'''


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def remote_manifest() -> dict:
    completed = subprocess.run(SSH + ["python3", "-"], input=REMOTE_MANIFEST,
                               text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


def campaign_active() -> bool:
    completed = subprocess.run(SSH + ["tmux", "has-session", "-t", "mallory-solr05-v4-junit"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if completed.returncode == 255:
        raise RuntimeError("could not check remote tmux: "
                           + completed.stderr.decode(errors="replace"))
    return completed.returncode == 0


def collect(manifest: dict) -> None:
    expected = manifest["files"]
    if manifest["case_id"] != "SOLR-05" or manifest["status"] not in TERMINAL:
        raise ValueError("remote campaign is not terminal SOLR-05")
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if FINAL.exists():
        if digest(FINAL / "result.json") == expected["result.json"]:
            print("SOLR-05 v4 already synced with matching result SHA", flush=True)
            return
        raise FileExistsError("existing SOLR-05 result differs; preserving both")
    temporary = Path(tempfile.mkdtemp(prefix=".SOLR-05-v4-sync-", dir=FINAL.parent))
    try:
        transport = f"ssh -i {KEY} -o IdentitiesOnly=yes"
        subprocess.run(["rsync", "-az", "--checksum", "-e", transport,
                        HOST + ":" + REMOTE + "/", str(temporary) + "/"], check=True)
        actual = {str(path.relative_to(temporary)): digest(path)
                  for path in temporary.rglob("*") if path.is_file()}
        if actual != expected:
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            altered = sorted(name for name in expected.keys() & actual.keys()
                             if expected[name] != actual[name])
            raise ValueError(f"evidence hash mismatch: missing={missing[:4]} "
                             f"extra={extra[:4]} altered={altered[:4]}")
        os.replace(temporary, FINAL)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    receipt = {"schema_version": 1, "case_id": "SOLR-05",
               "remote_host": HOST, "remote_root": REMOTE, "campaign_variant": "v4_fixed_core_junit_gate",
               "result_sha256": expected["result.json"],
               "files_verified": len(expected), "status": manifest["status"]}
    (FINAL / "sync-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    audited = subprocess.run([sys.executable, "-m", "Mallory.core.audit",
                              "--campaign", str(FINAL), "--out",
                              str(FINAL / "offline-causal-audit.json")], cwd=REPO)
    if audited.returncode not in (0, 2):
        raise RuntimeError("offline causal audit did not produce a valid verdict")
    print(json.dumps(receipt, sort_keys=True), flush=True)


def main() -> int:
    while True:
        try:
            if not campaign_active():
                manifest = remote_manifest()
                if manifest["status"] in TERMINAL:
                    collect(manifest)
                    return 0
            print("waiting for SOLR-05 v4 JUnit-gated terminal campaign", flush=True)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("remote check or transfer retry: " + str(error), file=sys.stderr, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
