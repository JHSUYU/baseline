#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
lane=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9
release=$repo/Mallory/dispatch/releases/5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040
config=$lane/runtime/configs/HBASE-24-recoverable-read-v1-healthy.json
site=$lane/runtime/cases/HBASE-24-recoverable-read-v1/sites.json
output=$repo/data/mallory/calibration_hbase24_recoverable_v1/HBASE-24
worker_log=${output}.worker.log

if [[ $(hostname -s) != node1 || ${MALLORY_HBASE24_NODE1_GRANT:-} != healthy-only ]]; then
  printf 'HBASE-24 requires a dispatch healthy-only grant on node1\n' >&2
  exit 75
fi

mkdir -p /tmp/mallory-lanes "$(dirname "$output")"
exec 9>/tmp/mallory-lanes/hbase-lane9.lock
flock -n 9 || { printf 'lane9 is busy\n' >&2; exit 75; }
test ! -e "$output" && test ! -e "$worker_log"

printf '%s  %s\n' \
  ab32d1fb9b9a7b3562dc97f1000ebef5335c5b57e6dbab889f5edfde588d456d "$site" \
  a42c4c5a625d0870cc9fbccef71c3a1eac7bbd702c081e88e1abf89ea5534f72 "$config" \
  07c23da7699217aa4f51c389cde3539ee241ece05efa5d11575bc5d804cf4e80 "$lane/runtime/agent.jar" \
  5f83ae1146141c3559073c13fd5b9b952f09af87e4c9d83d2288fbd2c4fd2827 "$lane/runtime/adapter.jar" \
  c82e7304119fc97d5ffdf87e2656f286735675e81f5236030db265c6e239a12f "$lane/runtime/classes/edu/uva/liftlab/mallory/hbase/pilot/SelectedJUnit.class" \
  0b0beaeb6880a31149641d2d848b863712885469670c12099586d7f798522564 "$lane/runtime/junit-platform-launcher.jar" \
  b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5 /users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6-tests.jar \
  6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957 /users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-zookeeper-2.6.6.jar \
  4f3c0ba3dece475ef8be18294e770cf63a0a3df52444aa814f5d92c6e1b3b5db "$lane/source-equivalence.json" \
  ba0ee569fccf2a69057860800bc05a2fe1db0d5a4b368c490485ee542b0c55b2 "$lane/source/hbase-server/src/main/java/org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs.java" \
  0cc57f0c0d21b679997580cc8169e1b8f70ed0bb77e8bbb6bb6d41e5bca8a2b2 "$lane/source/hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/TestZKProcedure.java" \
  f946cd3195c5969b55ce5d079c272a7b12d673c5406a98ef026dc8fcea18fa88 "$lane/source/hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper.java" \
  | sha256sum -c -

cd "$repo"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
export PYTHONPATH="$release:$repo"

set +e
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only >"$worker_log" 2>&1
campaign_code=$?
if [[ -e "$output/result.json" ]]; then
  printf '%s\n' "$campaign_code" >"$output/campaign-exit.txt"
  python3 -m Mallory.core.audit --campaign "$output" \
    --out "$output/offline-causal-audit.json" >>"$worker_log" 2>&1
  audit_code=$?
  printf '%s\n' "$audit_code" >"$output/audit-exit.txt"
else
  audit_code=1
fi
set -e

printf 'HBASE-24 healthy campaign=%s audit=%s output=%s\n' \
  "$campaign_code" "$audit_code" "$output"
test "$campaign_code" -eq 0 && test "$audit_code" -eq 0
