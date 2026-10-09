#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/hdfs40-coverage-io
python3 system-test/run_original.py --test-class append --method testMultipleAppends --name healthy/append --probe --coverage --timeout-seconds 240 > healthy-append-driver.log 2>&1
python3 system-test/run_original.py --test-class restart --method testAppendWithPipelineRecovery --name healthy/restart --probe --coverage --timeout-seconds 240 > healthy-restart-driver.log 2>&1
printf 'HEALTHY_PROBES_FINISHED\n' > healthy-probes.done
