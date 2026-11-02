#!/usr/bin/env bash
# run_workloads_hbase.sh <tree> <m2> <outdir> <inventory.tsv> [online]
# B3 baseline / reach probe for HBase: run each distinct workload test once, sequentially, in <tree>
# (module hbase-server), keep its log and surefire reports, and append to <outdir>/summary.tsv:
# workload, rc, PASS|FAIL, seconds, surefire's last "Tests run" line, probe lines per case.
tree=$1; m2=$2; out=$3; inv=$4; online=${5:-}
source /bulk/specula-adhoc/hbase-env.sh
export MAVEN_OPTS="-Xmx8g -Dmaven.repo.local=$m2"
mkdir -p "$out"
cut -f8 "$inv" | tail -n +2 | sort -u | while read -r t; do
  cls=${t%%#*}; m=${t##*#}; short=${cls##*.}
  log=$out/${short}_${m}.log
  rm -rf "$tree/hbase-server/target/surefire-reports"
  off=-o; [ -n "$online" ] && off=; online=
  start=$(date +%s)
  (cd "$tree" && timeout 1800 mvn -B $off test -PrunAllTests -pl hbase-server \
     -Dmaven.repo.local="$m2" -Dtest="${short}#${m}" -DfailIfNoTests=false \
     -Dsurefire.failIfNoSpecifiedTests=false > "$log" 2>&1)
  rc=$?
  end=$(date +%s)
  rm -rf "$out/${short}_${m}.reports"
  cp -r "$tree/hbase-server/target/surefire-reports" "$out/${short}_${m}.reports" 2>/dev/null
  res=$(grep -E "Tests run:.*Fail" "$log" | tail -1 | sed 's/^\[[A-Z]*\] //')
  ok=FAIL
  grep -q 'BUILD SUCCESS' "$log" && grep -qE "Tests run: [1-9][0-9]*, Failures: 0, Errors: 0" "$log" && ok=PASS
  probes=$(cat "$out/${short}_${m}.reports"/*-output.txt 2>/dev/null | grep -o 'SPECULA-PROBE.*' \
    | tr ' ' '\n' | grep '^hbase-adhoc' | sort | uniq -c | awk '{printf "%s=%s ", $2, $1}')
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" "$t" "$rc" "$ok" "$((end-start))" "$res" "$probes" >> "$out/summary.tsv"
done
