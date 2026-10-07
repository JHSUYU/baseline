#!/usr/bin/env python3
"""Mirror a settled role pilot's raw receipts with per-file SHA verification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile


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


def main(suffix: str) -> None:
    if suffix not in {*(f"healthy-{i:03d}" for i in range(1, 4)),
                      *(f"role-f{i:03d}" for i in range(1, 4))}:
        raise ValueError("Only bounded role pilot labels are accepted")
    checkpoint = json.loads((HERE / "role-pilot-checkpoint.json").read_text())
    if checkpoint["in_flight"] is not None:
        raise RuntimeError("Archive only at a complete pilot boundary")
    trials = [*checkpoint["healthy_attempts"], *checkpoint["fault_trials"]]
    settled = next((trial for trial in trials if trial["suffix"] == suffix), None)
    if settled is None:
        raise RuntimeError("Pilot attempt is not settled")
    raw = sorted((HERE / "logs").glob(suffix + ".*"))
    if not any(path.name == suffix + ".receipt.json" for path in raw):
        raise RuntimeError("Raw receipt missing")
    files = raw + [HERE / "role-plan.json", HERE / "role_pilot.py",
                   HERE / "audit_role_run.py", HERE / "run.sh",
                   HERE / "base-agent.jar", HERE / "upstream-agent.jar",
                   HERE.parent / "work-upstream/diag-s203/agent.jar"]
    manifest = HERE / f"{suffix}.archive-manifest.json"
    archive = HERE / f"{suffix}.raw.tar.gz"
    remote_receipt = HERE / f"{suffix}.remote-verified.json"
    if remote_receipt.exists():
        raise RuntimeError("Pilot already mirrored; refusing overwrite")
    entries = [{"path": str(path.relative_to(CASE)), "size": path.stat().st_size,
                "sha256": sha(path)} for path in files]
    data = {"label": suffix, "created_utc": datetime.now(timezone.utc).isoformat(),
            "classification": "distinct_role_aware_pilot_not_s272_exact_replay",
            "fuzz_budget_admitted": False, "settled": True,
            "plan_sha256": checkpoint["plan_sha256"], "files": entries}
    if manifest.exists() or archive.exists():
        if not (manifest.exists() and archive.exists()):
            raise RuntimeError("Partial prior archive")
        if json.loads(manifest.read_text())["files"] != entries:
            raise RuntimeError("Raw file hashes changed since prior archive")
    else:
        manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        with tarfile.open(archive, "w:gz") as output:
            for path in [*files, manifest]:
                output.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    remote = ("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/"
              f"HBASE-32/role-aware-v3-pilot/{suffix}")
    subprocess.run([*SSH, REMOTE, "mkdir", "-p", remote], check=True)
    subprocess.run(["scp", *SSH[1:], str(manifest), str(archive),
                    f"{REMOTE}:{remote}/"], check=True)
    verifier = '''import hashlib,json,tarfile,sys
from pathlib import Path
root=Path(sys.argv[1]); expected_manifest=sys.argv[2]; expected_archive=sys.argv[3]
manifest_file=next(root.glob('*.archive-manifest.json'))
archive_file=next(root.glob('*.raw.tar.gz'))
assert hashlib.sha256(manifest_file.read_bytes()).hexdigest()==expected_manifest
assert hashlib.sha256(archive_file.read_bytes()).hexdigest()==expected_archive
manifest=json.loads(manifest_file.read_text())
with tarfile.open(archive_file,'r:gz') as source:
 for item in manifest['files']:
  contents=source.extractfile(item['path']).read()
  assert len(contents)==item['size']
  assert hashlib.sha256(contents).hexdigest()==item['sha256'],item['path']
print(len(manifest['files']))
'''
    checked = subprocess.run([*SSH, REMOTE, "python3", "-", remote,
                              sha(manifest), sha(archive)], input=verifier,
                             check=True, capture_output=True, text=True)
    count = int(checked.stdout.strip())
    if count != len(entries):
        raise RuntimeError("Remote per-file verification count mismatch")
    receipt = {"label": suffix, "verified_utc": datetime.now(timezone.utc).isoformat(),
               "remote_dir": remote, "manifest_sha256": sha(manifest),
               "archive_sha256": sha(archive), "files_verified_on_node1": count,
               "fuzz_budget_admitted": False}
    remote_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: archive_role_pilot.py healthy-NNN|role-fNNN")
    main(sys.argv[1])
