#!/usr/bin/env bash
# wait_all.sh [seconds] -- block until any system's case finishes / needs the operator / logs an
# ERROR line, or the time runs out (default 540 s).  Prints what changed, per system.
limit=${1:-540}
end=$((SECONDS + limit))
while (( SECONDS < end )); do
  out=""
  for s in hdfs zookeeper hbase solr; do
    [[ -d /bulk/specula-adhoc/$s/claims ]] || continue
    r=$(/bulk/specula-adhoc/wait_event.sh $s 1 2>/dev/null)
    [[ $r == CHANGED* ]] && out+="== $s"$'\n'"$(echo "$r" | grep -v '^#')"$'\n'
  done
  [[ -n $out ]] && { echo "$out"; exit 0; }
  sleep 30
done
echo "no change"
