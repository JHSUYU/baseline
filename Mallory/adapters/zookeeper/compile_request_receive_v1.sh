#!/usr/bin/env bash
set -u
root=/users/ZhenyuLi/.mallory-worktrees/zookeeper-requestrecv-v1-lane2
out=/users/ZhenyuLi/baseline/data/mallory/calibration/ZOOKEEPER-02-03/requestrecv-v1
mkdir -p "$out" /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/zookeeper-lane2.lock
flock -n 9 || { printf 'ZooKeeper lane2 lock busy\n' >&2; exit 75; }
cd "$root" || exit 1
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
timeout 600 mvn -B -ntp -pl zookeeper-server -am -DskipTests test-compile > "$out/compile.log" 2>&1
status=$?
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d}\n' \
  "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" > "$out/compile-exit.json"
exit "$status"
