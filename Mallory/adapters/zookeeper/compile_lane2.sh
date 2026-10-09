#!/usr/bin/env bash
set -u

source_root=/users/ZhenyuLi/.mallory-worktrees/zookeeper-lane2
output_root=/users/ZhenyuLi/.mallory-worktrees/bin/zk-lane2-compile
lock_file=/tmp/mallory-lanes/zookeeper-lane2.lock

mkdir -p "$output_root" /tmp/mallory-lanes
exec 9>"$lock_file"
if ! flock -n 9; then
  printf 'lane lock busy\n' > "$output_root/error.txt"
  exit 75
fi

cd "$source_root" || exit 1
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
timeout 600 mvn -q -pl zookeeper-server -am -DskipTests test-compile > "$output_root/compile.log" 2>&1
status=$?
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d}\n' \
  "$started" "$finished" "$status" > "$output_root/exit.json"
exit "$status"
