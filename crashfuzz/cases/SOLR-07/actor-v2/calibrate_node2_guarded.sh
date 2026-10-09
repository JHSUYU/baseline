#!/usr/bin/env bash
set -euo pipefail

case_dir=/users/ZhenyuLi/baseline/crashfuzz/cases/SOLR-07/actor-v2
cd "$case_dir"
rm -f calibration-node2.exit
exec > >(tee -a "$case_dir/calibration-node2.log") 2>&1
trap 'printf "%s\n" "$?" > "$case_dir/calibration-node2.exit"' EXIT

while true; do
  running_java=$(pgrep -c java || true)
  free_kib=$(df -P -k "$case_dir" | awk 'NR==2 {print $4}')
  if (( running_java <= 2 && free_kib >= 10485760 )); then
    break
  fi
  printf 'waiting for Solr JUnit slot: java=%s free_kib=%s\n' "$running_java" "$free_kib"
  sleep 10
done

python3 calibrate_v2.py
