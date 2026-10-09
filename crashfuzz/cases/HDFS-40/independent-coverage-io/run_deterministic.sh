#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/hdfs40-coverage-io
python3 system-test/run_original.py --test-class append --method testFailedAppendBlockRejection --name healthy/deterministic-failed-rejection --probe --coverage --timeout-seconds 180 > healthy-deterministic-failed-rejection-driver.log 2>&1
python3 system-test/run_original.py --test-class append --method testMultiAppend2 --name healthy/deterministic-multi-append2 --probe --coverage --timeout-seconds 180 > healthy-deterministic-multi-append2-driver.log 2>&1
printf 'DETERMINISTIC_FINISHED\n' > deterministic.done
