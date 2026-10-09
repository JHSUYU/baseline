#!/usr/bin/env bash
set -euo pipefail

export HBASE32_RUN_ROOT=/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32/work-lots
export HBASE32_TEST_METHOD=testLotsOfRegionReplicas
if [[ "${1:-}" == run && "${2:-}" =~ ^r[0-9]+$ &&
      -f "$HBASE32_RUN_ROOT/.pause-before-next-run" ]]; then
  printf '%s\n' "${2:-unknown}" > "$HBASE32_RUN_ROOT/.paused-before-run-id"
  while [[ -f "$HBASE32_RUN_ROOT/.pause-before-next-run" ]]; do
    sleep 0.2
  done
fi
exec /users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-32/work/run.sh "$@"
