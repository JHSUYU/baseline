#!/usr/bin/env bash
set -euo pipefail

repo=/users/ZhenyuLi/baseline
case_dir="$repo/Mallory/adapters/hdfs/cases/next-v16"
release="$repo/Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
out="$repo/data/mallory/calibration_v16_node2/HDFS-29"
receipt="$repo/data/mallory/calibration_v16_node2_artifacts/HDFS-29"
lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock

cd "$repo"
python3 "$case_dir/preflight_hdfs29_node2_v16.py" > "$receipt/prelaunch.json"
export PYTHONPATH="$release:$repo${PYTHONPATH:+:$PYTHONPATH}"

set +e
flock -n "$lock" python3 -m Mallory.core.campaign \
  --config "$case_dir/HDFS-29-lease-recovery-healthy-v16-node2.json" \
  --out "$out" --calibration-only
campaign_rc=$?
set -e
printf '%s\n' "$campaign_rc" > "$receipt/campaign.exit-code"

if [[ -f "$out/result.json" ]]; then
  set +e
  python3 -m Mallory.core.audit --campaign "$out" \
    --out "$out/offline-causal-audit.json"
  audit_rc=$?
  python3 "$case_dir/gate_hdfs29_lease_recovery_v16_node2.py" --campaign "$out" \
    > "$receipt/postrun-gate.json"
  gate_rc=$?
  set -e
  printf '%s\n' "$audit_rc" > "$receipt/audit.exit-code"
  printf '%s\n' "$gate_rc" > "$receipt/gate.exit-code"
  if (( campaign_rc == 0 && audit_rc == 0 && gate_rc == 0 )); then
    exit 0
  fi
fi
exit 2
