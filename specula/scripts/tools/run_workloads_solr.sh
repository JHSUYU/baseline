#!/usr/bin/env bash
# run_workloads_solr.sh <tree> <ivy user dir> <outdir> <inventory.tsv> <targets dir>
# B3 baseline / reach probe for Solr: run each distinct workload test once, sequentially, in <tree> (module solr/core,
# Ant + Ivy), with the exact test_command of its first case's target file.  Keep the
# Ant log and the test reports (solr/build/solr-core/test/TEST-*.xml, and tests-report.txt, which holds every test JVM output line), and append to
# <outdir>/summary.tsv: workload, rc, PASS|FAIL, seconds, junit4's "Tests summary" line, probe lines per case.
tree=$1; ivy=$2; out=$3; inv=$4; targets=$5
source /bulk/specula-adhoc/solr-env.sh
export IVY_USER_DIR=$ivy
export ANT_OPTS="-Xmx4g -Divy.default.ivy.user.dir=$IVY_USER_DIR"
mkdir -p "$out"
tail -n +2 "$inv" | awk -F'\t' '!seen[$8]++ {print $8 "\t" $1}' | while IFS=$'\t' read -r t case; do
  cls=${t%%#*}; m=${t##*#}; short=${cls##*.}
  # The case's own test_command from its target file, with <Class>/<method> filled in, run from the tree root.
  cmd=$(sed -n 's/^  test_command: "\(.*\)"$/\1/p' "$targets/$case.yaml" | sed -e "s/<Class>/$short/" -e "s/<method>/$m/")
  extra=$(echo "$cmd" | grep -o " -D\(tests\.\(nightly\|awaitsfix\|useSecurityManager\)\|args\)=[^ ]*" | tr -d '\n')
  log=$out/${short}_${m}.log
  rep=$tree/solr/build/solr-core/test
  rm -rf "$rep"
  start=$(date +%s)
  (cd "$tree" && echo "+ $cmd" > "$log" && timeout 2400 bash -c "$cmd" < /dev/null >> "$log" 2>&1)
  rc=$?
  end=$(date +%s)
  rm -rf "$out/${short}_${m}.reports"; mkdir -p "$out/${short}_${m}.reports"
  cp "$rep"/TEST-*.xml "$rep"/tests-*.txt "$out/${short}_${m}.reports/" 2>/dev/null
  res=$(grep -o 'Tests summary:.*' "$log" | tail -1)
  ok=FAIL
  grep -q 'BUILD SUCCESSFUL' "$log" && echo "$res" | grep -qE '^Tests summary: 1 suite, 1 test$' && ok=PASS
  probes=$(cat "$out/${short}_${m}.reports"/tests-report.txt 2>/dev/null | grep -o 'SPECULA-PROBE[ a-z0-9-]*' \
    | tr ' ' '\n' | grep '^solr-adhoc' | sort | uniq -c | awk '{printf "%s=%s ", $2, $1}')
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$t" "$rc" "$ok" "$((end-start))" "$res" "$probes" "$extra" >> "$out/summary.tsv"
done
