#!/usr/bin/env bash
set -euo pipefail

case_id=${1:?HBASE-23 or HBASE-37 required}
mode=${2:?healthy or full required}
run_tag=${3:-01}
[[ "$run_tag" =~ ^[0-9][0-9]$ ]] || { echo 'Two-digit run tag required' >&2; exit 2; }
base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
stage="$base/Mallory/adapters/hbase/pilot/HBASE-23-37-terminal-v1"

case "$case_id:$mode" in
  23:healthy) digest=b1e74d95e924bb40e3b442c8d14daeefd904659e30c799da6ed52276b4e05bdf ;;
  23:full) digest=8c4914b7d68f8d1038bee766c43b51f5ad46f333ab910389d11fec48b7d12bc5 ;;
  37:healthy) digest=4eb678789d4fca5fe649d829208c9814e35327d6b14a8cf228b02c6bd4cf62c3 ;;
  37:full) digest=b9a01789520a0b48bd0b53653f7050e079952a725a44631321f179c4c432b373 ;;
  *) echo 'Invalid case/mode' >&2; exit 2 ;;
esac
config="$stage/HBASE-$case_id-$mode.json"
if [ "$mode" = healthy ]; then
  output="$base/data/mallory/HBASE-$case_id/campaigns/terminal-v1-healthy-r$run_tag"
else
  output="$base/data/mallory/HBASE-$case_id/campaigns/terminal-v1-full"
fi
if [ "$case_id" = 23 ]; then
  lock=/tmp/mallory-lanes/hbase-lane9-next.lock
else
  lock=/tmp/mallory-lanes/hbase-lane7.lock
fi

exec 9>"$lock"
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' "$digest" "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" "$mode" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
mode = sys.argv[2]
budget = config['budget']
assert budget['trials'] == (1 if mode == 'healthy' else 80)
assert budget['seconds'] == (720 if mode == 'healthy' else 3600)
assert budget['max_faults_per_trial'] == (1 if mode == 'healthy' else 3)
for artifact in config['runtime_artifacts']:
    path = Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit(f'runtime artifact SHA mismatch: {path}')
receipt = config['source_equivalence_receipt']
path = Path(receipt['path'])
if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
    raise SystemExit(f'source equivalence SHA mismatch: {path}')
print(f"{config['case_id']} {mode} pins valid", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
