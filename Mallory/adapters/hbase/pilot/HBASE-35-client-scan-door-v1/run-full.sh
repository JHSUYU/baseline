#!/usr/bin/env bash
set -euo pipefail

base=/users/ZhenyuLi/baseline
release="$base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
config="$base/Mallory/adapters/hbase/pilot/HBASE-35-client-scan-door-v1/HBASE-35-client-scan-door-v1-full.json"
pilot="$base/data/mallory/pilots/HBASE-35-client-scan-v1-receipt.json"
output="$base/data/mallory/HBASE-35/campaigns/client-scan-v1-full"

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
flock -n 9
test ! -e "$output"
cd "$base"
python3 -m Mallory.dispatch.core_release --verify "$release/manifest.json"
printf '%s  %s\n' \
  '8ef1fa816b6854205d1a61a012a9ec13c30aa202aea51cad5ca6095006572563' "$config" \
  'c224c7dd0dedf4b81adc3584b59c74c6287c7e8633834116295cd8e11e960787' "$pilot" \
  '30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8' "$release/manifest.json" | sha256sum -c -
export PYTHONPATH="$release:$base"
python3 - "$config" "$pilot" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
from Mallory.core.campaign import validate_config

config = json.loads(Path(sys.argv[1]).read_text())
validate_config(config)
assert config['case_id'] == 'HBASE-35'
assert config['cluster_test'] == 'org.apache.hadoop.hbase.util.TestHBaseFsckMOB#testQuarantineCorruptMobFile'
assert config['budget'] == {'trials': 80, 'seconds': 3600,
                            'max_faults_per_trial': 3,
                            'trial_timeout_seconds': 780}
assert config['require_event_time_paths'] is True
pilot = json.loads(Path(sys.argv[2]).read_text())
assert pilot['fault_trials'] == 3
assert pilot['strict_postfault_path_trials'] == 1
assert pilot['selected_exception_trials'] == 0
for artifact in config['runtime_artifacts']:
    path = Path(artifact['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit(f'runtime artifact SHA mismatch: {path}')
attestation = config['calibration_attestation']
for path, digest in (
    (Path(config['mapping']['verified_healthy_probe']), attestation['healthy_result_sha256']),
    (Path(attestation['healthy_causal_audit']['path']),
     attestation['healthy_causal_audit']['sha256']),
):
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(f'healthy attestation SHA mismatch: {path}')
print('HBASE-35 full config, healthy seed and runtime pins valid', flush=True)
PY
python3 -m Mallory.core.campaign --config "$config" --out "$output"
