#!/usr/bin/env bash
set -euo pipefail

cd /run/user/20003/mallory-native-depth-v16
receipt=/dev/shm/mallory-hdfs-balancer-v16-node0/guarded-healthy-v16b.json
while [[ ! -f "$receipt" ]]; do
  sleep 5
done
python3 - "$receipt" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    receipt = json.load(stream)
if receipt.get("status") != "healthy_seed":
    raise SystemExit("V16b healthy gate failed; no faults started")
PY
export MALLORY_NATIVE_ENGINE_ROOT=/users/ZhenyuLi/.mallory-worktrees/native-repeated-io-v1/Mallory/static_scope_port/original_engine
exec python3 -u -m Mallory.adapters.hdfs.graphchecker_port.balancer_v15.run_pilot_v16 --through 4
