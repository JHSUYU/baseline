#!/usr/bin/env python3
"""Copy and verify terminal Solr 22 pilot inputs; leave scratch on node2."""

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
REMOTE = BASE / "data/mallory/pilot_v27p_lane4/SOLR-22"
FINAL = BASE / "data/mallory/replays/SOLR-22-v27p-lane4"
RELEASE = BASE / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
SESSION = "mallory-solr22-v27p-lane4-pilot"
HOST = "ZhenyuLi@node2"
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", HOST]
TERMINAL = {"calibration_complete", "budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "healthy_node_identity_missing", "healthy_seed_ambiguous",
            "healthy_no_injectable_door", "healthy_attestation_failed",
            "fault_trials_not_attested"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


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
            files[str(path.relative_to(root))]={{"sha256":h.hexdigest(),
                                               "bytes":path.stat().st_size}}
    result=json.loads((root/"result.json").read_text())
    print(json.dumps({{"ready":True,"case_id":result.get("case_id"),
                      "status":result.get("status"),"files":files}},sort_keys=True))
'''
    result = subprocess.run(SSH + ["python3", "-"], input=script, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def split_files(manifest: dict) -> tuple[dict, dict]:
    retained, remote_only = {}, {}
    for name, record in manifest["files"].items():
        (remote_only if "scratch" in Path(name).parts else retained)[name] = record
    return retained, remote_only


def collect(manifest: dict) -> None:
    if manifest["case_id"] != "SOLR-22" or manifest["status"] not in TERMINAL:
        raise ValueError("remote calibration is not terminal SOLR-22")
    retained, remote_only = split_files(manifest)
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if FINAL.exists():
        actual = {str(path.relative_to(FINAL)): {"sha256": digest(path),
                  "bytes": path.stat().st_size} for path in FINAL.rglob("*")
                  if path.is_file() and path.name not in
                  ("sync-receipt.json", "offline-causal-audit.json")}
        if actual != retained:
            raise FileExistsError("existing sparse replay differs; preserve both")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".SOLR-22-v27p-sync-", dir=FINAL.parent))
        try:
            transport = f"ssh -i {KEY} -o IdentitiesOnly=yes"
            subprocess.run(["rsync", "-az", "--checksum", "--exclude=scratch/",
                            "-e", transport, HOST + ":" + str(REMOTE) + "/",
                            str(temporary) + "/"], check=True)
            actual = {str(path.relative_to(temporary)): {"sha256": digest(path),
                      "bytes": path.stat().st_size} for path in temporary.rglob("*")
                      if path.is_file()}
            if actual != retained:
                raise ValueError("sparse replay files differ from node2 SHA manifest")
            os.replace(temporary, FINAL)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    receipt = {"schema_version": 1, "case_id": "SOLR-22", "remote_host": HOST,
               "remote_root": str(REMOTE), "campaign_variant": "v27p_lane4_pilot_fixed_5820",
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
        raise RuntimeError("final-core audit did not produce a verdict")
    audit = json.loads((FINAL / "offline-causal-audit.json").read_text())
    print(json.dumps({"result_sha256": receipt["result_sha256"],
                      "sync_receipt_sha256": digest(receipt_path),
                      "audit_gate": audit.get("report_gate_passed"),
                      "audit_sha256": digest(FINAL / "offline-causal-audit.json"),
                      "retained_count": len(retained),
                      "remote_only_scratch_count": len(remote_only)},
                     sort_keys=True), flush=True)


def main() -> int:
    while True:
        try:
            if not active():
                manifest = remote_manifest()
                if manifest.get("ready") and manifest.get("status") in TERMINAL:
                    retained, _ = split_files(manifest)
                    needed = sum(row["bytes"] for row in retained.values()) + 512 * 1024 * 1024
                    FINAL.parent.mkdir(parents=True, exist_ok=True)
                    if not FINAL.exists() and shutil.disk_usage(FINAL.parent).free < needed:
                        print(f"waiting for sparse replay disk: need {needed} bytes", flush=True)
                        time.sleep(30)
                        continue
                    collect(manifest)
                    return 0
                raise RuntimeError("tmux exited without terminal result.json")
            print("waiting for SOLR-22 lane4 terminal pilot", flush=True)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("remote check retry: " + str(error), file=sys.stderr, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
