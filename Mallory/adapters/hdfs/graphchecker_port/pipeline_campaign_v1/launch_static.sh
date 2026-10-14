#!/usr/bin/env bash
set -euo pipefail
code=/dev/shm/mallory-hdfs11-pipeline-code-v1/Mallory/adapters/hdfs/graphchecker_port/pipeline_campaign_v1
run=/dev/shm/mallory-hdfs11-pipeline-v1-run
exec python3 "$code/guarded_command.py" \
  --receipt "$run/static-v2-guard-receipt.json" \
  --stdout "$run/static-v2.stdout.log" \
  --stderr "$run/static-v2.stderr.log" \
  --min-root-bytes 1073741824 \
  --min-shm-bytes 3221225472 \
  --min-memory-bytes 17179869184 \
  --poll-seconds 3 \
  -- python3 "$code/run_scope.py" \
  /dev/shm/mallory-hdfs11-pipeline-code-v1/scope-input-node1-v3.json \
  /dev/shm/mallory-hdfs11-pipeline-v2-static
