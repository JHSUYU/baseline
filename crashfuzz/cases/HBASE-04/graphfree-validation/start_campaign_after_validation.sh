#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-04/graphfree-validation

for ((poll=0; poll<720; poll++)); do
  if [[ -f "$case_dir/read_retry_pair.exit" ]]; then
    break
  fi
  sleep 15
done

if [[ ! -f "$case_dir/read_retry_pair.exit" ]]; then
  printf 'SKIP campaign: representative replay did not finish in polling window\n'
  exit 1
fi

python3 "$case_dir/validate_replay.py" > "$case_dir/validation.log" 2>&1
"$case_dir/run.sh" build-campaign
printf 'START independent campaign %s\n' "$(date -u +%FT%TZ)"
python3 -u "$case_dir/campaign.py" > "$case_dir/campaign.log" 2>&1
printf 'END independent campaign %s\n' "$(date -u +%FT%TZ)"
