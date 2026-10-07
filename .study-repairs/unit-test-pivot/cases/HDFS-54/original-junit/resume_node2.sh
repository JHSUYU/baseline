#!/usr/bin/env bash
# Run on node2 only after the current node2 owner explicitly releases its slot.
set -euo pipefail

here=/users/ZhenyuLi/hdfs54-original-campaign
runs=$here/runs
session=hdfs54_original_80

if [[ $(hostname -s) != node2 ]]; then
  echo 'HDFS-54 original campaign is staged for node2' >&2
  exit 2
fi
if tmux has-session -t "$session" 2>/dev/null; then
  echo "HDFS-54 campaign already active: $session"
  exit 0
fi
if [[ -e "$runs/.node1-pilot-active" ]]; then
  echo 'HDFS-54 node1 pilot owns the next queued plan; merge its checkpoint before node2 resumes' >&2
  exit 5
fi
if tmux list-sessions -F '#S' 2>/dev/null | rg -q '^solr36_37'; then
  echo 'Solr 36/37 node2 session remains active; wait for explicit release' >&2
  exit 3
fi
if /usr/lib/jvm/java-8-openjdk-amd64/bin/jps -l |
    awk '$2 != "sun.tools.jps.Jps" { print }' | rg -q .; then
  echo 'Another JVM is active on node2; cannot start HDFS-54 cluster' >&2
  exit 4
fi
python3 - "$runs/campaign-state.json" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text())
assert state['test'] == ('org.apache.hadoop.hdfs.TestFileChecksum#'
                         'testStripedAndReplicatedFileChecksum2[0]')
assert state['effective'] >= 2, 'node1 trial 2 must be reconciled before resume'
assert [row['id'] for row in state['attempts'][:2]] == [
    '01f09073125e7810', '09a99b3dfe331261']
assert state['effective'] == sum(row['result'] == 'effective'
                                  for row in state['attempts'])
assert not set(row['id'] for row in state['attempts']) & set(
    row['id'] for row in state['queue'])
assert len({row['id'] for row in state['queue']}) == len(state['queue'])
print('Resuming HDFS-54:', state['effective'], 'effective,',
      len(state['queue']), 'queued, in_flight=', state['in_flight'] is not None)
PY

tmux new-session -d -s "$session" \
  "cd '$here' && nice -n 10 python3 campaign.py --runs '$runs' --effective-budget 80 --max-faults 8 --attempt-cap 320 >> '$here/campaign.log' 2>&1"
echo "Started node2 tmux session $session"
