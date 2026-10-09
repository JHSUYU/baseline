#!/usr/bin/env bash
set -euo pipefail

here=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-17/independent
for attempt in 1 2 3 4 5 6; do
  suffix="calibration-${attempt}"
  log="$here/logs/$suffix.log"
  set +e
  "$here/fuzz.sh" run "$suffix" > "$log" 2>&1
  code=$?
  set -e
  if [[ "$code" == 0 ]] && rg -q 'HBASE17 B5_EXIT ordinal=[0-9]+ outcome=true' "$log" \
    && rg -q 'HBASE17 JUNIT found=1 succeeded=1 failed=0' "$log"; then
    cp "$log" "$here/logs/seed.log"
    cp "$here/logs/$suffix.exec" "$here/logs/seed.exec"
    printf 'selected=%s\n' "$suffix" > "$here/logs/seed_selection.txt"
    exit 0
  fi
done
exit 1
