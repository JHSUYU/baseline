#!/usr/bin/env python3
"""Hash-verify SOLR-06 lane3 evidence, then run the pinned final-core audit."""

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
REMOTE = BASE / "data/mallory/campaign_v15a_lane3/SOLR-06"
FINAL = BASE / "data/mallory/replays/SOLR-06-v15a-lane3"
RELEASE = BASE / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
SESSION = "mallory-solr06-v15a-lane3-full"
HOST = "ZhenyuLi@node2"
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", HOST]
TERMINAL = {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
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
            files[str(path.relative_to(root))]=h.hexdigest()
    result=json.loads((root/"result.json").read_text())
    print(json.dumps({{"ready":True,"case_id":result.get("case_id"),
                      "status":result.get("status"),"files":files}},sort_keys=True))
'''
    result = subprocess.run(SSH + ["python3", "-"], input=script, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def collect(manifest: dict) -> None:
    if manifest["case_id"] != "SOLR-06" or manifest["status"] not in TERMINAL:
        raise ValueError("remote campaign is not terminal SOLR-06")
    expected = manifest["files"]
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    if FINAL.exists():
        if digest(FINAL / "result.json") != expected["result.json"]:
            raise FileExistsError("existing replay differs; preserving both")
        print("existing replay matches remote result", flush=True)
        return
    temporary = Path(tempfile.mkdtemp(prefix=".SOLR-06-v15a-sync-", dir=FINAL.parent))
    try:
        transport = f"ssh -i {KEY} -o IdentitiesOnly=yes"
        subprocess.run(["rsync", "-az", "--checksum", "-e", transport,
                        HOST + ":" + str(REMOTE) + "/", str(temporary) + "/"], check=True)
        actual = {str(path.relative_to(temporary)): digest(path)
                  for path in temporary.rglob("*") if path.is_file()}
        if actual != expected:
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
            raise ValueError(f"evidence differs missing={missing[:4]} extra={extra[:4]} "
                             f"changed={changed[:4]}")
        os.replace(temporary, FINAL)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    receipt = {"schema_version": 1, "case_id": "SOLR-06", "remote_host": HOST,
               "remote_root": str(REMOTE), "campaign_variant": "v15a_lane3_fixed_5820",
               "result_sha256": expected["result.json"],
               "files_verified": len(expected), "status": manifest["status"]}
    (FINAL / "sync-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    environment = dict(os.environ, PYTHONPATH=f"{RELEASE}:{BASE}")
    result = subprocess.run([sys.executable, "-m", "Mallory.core.audit",
                             "--campaign", str(FINAL), "--out",
                             str(FINAL / "offline-causal-audit.json")],
                            cwd=BASE, env=environment)
    if result.returncode not in (0, 2):
        raise RuntimeError("final-core audit did not produce a verdict")
    audit = json.loads((FINAL / "offline-causal-audit.json").read_text())
    print(json.dumps({**receipt, "audit_gate": audit.get("report_gate_passed"),
                      "audit_sha256": digest(FINAL / "offline-causal-audit.json")},
                     sort_keys=True), flush=True)


def main() -> int:
    while True:
        try:
            if not active():
                manifest = remote_manifest()
                if manifest.get("ready") and manifest.get("status") in TERMINAL:
                    collect(manifest)
                    return 0
                raise RuntimeError("tmux exited without a terminal result.json")
            print("waiting for SOLR-06 lane3 terminal campaign", flush=True)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("remote check retry: " + str(error), file=sys.stderr, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
