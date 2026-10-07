#!/usr/bin/env bash
set -euo pipefail

export HBASE32_RUN_ROOT=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work-lots
export HBASE32_TEST_METHOD=testLotsOfRegionReplicas
if [[ "${1:-}" == run && -f "$HBASE32_RUN_ROOT/.pause-before-next-run" ]]; then
  printf '%s\n' "${2:-unknown}" > "$HBASE32_RUN_ROOT/.paused-before-run-id"
  while [[ -f "$HBASE32_RUN_ROOT/.pause-before-next-run" ]]; do
    sleep 0.2
  done
fi
exec /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work/run.sh "$@"
