#!/usr/bin/env bash
set -u

if [ "$#" -ne 3 ]; then
  printf 'usage: run_lane2_healthy.sh CONFIG.json OUTPUT_DIR CORE_RELEASE_ROOT\n' >&2
  exit 2
fi
config=$1
output=$2
core_release=$3
mkdir -p "$output" /tmp/mallory-lanes
exec 9>/tmp/mallory-lanes/zookeeper-lane2.lock
flock -n 9 || { printf 'ZooKeeper lane2 lock is busy\n' >&2; exit 75; }

export MALLORY_ATTEMPT_ID="zk-healthy-$(date -u +%Y%m%dT%H%M%SZ)"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
cd /users/ZhenyuLi/baseline || exit 1
python3 Mallory/adapters/zookeeper/verify_lane2_campaign.py --healthy-only "$config" >> "$output/driver.log" 2>&1 || exit $?
manifest="$core_release/manifest.json"
python3 Mallory/dispatch/core_release.py --verify "$manifest" >> "$output/driver.log" 2>&1 || exit $?
cp "$manifest" "$output/core-release-manifest.json"
export PYTHONPATH="$core_release:/users/ZhenyuLi/baseline"
export MALLORY_CORE_RELEASE_ID="${core_release##*/}"
export MALLORY_CORE_RELEASE_ID_ROOT="$core_release"
cd "$core_release" || exit 1
python3 -c 'import Mallory.core.campaign as c; import os; assert os.path.realpath(c.__file__).startswith(os.path.realpath(os.environ["MALLORY_CORE_RELEASE_ID_ROOT"]) + os.sep)' >> "$output/driver.log" 2>&1 || exit $?
python3 -m Mallory.core.campaign --config "$config" --out "$output" >> "$output/driver.log" 2>&1
status=$?
if [ "$status" -eq 0 ]; then
  python3 -m Mallory.core.audit --campaign "$output" --out "$output/offline-causal-audit.json" >> "$output/driver.log" 2>&1
  status=$?
fi
printf '{"started_utc":"%s","finished_utc":"%s","exit_code":%d,"attempt_id":"%s"}\n' \
  "$started" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status" "$MALLORY_ATTEMPT_ID" > "$output/driver-exit.json"
exit "$status"
