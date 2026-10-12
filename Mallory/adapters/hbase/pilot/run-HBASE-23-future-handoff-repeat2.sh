#!/usr/bin/env bash
set -u
set -o pipefail

lane_root=/users/ZhenyuLi/.mallory-worktrees/hbase/lane9-next
release_root=/users/ZhenyuLi/baseline/Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f
case_config=$lane_root/runtime/configs/HBASE-23-lane9-next-future-handoff-healthy.json
worker_exit=$lane_root/runtime/HBASE-23-handoff-fa5f-repeat2-worker-exit.txt

exec 9>/tmp/mallory-lanes/hbase-lane9-next.lock
if ! flock -n 9; then
  printf 'lane9-next lock busy\n' >&2
  exit 75
fi
if [[ -e "$worker_exit" ]]; then
  printf 'repeat worker already ran\n' >&2
  exit 98
fi

export PYTHONPATH="$release_root:/users/ZhenyuLi/baseline"
for repeat in 01 02; do
  case_output=$lane_root/healthy-HBASE-23-handoff-fa5f-repeat$repeat
  worker_log=$lane_root/runtime/HBASE-23-handoff-fa5f-repeat$repeat-worker.log
  if [[ -e "$case_output" || -e "$worker_log" ]]; then
    printf 'repeat output already exists: %s\n' "$case_output" >&2
    exit 98
  fi
  python3 -m Mallory.core.campaign --config "$case_config" --out "$case_output" --calibration-only >"$worker_log" 2>&1
  campaign_code=$?
  printf '%s\n' "$campaign_code" >"$case_output/campaign-exit.txt"
  python3 -m Mallory.core.audit --campaign "$case_output" --out "$case_output/offline-causal-audit.json" >>"$worker_log" 2>&1
  audit_code=$?
  printf '%s\n' "$audit_code" >"$case_output/audit-exit.txt"
  python3 - "$case_output" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
summary = json.loads((root / "result.json").read_text())
trial = json.loads((root / "trials/r0000/result.json").read_text())
audit = json.loads((root / "offline-causal-audit.json").read_text())
feedback = trial.get("feedback") or {}
instances = feedback.get("target_instances") or []
qualified = (
    summary.get("status") == "calibration_complete"
    and summary.get("healthy_seed_valid") is True
    and trial.get("junit_validation", {}).get("status") == "passed"
    and feedback.get("target_reached") is True
    and feedback.get("target_threw") is False
    and instances
    and all(row.get("node") not in (None, "", "unknown") for row in instances)
    and audit.get("require_event_time_paths") is True
    and audit.get("report_gate_passed") is True
    and audit.get("healthy_observed_path_doors", 0) > 0
)
(root / "qualified.txt").write_text("1\n" if qualified else "0\n")
sys.exit(0 if qualified else 1)
PY
  qualification_code=$?
  if [[ "$qualification_code" == 0 ]]; then
    printf 'qualified repeat %s\n' "$repeat" >"$worker_exit"
    exit 0
  fi
done
printf 'no qualified repeat\n' >"$worker_exit"
exit 0
