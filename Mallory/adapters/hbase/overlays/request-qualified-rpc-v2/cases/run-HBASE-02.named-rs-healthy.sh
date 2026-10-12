#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v2/cases/HBASE-02.named-rs-healthy.json"
output="$base/data/mallory/calibration_v33/HBASE-02"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '54540701218c4e44aa5cf1618b006e59ab0ff64facec23477789e61fb62b9712' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["calibration_only"] and config["require_event_time_paths"]
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
print("HBASE-02 named-RS healthy config and artifacts verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
