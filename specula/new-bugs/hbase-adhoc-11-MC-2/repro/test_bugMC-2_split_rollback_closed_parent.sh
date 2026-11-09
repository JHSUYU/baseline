#!/usr/bin/env bash
# MC-2 reproduction driver.  usage: test_bugMC-2_split_rollback_closed_parent.sh <tree> <method> [<method> ...]
# Copies the test into <tree>/hbase-server (same module as the workload, TestRegionMove) and runs
# each method in its own JVM/minicluster, bounded by `timeout`. Build first with BUILD=1.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE="$1"; shift
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-11/env.sh
CLS=TestMC2SplitRollbackClosedParent
DEST="$TREE/hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/$CLS.java"
cp "$HERE/test_bugMC-2_$CLS.java" "$DEST"
LOGS="${LOGS:-$HERE/MC-2-logs}"; mkdir -p "$LOGS"
cd "$TREE" || exit 2
if [ "${BUILD:-0}" = 1 ]; then
  # No `install`: the shared dependency repo must stay as it is. Reactor resolves both modules.
  timeout -k 30 1500 mvn -B -o test-compile -DskipTests -Dmaven.javadoc.skip=true -Denforcer.skip=true \
    -pl hbase-procedure,hbase-server > "$LOGS/build-$(basename "$TREE").log" 2>&1
  rc=$?; echo "build exit=$rc"; [ $rc -eq 0 ] || { tail -30 "$LOGS/build-$(basename "$TREE").log"; exit $rc; }
fi
for m in "$@"; do
  log="$LOGS/$(basename "$TREE")-$m.log"
  echo "=== $m (tree=$TREE, HEAD=$(git -C "$TREE" rev-parse --short HEAD 2>/dev/null || echo archive))"
  timeout -k 30 "${TEST_TIMEOUT:-900}" mvn -B -o surefire:test -pl hbase-procedure,hbase-server \
    -Dtest="org.apache.hadoop.hbase.regionserver.$CLS#$m" -DfailIfNoTests=false \
    -Dsurefire.failIfNoSpecifiedTests=false > "$log" 2>&1
  echo "mvn exit=$?"
  grep -E 'Tests run:|BUILD (SUCCESS|FAILURE)' "$log" | tail -3
  rep="$TREE/hbase-server/target/surefire-reports/org.apache.hadoop.hbase.regionserver.$CLS-output.txt"
  if [ -f "$rep" ]; then cp "$rep" "$LOGS/$(basename "$TREE")-$m-output.txt"; grep -a '^MC2: ' "$rep"; else grep -a 'MC2: ' "$log"; fi
done
