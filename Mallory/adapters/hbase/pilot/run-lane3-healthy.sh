#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane3
config=$base/runtime/configs/HBASE-07-healthy.json
out=$base/healthy-HBASE-07

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane3.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
python3 - "$config" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text())
assert hashlib.sha256(p.read_bytes()).hexdigest() == '7deea010edd34d6f38cb95b095fa8048a17a0f210aba7a7d5a2aa21b102b9937'
for item in d['runtime_artifacts'] + [d['source_equivalence_receipt']]:
    q=pathlib.Path(item['path'])
    assert hashlib.sha256(q.read_bytes()).hexdigest()==item['sha256'], str(q)
assert pathlib.Path(d['cwd']).is_dir()
PY

cd "$release"
timeout 650s python3 -m Mallory.core.campaign --config "$config" --out "$out"
python3 -m Mallory.core.audit --campaign "$out" --out "$out/offline-causal-audit.json"
