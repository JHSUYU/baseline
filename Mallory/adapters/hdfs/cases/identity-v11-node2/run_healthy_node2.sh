#!/usr/bin/env bash
set -eu

release=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf
export PYTHONPATH="${release}:/users/ZhenyuLi/baseline"
export MALLORY_HDFS_DIST_ROOT=/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3
exec 9>/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
flock -x 9
python3 -m Mallory.core.campaign \
  --config /users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v11-configs/HDFS-28-healthy.json \
  --out /users/ZhenyuLi/baseline/data/mallory/calibration_v11_node2/HDFS-28 \
  --calibration-only
