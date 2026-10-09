#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v1/cases/HBASE-02.lane9-full.json"
output="$base/data/mallory/HBASE-02/campaigns/qualified-get-v1"
review="$base/data/mallory/pilots/HBASE-02-qualified-get-v1-precision-review.json"
receipt="$base/data/mallory/pilots/HBASE-02-qualified-get-v1-receipt.json"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'c1434cf269123eeb70e92682f8eabdfbdbfa3f326ff40fc99fc31791869b2195' "$config" \
  '88b4d07d617397368c67e321a91828be0bfd0af6c146d1f2ab1ed2c62092901f' "$review" \
  '1597c9ec6823b671acf6ae0a64c1e1dfe3eefa4ee73792b6236e30480cb94c75' "$receipt" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["budget"]["trials"] == 80
assert config["budget"]["seconds"] == 3600
assert config["budget"]["max_faults_per_trial"] == 3
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
print("HBASE-02 qualified Get full config and artifacts verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
