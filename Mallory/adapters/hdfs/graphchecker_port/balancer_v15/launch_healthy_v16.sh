#!/usr/bin/env bash
set -euo pipefail

cd /run/user/20003/mallory-native-depth-v16
unshare -U -c --keep-caps -m --fork --propagation private \
  sh -c 'mount --bind "$1" "$1" && mount -o remount,bind,ro "$1" && shift && exec "$@"' \
  sh /proj/silentfailure-PG0 \
  python3 -m Mallory.native_graphchecker_campaign.guarded_healthy \
  --pg0 /proj/silentfailure-PG0 \
  --config /dev/shm/mallory-hdfs-balancer-v16-node0/campaign-config-v16.json \
  --output /dev/shm/mallory-hdfs-balancer-v16-node0/formal \
  --raw-root /dev/shm/mallory-hdfs-balancer-v16-node0/raw \
  --receipt /dev/shm/mallory-hdfs-balancer-v16-node0/guarded-healthy-v16.json \
  --config-sha256 ed719939ba0c6e03bafaa100c1729a6a3a05ff6c3a9e947abecd34b10202f49d \
  --campaign-source-sha256 c08afcda3a22d5ea16847bbfd801d1800814a625cf4fe92d4f2d43b3edace9e1 \
  --max-raw-bytes 2000000000 --max-output-bytes 3000000000 \
  --min-raw-available-bytes 5000000000 --min-output-available-bytes 5000000000 \
  --min-root-available-bytes 1600000000 \
  --min-memory-available-bytes 10000000000 \
  --max-wall-seconds 1800 --poll-seconds 1
