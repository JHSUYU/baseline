#!/usr/bin/env python3
"""Seal terminal HBASE-31 evidence on node1; copy only above node0 disk floor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess


ROOT = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CASE = ROOT / "data/mallory/cases/HBASE-31/campaigns/typed-dispatch-v2-full"
ARCHIVE = ROOT / "data/mallory/evidence_archives/campaign_typed_dispatch_v2/HBASE-31.tar.gz"
REMOTE_MANIFEST = ARCHIVE.with_suffix(".manifest.json")
RECEIPT = HERE / "full-v2-collection-receipt.json"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "ZhenyuLi@node1"]
FLOOR = 5 * 1024**3
SAFETY = 512 * 1024**2


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


REMOTE_SEAL = r'''
import hashlib,json,pathlib,sys,tarfile
case=pathlib.Path(sys.argv[1])
archive=pathlib.Path(sys.argv[2])
manifest=pathlib.Path(sys.argv[3])
config_sha=sys.argv[4]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
result=json.loads((case/'result.json').read_text())
audit=json.loads((case/'offline-causal-audit.json').read_text())
verdict=json.loads((case/'terminal-verdict.json').read_text())
if result['case_id']!='HBASE-31' or result['status'] not in ('queue_exhausted','budget_exhausted') or verdict['status']!=result['status']:
 raise RuntimeError('HBASE-31 not naturally terminal')
if sha(case/'config.json')!=config_sha or audit['campaign_result_sha256']!=sha(case/'result.json') or verdict['result_sha256']!=sha(case/'result.json'):
 raise RuntimeError('HBASE-31 result, audit or config mismatch')
files={str(p.relative_to(case)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(case.rglob('*')) if p.is_file() and p.name!='.campaign.lock'}
if archive.exists() or manifest.exists():
 if not archive.is_file() or not manifest.is_file(): raise RuntimeError('partial prior archive')
 old=json.loads(manifest.read_text())
 if old['files']!=files or old['archive_sha256']!=sha(archive): raise RuntimeError('prior archive differs')
else:
 archive.parent.mkdir(parents=True,exist_ok=True)
 temporary=archive.with_name('.'+archive.name+'.tmp')
 if temporary.exists(): raise RuntimeError('prior temporary archive exists')
 with tarfile.open(temporary,'w:gz') as packed:
  for rel in files: packed.add(case/rel,arcname=case.name+'/'+rel,recursive=False)
 with tarfile.open(temporary,'r:gz') as packed:
  members={m.name[len(case.name)+1:]:{'sha256':hashlib.sha256(packed.extractfile(m).read()).hexdigest(),'bytes':m.size} for m in packed if m.isfile() and m.name.startswith(case.name+'/')}
 if members!=files: raise RuntimeError('archive member hashes differ')
 temporary.rename(archive)
 row={'schema_version':1,'case_id':'HBASE-31','status':result['status'],'result_sha256':sha(case/'result.json'),'audit_sha256':sha(case/'offline-causal-audit.json'),'verdict_sha256':sha(case/'terminal-verdict.json'),'config_sha256':config_sha,'archive_sha256':sha(archive),'archive_bytes':archive.stat().st_size,'files':files}
 manifest.write_text(json.dumps(row,sort_keys=True,indent=2)+'\n')
row=json.loads(manifest.read_text())
if row['files']!=files or row['archive_sha256']!=sha(archive): raise RuntimeError('sealed evidence changed')
print(json.dumps({'manifest':row,'manifest_sha256':sha(manifest),'duration_seconds':result['duration_seconds'],'fault_trials_completed':result['fault_trials_completed'],'verdict':verdict},sort_keys=True))
'''


def main() -> None:
    stage = json.loads((HERE / "full-v2-stage-receipt.json").read_text())
    command = shlex.join(["python3", "-c", REMOTE_SEAL, str(CASE), str(ARCHIVE),
                           str(REMOTE_MANIFEST), stage["config_sha256"]])
    remote = subprocess.run(SSH + [command], text=True, capture_output=True, check=True)
    sealed = json.loads(remote.stdout)
    manifest = sealed["manifest"]
    assert manifest["status"] in {"queue_exhausted", "budget_exhausted"}
    assert manifest["config_sha256"] == stage["config_sha256"]
    copied = False
    free = shutil.disk_usage(ROOT).free
    if free >= FLOOR + SAFETY + manifest["archive_bytes"]:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        if not ARCHIVE.exists():
            temporary = ARCHIVE.with_name("." + ARCHIVE.name + ".tmp")
            if temporary.exists():
                raise RuntimeError("prior temporary local archive exists")
            subprocess.run(["scp", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
                            "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                            f"ZhenyuLi@node1:{ARCHIVE}", str(temporary)], check=True)
            if sha(temporary) != manifest["archive_sha256"]:
                raise RuntimeError("copied archive SHA differs")
            temporary.rename(ARCHIVE)
        if sha(ARCHIVE) != manifest["archive_sha256"]:
            raise RuntimeError("local archive SHA differs")
        copied = True
    receipt = {
        "schema_version": 1, "case_id": "HBASE-31",
        "kind": "typed_dispatch_v2_full_offhost_collection",
        "status": manifest["status"],
        "duration_seconds": sealed["duration_seconds"],
        "fault_trials_completed": sealed["fault_trials_completed"],
        "remote_host": "node1", "remote_campaign": str(CASE),
        "remote_archive": str(ARCHIVE),
        "remote_manifest": str(REMOTE_MANIFEST),
        "remote_manifest_sha256": sealed["manifest_sha256"],
        "archive_sha256": manifest["archive_sha256"],
        "archive_bytes": manifest["archive_bytes"],
        "archive_on_node0": copied,
        "node0_disk_free_bytes_at_collection": free,
        "node0_floor_bytes": FLOOR, "node0_safety_bytes": SAFETY,
        "result_sha256": manifest["result_sha256"],
        "audit_sha256": manifest["audit_sha256"],
        "terminal_verdict_sha256": manifest["verdict_sha256"],
        "config_sha256": manifest["config_sha256"],
        "source_gap_receipt_sha256": stage["predicate_source_gap_sha256"],
        "strict_injected_trials": sealed["verdict"]["strict_injected_trials"],
        "strict_target_trials": sealed["verdict"]["strict_target_trials"],
        "exact_exception_trials": sealed["verdict"]["exact_exception_trials"],
        "audit_report_gate_passed": sealed["verdict"]["audit_report_gate_passed"],
        "bug_claim": False
    }
    RECEIPT.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "duration_seconds": receipt["duration_seconds"],
                      "archive_on_node0": copied, "receipt_sha256": sha(RECEIPT)}))


if __name__ == "__main__":
    main()
