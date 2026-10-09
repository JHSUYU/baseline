#!/usr/bin/env bash
set -u

if [ "$#" -ne 3 ]; then
  printf 'usage: run_lane2_campaign.sh CONFIG.json OUTPUT_DIR CORE_RELEASE_ROOT\n' >&2
  exit 2
fi

config=$1
output=$2
core_release=$3
mkdir -p "$output" /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/zookeeper-lane2.lock
if ! flock -n 9; then
  printf 'ZooKeeper lane2 lock is busy\n' >&2
  exit 75
fi

export MALLORY_ATTEMPT_ID="zk-lane2-$(date -u +%Y%m%dT%H%M%SZ)"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cd /users/ZhenyuLi/baseline || exit 1
python3 Mallory/adapters/zookeeper/verify_lane2_campaign.py "$config" >> "$output/driver.log" 2>&1
preflight=$?
if [ "$preflight" -ne 0 ]; then
  printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d,"attempt_id":"%s","stage":"preflight"}\n' \
    "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$preflight" "$MALLORY_ATTEMPT_ID" > "$output/driver-exit.json"
  exit "$preflight"
fi
manifest="$core_release/manifest.json"
python3 Mallory/dispatch/core_release.py --verify "$manifest" >> "$output/driver.log" 2>&1
release_check=$?
if [ "$release_check" -ne 0 ]; then
  printf 'Core release verification failed\n' >> "$output/driver.log"
  exit "$release_check"
fi
cp "$manifest" "$output/core-release-manifest.json"
export PYTHONPATH="$core_release:/users/ZhenyuLi/baseline"
export MALLORY_CORE_RELEASE_ID="${core_release##*/}"
export MALLORY_CORE_RELEASE_ID_ROOT="$core_release"
cd "$core_release" || exit 1
python3 -c 'import Mallory.core.campaign as c; import os; assert os.path.realpath(c.__file__).startswith(os.path.realpath(os.environ["MALLORY_CORE_RELEASE_ID_ROOT"]) + os.sep)' >> "$output/driver.log" 2>&1
import_check=$?
if [ "$import_check" -ne 0 ]; then
  printf 'Campaign module did not import from pinned core release\n' >> "$output/driver.log"
  exit "$import_check"
fi
python3 -m Mallory.core.campaign --config "$config" --out "$output" >> "$output/driver.log" 2>&1
status=$?
finished=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d,"attempt_id":"%s"}\n' \
  "$started" "$finished" "$status" "$MALLORY_ATTEMPT_ID" > "$output/driver-exit.json"
exit "$status"
