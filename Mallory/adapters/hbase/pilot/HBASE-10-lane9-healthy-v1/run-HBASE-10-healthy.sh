#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
package="$base/Mallory/adapters/hbase/pilot/HBASE-10-request-qualified-healthy-v2"
config="$package/HBASE-10.healthy.json"
output="$base/data/mallory/calibration_hbase10_qualified_v2/HBASE-10"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '6be801a664c989cb54279913320d82d642f7d24bcb4c16e7377a80c2d246ac89' "$config" \
  '0556b1c75075570a4f006fde44d6b1f61ad127fb0a252fcfd0b8e3462041e819' "$package/HBASE-10.sites.json" \
  'c9eca5b3073f7aa56a45b9acd867c3a81539e98e34dbf0a9394148b8712c1879' "$package/receipt.json" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 "$package/preflight.py"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["calibration_only"] is True
assert config["budget"]["trials"] == 1
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
print("HBASE-10 request-qualified healthy pins valid", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output" --calibration-only
