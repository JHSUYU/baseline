#!/usr/bin/env bash
set -euo pipefail

lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane7
baseline=/users/ZhenyuLi/baseline
release=$baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
out=$lane/healthy-HBASE-24-v5b
lock=/tmp/mallory-lanes/hbase-lane7.lock

mkdir -p "$(dirname "$lock")"
exec 9>"$lock"
flock -n 9
test ! -e "$out"
export PYTHONPATH="$release:$baseline"
cd "$baseline"
set +e
python3 -m Mallory.core.campaign \
  --config "$lane/runtime/configs/HBASE-24-lane7-healthy.json" \
  --out "$out"
campaign_rc=$?
python3 -m Mallory.core.audit \
  --campaign "$out" \
  --out "$out/offline-causal-audit.json"
audit_rc=$?
set -e
printf 'campaign_exit=%s audit_exit=%s\n' "$campaign_rc" "$audit_rc"
