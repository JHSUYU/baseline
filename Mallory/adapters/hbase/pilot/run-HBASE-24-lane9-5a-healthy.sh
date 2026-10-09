#!/usr/bin/env bash
set -euo pipefail

lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9
baseline=/users/ZhenyuLi/baseline
release=$baseline/Mallory/dispatch/releases/5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040
config=$lane/runtime/configs/HBASE-24-lane9-5a-healthy.json
out=$lane/healthy-HBASE-24-5a
lock=/tmp/mallory-lanes/hbase-lane9.lock

mkdir -p "$(dirname "$lock")"
exec 9>"$lock"
flock -n 9
test ! -e "$out"
printf '%s  %s\n' 0393751f58ec6ff1da43c19cd395be691cf3518f805b58745cbcb3237127ce8f "$config" | sha256sum -c -
export PYTHONPATH="$release:$baseline"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
cd "$baseline"
set +e
python3 -m Mallory.core.campaign --config "$config" --out "$out"
campaign_rc=$?
python3 -m Mallory.core.audit --campaign "$out" --out "$out/offline-causal-audit.json"
audit_rc=$?
set -e
printf 'campaign_exit=%s audit_exit=%s\n' "$campaign_rc" "$audit_rc"
