#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v2/cases/HBASE-02.named-rs-pilot.json"
output="$base/data/mallory/pilots/HBASE-02-named-rs-v2"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'cf580b401d4f69cb8c120fc4ebd68d4e244df6b59b1e41ff0c1cdcabfbb4903c' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["budget"]["trials"] == 4
assert config["budget"]["max_faults_per_trial"] == 1
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
print("HBASE-02 named-RS pilot config and artifacts verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
