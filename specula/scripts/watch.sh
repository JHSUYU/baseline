#!/usr/bin/env bash
# watch.sh <system> -- one line per phase change, error, completion or new confirmation verdict
# of the system's ad hoc runs (<system>/logs/*.log).
system=${1:?usage: watch.sh <system>}
shopt -s nullglob
logs=/bulk/specula-adhoc/${system}/logs
cd "${logs}" || exit 1
seen=${logs}/.seen-verdicts
touch "$seen"
( tail -n0 -F *.log 2>&1 |
  awk '/^==> .* <==$/{f=$2; next} /\] PHASE |ERROR|Traceback|finished \(exit|Pipeline completed|BLOCKED|Rate limited/ && !/: running |: reading /{print f": "$0; fflush()}' ) &
while true; do
  for log in *.log; do
    case=${log%.log}
    run=$(grep -oP '^Run:\s+\K\S+' "$log" | tail -1)
    [[ -n $run ]] || continue
    for v in /users/ZhenyuLi/Specula/runs/${run}/${case}/.specula-output/confirmation/*/verdict.json; do
      grep -qxF "$v" "$seen" && continue
      echo "$v" >> "$seen"
      echo "VERDICT ${case}/$(basename "$(dirname "$v")"): $(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("verdict") or d.get("status") or list(d)[:6])' "$v" 2>&1 | cut -c1-160)"
    done
  done
  sleep 30
done
