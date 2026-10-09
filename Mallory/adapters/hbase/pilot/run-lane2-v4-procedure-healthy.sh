#!/usr/bin/env bash
set -euo pipefail

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
base=/users/ZhenyuLi/.mallory-worktrees/hbase/lane2-v4

mkdir -p /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/hbase-lane2.lock
flock -n 9

export PYTHONPATH="$release:/users/ZhenyuLi/baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"

for n in 17 18; do
  config=$base/runtime/configs/HBASE-$n-v4-healthy.json
  out=$base/healthy-HBASE-$n
  python3 - "$config" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); d=json.loads(p.read_text())
expected={
    'HBASE-17':'d389a385d4efd1270a9a40e1d9f96263a8846023d93e1481b8c14972a9ccc927',
    'HBASE-18':'29dc20b71522096591b3ce2fed88d00426ca41ead4b734a8310aa8bc4585e81b',
}[d['case_id']]
assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
for item in d['runtime_artifacts']:
    q=pathlib.Path(item['path'])
    assert hashlib.sha256(q.read_bytes()).hexdigest()==item['sha256'], str(q)
assert pathlib.Path(d['cwd']).is_dir()
PY

  cd "$release"
  set +e
  timeout 750s python3 -m Mallory.core.campaign --config "$config" --out "$out"
  campaign_exit=$?
  if [[ -f "$out/result.json" ]]; then
    python3 -m Mallory.core.audit --campaign "$out" \
      --out "$out/offline-causal-audit.json"
    audit_exit=$?
  else
    audit_exit=99
  fi
  set -e
  printf 'HBASE-%s campaign_exit=%s audit_exit=%s\n' "$n" "$campaign_exit" "$audit_exit"
done
