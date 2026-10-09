#!/usr/bin/env bash
set -euo pipefail

cd /users/ZhenyuLi/baseline
export PYTHONPATH=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf:/users/ZhenyuLi/baseline

exec python3 -m Mallory.dispatch.lane_handoff \
  --state-root data/mallory/dispatch/node0-hdfs49-smallseed-lane2 \
  --host node0 \
  --lane-id hdfs-lane2 \
  --hosts-file Mallory/dispatch/shards/node0-hosts.json \
  --ready-manifest data/mallory/dispatch/node0-hdfs49-smallseed-lane2/ready.json \
  --inventory Mallory/cases/revisions/HDFS-49-smallseed-v1.inventory.json \
  --source-reference Mallory/cases/revisions/HDFS-49-smallseed-v1.source-reference.json \
  --core-release-manifest Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf/manifest.json \
  --wait-for-tmux-exit mallory-node0-hdfs-alternates-lane2 \
  --wait-for-case HDFS-39 \
  --priority HDFS-49 \
  --stop-when-empty \
  --poll-seconds 20
