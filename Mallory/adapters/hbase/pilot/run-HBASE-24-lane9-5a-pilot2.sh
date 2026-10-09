#!/usr/bin/env bash
set -euo pipefail

lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9
baseline=/users/ZhenyuLi/baseline
release=$baseline/Mallory/dispatch/releases/5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040
config=$lane/runtime/configs/HBASE-24-lane9-5a-pilot2.json
out=$lane/pilot-HBASE-24-5a-2
lock=/tmp/mallory-lanes/hbase-lane9.lock

mkdir -p "$(dirname "$lock")"
exec 9>"$lock"
flock -n 9
test ! -e "$out"
printf '%s  %s\n' 9f0291b4549669af71ad69ef5598bb7f7c5ace6af1a7047f4b1922ba95731ed9 "$config" | sha256sum -c -
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
