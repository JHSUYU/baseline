#!/usr/bin/env python3
"""SHA-verify a terminal SOLR-22 v33g dynamic healthy; keep scratch on node2."""

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

BASE = Path("/users/ZhenyuLi/baseline")
REMOTE = BASE / "data/mallory/pilot_v33g2p_lane4/SOLR-22"
FINAL = BASE / "data/mallory/replays/SOLR-22-v33g2p-lane4"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SESSION = "mallory-solr22-v33g2p-lane4-pilot"
HOST = "ZhenyuLi@node2"
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", HOST]
TERMINAL = {"calibration_complete", "budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "healthy_node_identity_missing", "healthy_seed_ambiguous", "healthy_no_injectable_door",
            "healthy_attestation_failed", "fault_trials_not_attested"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def active() -> bool:
    result = subprocess.run(SSH + ["tmux", "has-session", "-t", SESSION],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode == 255:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.returncode == 0


def remote_manifest() -> dict:
    script = f'''from pathlib import Path
import hashlib,json
root=Path({str(REMOTE)!r})
if not (root/"result.json").is_file():
    print(json.dumps({{"ready":False}}))
else:
    files={{}}
    for path in sorted(root.rglob("*")):
        if path.is_symlink(): raise ValueError("symlink in evidence: "+str(path))
        if path.is_file():
            h=hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024*1024),b""):
                    h.update(chunk)
            files[str(path.relative_to(root))]={{"sha256":h.hexdigest(),"bytes":path.stat().st_size}}
    result=json.loads((root/"result.json").read_text())
    print(json.dumps({{"ready":True,"case_id":result.get("case_id"),
                      "status":result.get("status"),"files":files}},sort_keys=True))
'''
    result = subprocess.run(SSH + ["python3", "-"], input=script, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def collect(manifest: dict) -> None:
    if manifest["case_id"] != "SOLR-22" or manifest["status"] not in TERMINAL:
        raise ValueError("node2 pilot not terminal SOLR-22")
    retained = {name: row for name, row in manifest["files"].items()
                if "scratch" not in Path(name).parts}
    remote_only = {name: row for name, row in manifest["files"].items()
                   if "scratch" in Path(name).parts}
    needed = sum(row["bytes"] for row in retained.values()) + 128 * 1024 * 1024
    if shutil.disk_usage(BASE).free < needed + 5 * 1024 ** 3:
        raise RuntimeError("node0 5 GiB reserve would be violated")
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if FINAL.exists():
        actual = {str(path.relative_to(FINAL)): {"sha256": digest(path), "bytes": path.stat().st_size}
                  for path in FINAL.rglob("*") if path.is_file() and path.name not in
                  ("sync-receipt.json", "offline-causal-audit.json")}
        if actual != retained:
            raise FileExistsError("existing replay differs; preserve both")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".SOLR-22-v33p-sync-", dir=FINAL.parent))
        try:
            transport = f"ssh -i {KEY} -o IdentitiesOnly=yes"
            subprocess.run(["rsync", "-az", "--checksum", "--exclude=scratch/",
                            "-e", transport, HOST + ":" + str(REMOTE) + "/",
                            str(temporary) + "/"], check=True)
            actual = {str(path.relative_to(temporary)): {"sha256": digest(path),
                      "bytes": path.stat().st_size} for path in temporary.rglob("*") if path.is_file()}
            if actual != retained:
                raise ValueError("node0 sparse replay differs from node2 SHA manifest")
            os.replace(temporary, FINAL)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    receipt = {"schema_version": 1, "case_id": "SOLR-22", "remote_host": HOST,
               "remote_root": str(REMOTE), "campaign_variant": "v33g2p_lane4_fa5f_dynamic_actor_pilot",
               "result_sha256": retained["result.json"]["sha256"],
               "retained_files": retained, "remote_only_scratch_files": remote_only,
               "raw_remote_preserved": True, "status": manifest["status"]}
    receipt_path = FINAL / "sync-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    environment = dict(os.environ, PYTHONPATH=f"{RELEASE}:{BASE}")
    result = subprocess.run([sys.executable, "-m", "Mallory.core.audit", "--campaign",
                             str(FINAL), "--out", str(FINAL / "offline-causal-audit.json")],
                            cwd=BASE, env=environment)
    if result.returncode not in (0, 2):
        raise RuntimeError("final-core audit failed to produce a verdict")
    audit = json.loads((FINAL / "offline-causal-audit.json").read_text())
    print(json.dumps({"result_sha256": receipt["result_sha256"],
                      "sync_receipt_sha256": digest(receipt_path),
                      "audit_gate": audit.get("report_gate_passed"),
                      "audit_sha256": digest(FINAL / "offline-causal-audit.json"),
                      "retained_count": len(retained),
                      "remote_only_scratch_count": len(remote_only)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    while True:
        try:
            if active():
                print("waiting for SOLR-22 pilot terminal", flush=True)
            else:
                manifest = remote_manifest()
                if not manifest.get("ready") or manifest.get("status") == "running":
                    print("waiting for terminal result write", flush=True)
                    time.sleep(2)
                    continue
                if manifest.get("status") not in TERMINAL:
                    raise RuntimeError("healthy tmux exited without terminal result.json")
                retained = {name: row for name, row in manifest["files"].items()
                            if "scratch" not in Path(name).parts}
                need = sum(row["bytes"] for row in retained.values()) + 128 * 1024 * 1024
                free = shutil.disk_usage(BASE).free
                if free >= need + 5 * 1024 ** 3:
                    collect(manifest)
                    break
                print(f"waiting for node0 5 GiB reserve: free={free} needed={need}", flush=True)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print(f"transient remote check failure: {error}", file=sys.stderr, flush=True)
        time.sleep(30)
