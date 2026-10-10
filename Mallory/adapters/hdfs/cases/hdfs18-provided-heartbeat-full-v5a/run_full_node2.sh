#!/usr/bin/env bash
set -euo pipefail

if [[ "$(hostname -s)" != node2 || "${MALLORY_HDFS18_V5A_NODE2_GRANT:-}" != full-v5a ]]; then
  echo 'HDFS-18 full-v5a requires dispatch GO on node2' >&2
  exit 75
fi

task_base=/users/ZhenyuLi/baseline
task_here="$task_base/Mallory/adapters/hdfs/cases/hdfs18-provided-heartbeat-full-v5a"
task_release="$task_base/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
task_out=/tmp/mallory-hdfs18-provided-heartbeat-full-v5a-node2
task_log="${task_out}.worker.log"
task_lock=/tmp/mallory-lanes/hdfs-identity-v8-node2.lock
mkdir -p "$(dirname "$task_lock")"
exec 9>"$task_lock"
flock -n 9 || { echo 'HDFS node2 lane is busy' >&2; exit 75; }

python3 -B "$task_here/preflight.py"
cd /tmp
export PYTHONPATH="$task_release:$task_base"

task_phase=$(python3 - "$task_out" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
checkpoint, gate = out / 'checkpoint.json', out / 'healthy-gate.json'
if not checkpoint.exists():
    if gate.exists():
        raise SystemExit('healthy gate exists without checkpoint')
    print('calibration')
else:
    state = json.loads(checkpoint.read_text())
    if state.get('calibration_only') is False:
        print('promotion')
    elif (state.get('calibration_only') is True and
          state.get('status') == 'calibration_complete' and
          state.get('completed_trials') == [0]):
        print('promotion')
    elif (state.get('calibration_only') is True and
          state.get('status') == 'running' and
          not any(i > 0 for i in state.get('completed_trials', []))):
        print('calibration')
    else:
        raise SystemExit('checkpoint is not a safe healthy phase')
PY
)
if [[ "$task_phase" == calibration ]]; then
  python3 -B -m Mallory.core.campaign \
    --config "$task_here/HDFS-18-node2-full-v5a.json" \
    --out "$task_out" --calibration-only >>"$task_log" 2>&1
fi

python3 -B "$task_here/healthy_gate.py" --campaign "$task_out" --promote \
  >>"$task_log" 2>&1 || {
    echo 'HDFS-18 fresh r0000 failed exact typed path gate' >&2
    exit 75
  }
python3 -B "$task_here/healthy_gate.py" --campaign "$task_out" --verify-promotion \
  >>"$task_log" 2>&1
set +e
python3 -B -m Mallory.core.campaign \
  --config "$task_here/HDFS-18-node2-full-v5a.json" \
  --out "$task_out" >>"$task_log" 2>&1
task_campaign_code=$?
printf '%s\n' "$task_campaign_code" >"$task_out/campaign-exit.txt"
python3 -B "$task_here/healthy_gate.py" --campaign "$task_out" --verify-promotion \
  >>"$task_log" 2>&1
task_gate_code=$?
python3 -B -m Mallory.core.audit --campaign "$task_out" \
  --out "$task_out/offline-causal-audit.json" >>"$task_log" 2>&1
task_audit_code=$?
printf '%s\n' "$task_audit_code" >"$task_out/audit-exit.txt"
set -e
if [[ "$task_campaign_code" -ne 0 || "$task_gate_code" -ne 0 ||
      ( "$task_audit_code" -ne 0 && "$task_audit_code" -ne 2 ) ]]; then
  echo "HDFS-18 controller or audit failed; inspect $task_log" >&2
  exit 1
fi
