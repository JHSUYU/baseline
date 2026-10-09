#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
case_dir="$base/Mallory/adapters/solr/cases/SOLR-13/source-admission-v1"
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$case_dir/healthy-node2-lane3.json"
out="$base/data/mallory/calibration_solr13_source_admission_v1_node2/SOLR-13"
lane_lock=/tmp/mallory-lanes/solr-lane3.lock
source_lock=/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock

test "$(hostname -s)" = node2
test "$(sha256sum "$config" | cut -d ' ' -f1)" = f9316df2c50108e5375eda7d4ba59688b6a564958f9f4ce96412b21eb7f668ec
test ! -e "$out"
mkdir -p "$(dirname "$out")" "$(dirname "$lane_lock")"
exec 9>"$lane_lock"
flock -n 9
exec 8>"$source_lock"
flock -n 8

# Five GiB floor, two one-GiB scratch allowances, and a 128 MiB sync margin.
disk_available=$(df -PB1 "$base" | awk 'NR == 2 { print $4 }')
test "$disk_available" -ge 7650410496
memory_available_kib=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
test "$memory_available_kib" -ge 8388608

python3 "$case_dir/preflight.py"
PYTHONPATH="$release:$base" python3 - "$config" <<'PY'
import json
import sys
from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts

with open(sys.argv[1], encoding="utf-8") as stream:
    config = json.load(stream)
assert config["case_id"] == "SOLR-13"
assert config["calibration_only"] is True
assert config["auto_promote_if_healthy"] is False
assert config["budget"]["trials"] == 1
assert config["require_event_time_paths"] is True
assert config["reject_coarse_roots"] is True
validate_config(config)
verify_runtime_artifacts(config)
PY

exec env PYTHONPATH="$release:$base" python3 -m Mallory.core.campaign \
  --config "$config" --out "$out" --calibration-only
