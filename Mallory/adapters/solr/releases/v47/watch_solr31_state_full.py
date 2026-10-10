#!/usr/bin/env python3
"""Durable, floor-gated compact terminal receipt for the node2 SOLR-31 full run."""

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


BASE = Path("/users/ZhenyuLi/baseline")
REMOTE = BASE / "data/mallory/campaign_v47_state_watch_lane4/SOLR-31"
LOCAL = BASE / "data/mallory/replays/SOLR-31-v47-state-watch"
KEY = "/users/ZhenyuLi/.ssh/id_ed25519_nodes"
FLOOR = 5 * 1024**3 + 128 * 1024**2
TERMINAL = {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "fault_trials_not_attested"}


def remote(code: str) -> str:
    result = subprocess.run(["ssh", "-i", KEY, "node2", "python3", "-"],
                            input=code, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    result_file = REMOTE / "result.json"
    while True:
        probe = remote("import json,pathlib; p=pathlib.Path(%r); "
                       "print(json.load(p.open()).get('status') if p.exists() else 'absent')"
                       % str(result_file))
        if probe in TERMINAL:
            break
        time.sleep(30)

    manifest_code = r'''
import hashlib, json, pathlib
root = pathlib.Path(%r)
keep = {'result.json','config.json','checkpoint.json','plan.json',
        'junit-receipt.json','sites.jsonl','pilot-result.json','junit.log',
        'stderr.log','stdout.log','events.jsonl.gz'}
rows=[]
for path in sorted(root.rglob('*')):
    if not path.is_file() or path.name not in keep or 'scratch' in path.parts:
        continue
    data=path.read_bytes()
    rows.append({'path':str(path.relative_to(root)), 'bytes':len(data),
                 'sha256':hashlib.sha256(data).hexdigest()})
doc={'schema_version':1,'case_id':'SOLR-31',
     'terminal_status':json.loads((root/'result.json').read_text())['status'],
     'files':rows}
out=root/'terminal-manifest.json'
out.write_text(json.dumps(doc,sort_keys=True,indent=2)+'\n')
print(json.dumps({'terminal_status':doc['terminal_status'],
                  'files':len(rows),'manifest_sha256':hashlib.sha256(out.read_bytes()).hexdigest()}))
''' % str(REMOTE)
    summary = json.loads(remote(manifest_code))
    LOCAL.mkdir(parents=True, exist_ok=True)
    projected = sum(row["bytes"] for row in json.loads(remote(
        "import json,pathlib; p=pathlib.Path(%r); print(p.read_text())"
        % str(REMOTE / "terminal-manifest.json")))["files"]
                    if row["path"] in ("result.json", "config.json", "checkpoint.json"))
    projected += 2 * 1024**2
    if shutil.disk_usage(BASE).free - projected < FLOOR:
        (LOCAL / "transfer-held.json").write_text(json.dumps({
            "schema_version": 1, "reason": "node0_disk_floor",
            "remote_manifest_sha256": summary["manifest_sha256"],
            "terminal_status": summary["terminal_status"]}, indent=2) + "\n")
        return
    names = ["result.json", "config.json", "checkpoint.json", "terminal-manifest.json"]
    for name in names:
        subprocess.run(["rsync", "-a", "-e", "ssh -i " + KEY,
                        "node2:" + str(REMOTE / name), str(LOCAL / name)], check=True)
    assert sha(LOCAL / "terminal-manifest.json") == summary["manifest_sha256"]
    by_name = {row["path"]: row for row in json.loads(
        (LOCAL / "terminal-manifest.json").read_text())["files"]}
    for name in names[:3]:
        assert sha(LOCAL / name) == by_name[name]["sha256"]
    (LOCAL / "terminal-sync-receipt.json").write_text(json.dumps({
        "schema_version": 1, "case_id": "SOLR-31", "remote_root": str(REMOTE),
        "terminal_status": summary["terminal_status"], "file_count": summary["files"],
        "manifest_sha256": summary["manifest_sha256"],
        "result_sha256": by_name["result.json"]["sha256"],
        "raw_location": "node2; all trial files retained remotely"}, indent=2,
        sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
