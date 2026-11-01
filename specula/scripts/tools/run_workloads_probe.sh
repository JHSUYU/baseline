#!/usr/bin/env bash
# run_workloads.sh <tree> <m2> <outdir> <inventory.tsv> -- run each distinct workload test once (B3).
tree=$1; m2=$2; out=$3; inv=$4
source /bulk/specula-adhoc/env.sh
mkdir -p "$out"
cut -f9 "$inv" | tail -n +2 | sed 's/\[[0-9]*\]$//' | sort -u | while read -r t; do
  cls=${t%%#*}; m=${t##*#}; short=${cls##*.}
  log=$out/${short}_${m}.log
  start=$(date +%s)
  (cd "$tree" && timeout 1200 mvn -B -o surefire:test -pl hadoop-hdfs-project/hadoop-hdfs \
     -Dmaven.repo.local="$m2" -Dtest="${short}#${m}" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
     -Dsurefire.redirectTestOutputToFile=false > "$log" 2>&1)
  rc=$?
  cp "$tree/hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/${cls}-output.txt" "$out/${short}_${m}.output.txt" 2>/dev/null
  end=$(date +%s)
  res=$(grep -E "Tests run:.*Fail" "$log" | tail -1 | sed 's/^\[[A-Z]*\] //')
  printf "%s\t%s\t%s\t%ss\t%s\n" "$t" "$rc" "$(grep -q 'BUILD SUCCESS' "$log" && echo PASS || echo FAIL)" "$((end-start))" "$res" >> "$out/summary.tsv"
done
