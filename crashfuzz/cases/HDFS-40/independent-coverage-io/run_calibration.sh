#!/usr/bin/env bash
set -u
cd /users/ZhenyuLi/hdfs40-coverage-io
python3 system-test/run_original.py --test-class append4 --method testUpdateNeededReplicationsForAppendedFile --name healthy/append4-nonfatal --probe --coverage --timeout-seconds 180 > healthy-append4-nonfatal-driver.log 2>&1
python3 system-test/run_original.py --test-class append4 --method testAppendInsufficientLocations --name healthy/append4-expected-fatal --probe --coverage --timeout-seconds 180 > healthy-append4-expected-fatal-driver.log 2>&1
python3 system-test/run_original.py --test-class append --method testMultipleAppends --name healthy/semantic-append --probe --coverage --timeout-seconds 180 > healthy-semantic-append-driver.log 2>&1
printf 'CALIBRATION_FINISHED\n' > calibration.done
