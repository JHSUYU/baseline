#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
runtime=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next/runtime
release="$base/Mallory/dispatch/releases/96dd5cda2fe8e3f67130c8232fb98fa316a1eeac9a2ff3237075d7d8fe95538d"
config="$runtime/configs/HBASE-07-client-only-v1-full.json"
output="$base/data/mallory/HBASE-07/campaigns/client-only-v1"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'ac6ca902ffa33bd4ed95a2fdc55921c5fa46a4f81dde564e04c8e4d811ac99c0' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
print("HBASE-07 client-only full config and artifacts verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
