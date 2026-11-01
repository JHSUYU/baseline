#!/usr/bin/env bash
# start_logged_in_nodes.sh <system> [K] -- for each node without a running queue whose Claude login
# works, start its queue.  Prints one line per node it starts or skips.
system=${1:?usage: start_logged_in_nodes.sh <system> [K]}
k=${2:-5}
for n in node0 node1 node2 node3 node4; do
  if ssh -o BatchMode=yes -o ConnectTimeout=8 "$n" "pgrep -f '^python3 queue.py ${system} ' >/dev/null"; then
    continue
  fi
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$n" 'test -s ~/.claude/.credentials.json'; then
    echo "$n: not logged in"
    continue
  fi
  ok=$(ssh -o BatchMode=yes "$n" 'cd /tmp && DISABLE_AUTOUPDATER=1 timeout 120 ~/.local/bin/claude --model "claude-opus-5-5[1m]" -p "Reply with the single word OK." 2>&1 | tail -1')
  if [[ ${ok} == *OK* ]]; then
    ssh -o BatchMode=yes "$n" "/bulk/specula-adhoc/start-queue.sh ${system} ${k}"
  else
    echo "$n: login test failed: ${ok:0:120}"
  fi
done
