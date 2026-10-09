#!/bin/sh
set -u
case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/hdfs_recovery_shared/independent
cd "$case_dir" || exit 1
attempt=0
while [ "$attempt" -lt 3 ]; do
  python3 -u "$case_dir/campaign.py" >> "$case_dir/campaign.log" 2>&1
  status=$?
  if [ "$status" -eq 0 ]; then
    exit 0
  fi
  attempt=$((attempt + 1))
  printf 'campaign exit=%s restart=%s/3\n' "$status" "$attempt" >> "$case_dir/campaign.log"
  sleep 10
done
exit 1
