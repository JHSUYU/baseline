#!/usr/bin/env bash
# start-queue.sh <system> [K] -- (re)start this node's queue for a system (default K=5), over the
# inventory's whole case list; claims in <system>/claims/ keep nodes from taking the same case.
# Run it on each node: ssh nodeN /bulk/specula-adhoc/start-queue.sh <system> [K]
system=${1:?usage: start-queue.sh <system> [K]}
k=${2:-5}
root=/bulk/specula-adhoc
cd "${root}"
for pid in $(pgrep -f "^python3 queue.py ${system} "); do kill "${pid}"; done
cases=$(cut -f1 "${system}/inventory.tsv" | tail -n +2 | tr '\n' ' ')
nohup python3 queue.py "${system}" "${k}" ${cases} > "${system}/queue.out.$(hostname -s)" 2>&1 < /dev/null &
echo "$(hostname -s): queue started for ${system}, K=${k} (pid $!)"
