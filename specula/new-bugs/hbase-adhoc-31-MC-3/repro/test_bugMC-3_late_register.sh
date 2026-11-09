#!/usr/bin/env bash
# MC-3 reproduction driver. Usage: test_bugMC-3_late_register.sh <method> [log-suffix]
#   method: level0PlainKill | level1SessionExpiresLate | level1SessionExpiresEarly
# Env: HBASE_TREE (default: this finding's worktree), MC3_FAIL_FAST_LIMIT (unset = real default of 10),
#      MC3_SPLIT_BY_ZK (unset = true, as the workload), SKIP_BUILD=1
# Copies the test into the module, builds it, runs it under an outer timeout, prints the MC3| lines.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)"
TREE="${HBASE_TREE:-$OUT/confirmation/MC-3/worktree}"
METHOD="${1:?method}"
SUFFIX="${2:-$METHOD}"
LOG="$HERE/MC-3_$SUFFIX.log"
# shellcheck disable=SC1091
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-31/env.sh

T="$TREE/hbase-server/src/test/java/org/apache/hadoop/hbase"
cp "$HERE/test_bugMC-3_SpeculaMC3RegionServer.java" "$T/regionserver/SpeculaMC3RegionServer.java"
cp "$HERE/test_bugMC-3_TestSpeculaMC3LateRegister.java" "$T/master/TestSpeculaMC3LateRegister.java"

cd "$TREE" || exit 2
echo "tree: $TREE  HEAD: $(git rev-parse --short HEAD 2>/dev/null || cat .pristine-commit)  method: $METHOD  fail-fast: ${MC3_FAIL_FAST_LIMIT:-default(10)}  split-by-zk: ${MC3_SPLIT_BY_ZK:-true}"
if [ -z "${SKIP_BUILD:-}" ]; then
  timeout 1500 mvn -B -o -q test-compile -pl hbase-server -DskipTests -Denforcer.skip=true \
    -Dmaven.javadoc.skip=true > "$HERE/MC-3_build.log" 2>&1 \
    || { echo "BUILD FAILED"; grep -E 'ERROR.*\.java|BUILD' "$HERE/MC-3_build.log" | head -30; exit 2; }
fi
timeout 900 mvn -B -o surefire:test -pl hbase-server \
  -Dtest="TestSpeculaMC3LateRegister#$METHOD" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false > "$HERE/MC-3_$SUFFIX.mvn.log" 2>&1
RC=$?
R="$TREE/hbase-server/target/surefire-reports/org.apache.hadoop.hbase.master.TestSpeculaMC3LateRegister-output.txt"
cp "$R" "$LOG" 2>/dev/null
echo "surefire exit code: $RC (124 = outer timeout)"
grep -E 'Tests run:|BUILD (SUCCESS|FAILURE)' "$HERE/MC-3_$SUFFIX.mvn.log" | tail -3
grep -E 'MC3\|' "$LOG" | sed -E 's/^([0-9-]+T?[ ]?[0-9:,.]+).*MC3\|/\1 /' | cut -c1-420
echo "--- full log: $LOG"
exit $RC
