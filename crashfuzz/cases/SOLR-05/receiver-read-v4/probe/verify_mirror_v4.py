#!/usr/bin/env python3
"""Verify node2 mirror of every completed SOLR-05 V4 raw artifact by SHA-256."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
STATE = EVIDENCE / "campaign-v4/checkpoint.json"
REMOTE = "ZhenyuLi@node2"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(state: dict) -> dict[str, str]:
    names = ["original-001", "original-002", "healthy-001", "healthy-002",
             "healthy-003", "healthy-004", "pilot-001"]
    directories = [EVIDENCE / name for name in names]
    directories += [CASE / row["evidence"] for row in state["trials"]]
    result = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.name not in ("manifest.json.tmp",):
                result[str(path.relative_to(CASE))] = sha(path)
    return result


def main() -> None:
    state_bytes = STATE.read_bytes()
    state = json.loads(state_bytes)
    expected = files(state)
    subprocess.run(["rsync", "-a", "--delay-updates", "--exclude=scratch/",
        "--exclude=generated/", "--exclude=classes/",
        "--exclude=classes-original/", "-e", " ".join(SSH), str(CASE) + "/",
        REMOTE + ":" + str(CASE) + "/"], check=True)
    remote_script = '''
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]); request=json.load(sys.stdin)
actual={}
for name in request:
    path=root/name
    actual[name]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
print(json.dumps(actual,sort_keys=True))
'''
    encoded = base64.b64encode(remote_script.encode()).decode()
    remote_command = ("python3 -c 'import base64;exec(base64.b64decode(\"" +
                      encoded + "\"))' " + shlex.quote(str(CASE)))
    result = subprocess.run([*SSH, REMOTE, remote_command], input=json.dumps(expected),
                            capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    mismatches = [name for name, digest in expected.items()
                  if actual.get(name) != digest]
    receipt = {"case": "SOLR-05", "stage": "receiver-state-read-v4",
               "checkpoint_sha256": hashlib.sha256(state_bytes).hexdigest(),
               "completed_trials": len(state["trials"]),
               "completed_artifact_files": len(expected),
               "remote": "node2", "mismatches": mismatches,
               "complete_match": not mismatches}
    destination = EVIDENCE / "campaign-v4/mirror-verification.json"
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt))
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
