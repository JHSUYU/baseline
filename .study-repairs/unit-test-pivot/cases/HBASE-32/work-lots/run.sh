#!/usr/bin/env bash
set -euo pipefail

export HBASE32_RUN_ROOT=/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work-lots
export HBASE32_TEST_METHOD=testLotsOfRegionReplicas
exec /users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-32/work/run.sh "$@"
