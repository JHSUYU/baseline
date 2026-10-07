#!/usr/bin/env bash
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd -P)
cd "$here"
mkdir -p calibration
python3 prepare_calibration.py > calibration/selection.log 2>&1
python3 run.py "$here/calibration/attempt-01" \
  --agent "$here/solrleadership-independent-agent.jar" \
  --fault-plan "$here/calibration/fault.properties" \
  > "$here/calibration/driver.log" 2>&1
