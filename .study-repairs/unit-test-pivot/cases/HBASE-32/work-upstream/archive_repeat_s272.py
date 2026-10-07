#!/usr/bin/env python3
"""Mirror one completed s272 repeat with per-file SHA-256 verification."""

from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
SSH = ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
       "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new",
       "-o", "UserKnownHostsFile=/tmp/hbase32_node1_knownhosts"]
REMOTE = "ZhenyuLi@node1"


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def main(index: int) -> None:
    if index not in range(2, 7):
        raise ValueError("Only bounded s272 repeats 2..6")
    label = f"replay-s272-{index}"
    summary_path = HERE / "logs" / f"{label}.summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["source_trial"] == "s272" and summary["replay_suffix"] == label
    assert summary["fuzz_budget_admitted"] is False
    files = sorted((HERE / "logs").glob(f"{label}.*"))
    files += [HERE / f"replay-s272-repeat-{index}-plan.json",
              HERE / "replay_repeat_s272.py", HERE / "run.sh", HERE / "agent.jar",
              HERE / "diag-s203/agent.jar", CASE / "work/agent.jar"]
    manifest = HERE / f"evidence-s272-repeat{index}-manifest.json"
    archive = HERE / f"evidence-s272-repeat{index}.tar.gz"
    receipt = HERE / f"evidence-s272-repeat{index}-remote-receipt.json"
    if receipt.exists():
        raise RuntimeError("Repeat already verified; refusing overwrite")
    entries = [{"path": str(path.relative_to(CASE)), "size": path.stat().st_size,
                "sha256": sha(path)} for path in files]
    data = {"source_trial": "s272", "repeat_index": index,
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "classification": ("meta_host" if summary["selected_server_carried_meta_at_fault"]
                               else "non_meta_host_conditional_negative_control"),
            "summary": summary, "files": entries}
    if manifest.exists() or archive.exists():
        if not (manifest.exists() and archive.exists()):
            raise RuntimeError("Partial local archive")
        if json.loads(manifest.read_text())["files"] != entries:
            raise RuntimeError("Previously archived file hashes changed")
    else:
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        with tarfile.open(archive, "w:gz") as output:
            for path in [*files, manifest]:
                output.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    remote = ("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/"
              f"HBASE-32/upstream-s272-repeat{index}")
    subprocess.run([*SSH, REMOTE, "mkdir", "-p", remote], check=True)
    subprocess.run(["scp", *SSH[1:], str(manifest), str(archive),
                    f"{REMOTE}:{remote}/"], check=True)
    verifier = '''import hashlib,json,tarfile
from pathlib import Path
root=Path(__import__('sys').argv[1]); mh=__import__('sys').argv[2]; ah=__import__('sys').argv[3]
mfile=next(root.glob('*-manifest.json')); afile=next(root.glob('*.tar.gz'))
assert hashlib.sha256(mfile.read_bytes()).hexdigest()==mh
assert hashlib.sha256(afile.read_bytes()).hexdigest()==ah
manifest=json.loads(mfile.read_text())
with tarfile.open(afile,'r:gz') as tar:
 for entry in manifest['files']:
  payload=tar.extractfile(entry['path']).read()
  assert len(payload)==entry['size']
  assert hashlib.sha256(payload).hexdigest()==entry['sha256'],entry['path']
print(len(manifest['files']))
'''
    verified = subprocess.run([*SSH, REMOTE, "python3", "-",
                               remote, sha(manifest), sha(archive)],
                              input=verifier, check=True, capture_output=True, text=True)
    count = int(verified.stdout.strip())
    if count != len(entries):
        raise RuntimeError("Remote file count mismatch")
    receipt.write_text(json.dumps({
        "source_trial": "s272", "repeat_index": index,
        "verified_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "remote_dir": remote, "manifest_sha256": sha(manifest),
        "archive_sha256": sha(archive), "files_verified_on_node1": count,
        "fuzz_budget_admitted": False}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"repeat": index, "manifest_sha256": sha(manifest),
                      "archive_sha256": sha(archive), "files_verified": count}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: archive_repeat_s272.py 2..6")
    main(int(sys.argv[1]))
