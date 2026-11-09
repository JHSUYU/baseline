#!/usr/bin/env bash
# MC-3 reproduction driver. Usage: test_bugMC-3_truncate_detach.sh <SRC_TREE> <method> [<method>...]
# SRC_TREE: a checkout of base_commit with hbase-procedure and hbase-server already test-compiled.
# Each test method runs in its own JVM, with an outer timeout.
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)"
SRC="$1"; shift
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-11/env.sh
LOGDIR="$HERE/MC-3-logs"; mkdir -p "$LOGDIR"
TESTDIR="$SRC/hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver"
cp "$HERE/test_bugMC-3_truncate_detach.java" "$TESTDIR/SpeculaMC3TruncateDetachTest.java"
cd "$SRC" || exit 2
for m in "$@"; do
  export MC3_OUT="$LOGDIR/$m.mc3.txt"; : > "$MC3_OUT"
  echo "=== $m"
  timeout 14m mvn -B -o test -pl hbase-procedure,hbase-server \
    -Denforcer.skip=true -Dmaven.javadoc.skip=true \
    -Dtest="SpeculaMC3TruncateDetachTest#$m" -DfailIfNoTests=false \
    -Dsurefire.failIfNoSpecifiedTests=false -Dsurefire.timeout=800 \
    > "$LOGDIR/$m.mvn.log" 2>&1
  echo "mvn exit=$?"
  cp hbase-server/target/surefire-reports/*SpeculaMC3TruncateDetachTest-output.txt "$LOGDIR/$m.output.txt" 2>/dev/null
  grep -E 'Tests run:|BUILD |COMPILATION ERROR|ERROR.*\.java' "$LOGDIR/$m.mvn.log" | tail -6 | cut -c1-220
  cut -c1-400 "$MC3_OUT"
done
