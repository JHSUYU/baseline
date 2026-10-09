#!/usr/bin/env python3
"""SHA-sync the terminal Solr v13 configset-plugins healthy cohort from node2."""

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
REMOTE = "/users/ZhenyuLi/baseline/data/mallory/calibration_v13_config_lane1"
LOCAL = REPO / "data/mallory/calibration_v13_config_lane1"
CASES = ("SOLR-31", "SOLR-36", "SOLR-37")
KEY = Path.home() / ".ssh/id_ed25519_nodes"
SSH = ["ssh", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "ZhenyuLi@node2"]


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def ssh(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(SSH + [command], text=True, capture_output=True)


def collect() -> None:
    script = '''import hashlib,json,pathlib
root=pathlib.Path(''' + repr(REMOTE) + ''')
files={}
for path in sorted(root.rglob("*")):
 if path.is_symlink(): raise ValueError("symlink in v13 evidence: " + str(path))
 if path.is_file():
  h=hashlib.sha256()
  with path.open("rb") as f:
   for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
  files[str(path.relative_to(root))]=h.hexdigest()
print(json.dumps(files,sort_keys=True))
'''
    response = ssh("python3 - <<'PY'\n" + script + "\nPY")
    if response.returncode:
        raise RuntimeError("remote v13 manifest failed: " + response.stderr.strip())
    expected = json.loads(response.stdout)
    if "batch-result.json" not in expected:
        raise RuntimeError("remote v13 batch is not terminal")
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    if not LOCAL.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".solr-v13-config-sync-", dir=LOCAL.parent))
        try:
            subprocess.run(["rsync", "-az", "--checksum", "-e",
                            "ssh -i " + str(KEY) + " -o IdentitiesOnly=yes",
                            "ZhenyuLi@node2:" + REMOTE + "/", str(temporary) + "/"], check=True)
            actual = {str(path.relative_to(temporary)): sha256(path)
                      for path in temporary.rglob("*") if path.is_file()}
            if actual != expected:
                raise ValueError("v13 evidence hash manifest differs after transfer")
            os.replace(temporary, LOCAL)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    else:
        actual = {str(path.relative_to(LOCAL)): sha256(path)
                  for path in LOCAL.rglob("*") if path.is_file()
                  and path.name not in {"collection-receipt.json", "healthy-summary.json"}}
        if actual != expected:
            raise ValueError("existing v13 collection differs from remote evidence")
    receipt = {"schema_version": 1, "case_ids": list(CASES),
               "batch_result_sha256": expected["batch-result.json"],
               "remote_files_verified": len(expected), "remote_root": REMOTE}
    (LOCAL / "collection-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summarizer = REPO / "Mallory/adapters/solr/summarize_calibration.py"
    for case_id in CASES:
        campaign = LOCAL / case_id
        if ((campaign / "trials/r0000/result.json").is_file()
                and (campaign / "trials/r0000/pilot-result.json").is_file()):
            subprocess.run([sys.executable, str(summarizer), str(campaign),
                            "--out", str(campaign / "healthy-summary.json")], check=True)
    print("v13 configset-plugins evidence SHA-synced: " + str(LOCAL), flush=True)


def main() -> None:
    while True:
        result = ssh("test -f " + REMOTE + "/batch-result.json")
        if result.returncode == 255:
            raise RuntimeError("cannot reach node2: " + result.stderr.strip())
        if result.returncode == 0:
            collect()
            return
        session = ssh("tmux has-session -t mallory-solr-v13-config-lane1")
        if session.returncode == 255:
            raise RuntimeError("cannot inspect node2 tmux: " + session.stderr.strip())
        if session.returncode != 0:
            raise RuntimeError("v13 batch exited without terminal result")
        print("waiting for v13 configset-plugins cohort", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
