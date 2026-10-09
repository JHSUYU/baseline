#!/usr/bin/env bash
# One queued original-JUnit trial after the node1 owners explicitly release the slot.
set -euo pipefail

here=/users/ZhenyuLi/hdfs54-original-campaign
runs=$here/runs
session=hdfs54_original_node1_pilot

if [[ $(hostname -s) != node1 ]]; then
  echo 'This HDFS-54 pilot is staged for node1' >&2
  exit 2
fi
if [[ ! -f "$runs/.node1-pilot-lease.json" ]]; then
  echo 'Node1 pilot lease is absent; first reserve the plan on node2 and obtain owner handoff' >&2
  exit 3
fi
if tmux has-session -t "$session" 2>/dev/null; then
  echo "HDFS-54 node1 pilot already active: $session"
  exit 0
fi
if tmux list-sessions -F '#S' 2>/dev/null |
    rg -q '^(solr13_stage2|hdfs_storage_v2_startup_cal|hdfs_storage_v2_startup_fuzz)$'; then
  echo 'Solr13 or HDFS actor-V2 owns the node1 cluster slot' >&2
  exit 4
fi
if /usr/lib/jvm/java-8-openjdk-amd64/bin/jps -l |
    rg -q 'research\.solr13\.OriginalJUnit|hdfs.*actor.*v2'; then
  echo 'Solr13 or HDFS actor-V2 JVM is still running' >&2
  exit 4
fi
python3 - "$runs/campaign-state.json" "$runs/.node1-pilot-lease.json" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
lease = json.loads(Path(sys.argv[2]).read_text())
raw = state_path.read_bytes()
state = json.loads(raw)
assert lease['owner'] == 'node1-one-trial'
assert lease['checkpoint_sha256'] == hashlib.sha256(raw).hexdigest()
assert state['test'] == ('org.apache.hadoop.hdfs.TestFileChecksum#'
                         'testStripedAndReplicatedFileChecksum2[0]')
assert state['effective'] == 1 and len(state['attempts']) == 1
assert len(state['queue']) == 31 and state['in_flight'] is None
assert state['attempts'][0]['id'] == '01f09073125e7810'
assert state['attempts'][0]['result'] == 'effective'
assert state['effective'] == sum(row['result'] == 'effective'
                                  for row in state['attempts'])
assert not set(row['id'] for row in state['attempts']) & set(
    row['id'] for row in state['queue'])
assert len({row['id'] for row in state['queue']}) == len(state['queue'])
assert os.statvfs('/users/ZhenyuLi').f_bavail * os.statvfs('/users/ZhenyuLi').f_frsize > 8 * (1024 ** 3)
mem_available = next(int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))
assert mem_available > 8 * (1024 ** 2)
print('Reserved node1 HDFS-54 pilot: one new attempt after effective trial 1')
PY

tmux new-session -d -s "$session" \
  "cd '$here' && nice -n 10 python3 campaign.py --runs '$runs' --effective-budget 80 --max-faults 8 --attempt-cap 320 --once 1 >> '$here/campaign.node1-pilot.log' 2>&1"
echo "Started one queued HDFS-54 trial in node1 tmux $session"
