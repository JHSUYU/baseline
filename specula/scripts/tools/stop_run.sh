#!/usr/bin/env bash
# stop_run.sh <case> -- stop one Specula run (its pipeline process and every descendant) so it can be
# resumed later with run-case.sh <case> --run-id=<id>.  Never touches another case's processes.
case_id=${1:?usage: stop_run.sh <case>}
root=$(ps -eo pid,args | awk -v c="pipelinelib.py ${case_id}|" 'index($0, c) {print $1}')
[[ -n ${root} ]] || { echo "${case_id}: no pipeline process"; exit 0; }
tree() { local p=$1; echo "$p"; for c in $(ps -eo pid,ppid | awk -v p="$p" '$2==p {print $1}'); do tree "$c"; done; }
pids=$(for r in ${root}; do tree "$r"; done)
kill -TERM ${pids} 2>/dev/null
for i in $(seq 30); do
  alive=$(for p in ${pids}; do kill -0 "$p" 2>/dev/null && echo "$p"; done)
  [[ -z ${alive} ]] && break
  sleep 1
done
[[ -n ${alive} ]] && kill -KILL ${alive} 2>/dev/null
echo "${case_id}: stopped $(echo ${pids} | wc -w) processes"
