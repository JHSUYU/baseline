#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
config="$base/Mallory/adapters/hbase/overlays/request-qualified-rpc-v5/cases/HBASE-10.client-scoped-v2-full.json"
pilot="$base/data/mallory/pilots/HBASE-10-client-scoped-v2-precision-positive-receipt.json"
output="$base/data/mallory/HBASE-10/campaigns/client-bound-v2-full"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  'ccc9cdb4b997f8446b8bf0111e01264d70c6e0a4c5c62fa77deb95557fed2408' "$config" \
  'c6a10af999676213bcd728d53f7dbf2eaff744babb9f2b8ce28058ebf4d030ec' "$pilot" \
  'a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15' "$release/manifest.json" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" "$pilot" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config['mapping']['eligible_for_full_campaign'] is True
assert config['budget'] == {'trials': 80, 'seconds': 3600,
                            'max_faults_per_trial': 3,
                            'trial_timeout_seconds': 600}
assert config['require_event_time_paths'] is True
pilot = json.loads(Path(sys.argv[2]).read_text())
assert pilot['kind'] == 'bounded_client_bound_fault_retry_target_positive'
assert pilot['strict_postfault_target_paths'] == 1
assert pilot['exact_selected_exceptions'] == 0
for artifact in config['runtime_artifacts']:
    path = Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit(f'runtime artifact SHA mismatch: {path}')
attestation = config['calibration_attestation']
for path, digest in (
    (Path(config['mapping']['verified_healthy_probe']),
     attestation['healthy_result_sha256']),
    (Path(attestation['healthy_causal_audit']['path']),
     attestation['healthy_causal_audit']['sha256']),
):
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(f'healthy attestation SHA mismatch: {path}')
print('HBASE-10 client-bound full pins valid', flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
