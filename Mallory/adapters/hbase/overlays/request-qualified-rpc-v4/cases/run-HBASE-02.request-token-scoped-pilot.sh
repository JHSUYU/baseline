#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v4/cases/HBASE-02.request-token-scoped-pilot.json"
output="$base/data/mallory/pilots/HBASE-02-request-token-scoped-v4"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '70deb2ce12bb0486b8ce43b2a983db88965380385343a7c7bed3efbfd85d385f' "$config" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config["mapping"]["status"] == "runtime_attested"
assert config["replay_identity_mode"] == "qualified_request_site"
for artifact in config["runtime_artifacts"]:
    path = Path(artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise SystemExit(f"runtime artifact SHA mismatch: {path}")
for receipt in (config["calibration_attestation"]["healthy_causal_audit"],):
    path = Path(receipt["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
        raise SystemExit(f"healthy audit SHA mismatch: {path}")
print("HBASE-02 v4 scoped request pilot artifacts verified", flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
