#!/usr/bin/env bash
set -u

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
config_root=/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v12-configs
output_root=/users/ZhenyuLi/baseline/data/mallory/calibration_v12_node2
lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
export PYTHONPATH="${release}:/users/ZhenyuLi/baseline"
export MALLORY_HDFS_DIST_ROOT=/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3

mkdir -p "$output_root" "$(dirname "$lock")"
exec 9>"$lock"
flock -x 9
for id in HDFS-25 HDFS-27 HDFS-28; do
  echo "$(date -u +%FT%TZ) start $id"
  python3 -m Mallory.core.campaign \
    --config "$config_root/$id-healthy.json" \
    --out "$output_root/$id" \
    --calibration-only >"$output_root/$id-controller.log" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) finish $id rc=$rc"
done
