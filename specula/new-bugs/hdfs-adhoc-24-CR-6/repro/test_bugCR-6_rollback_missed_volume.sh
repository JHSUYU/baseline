#!/usr/bin/env bash
# CR-6 reproduction driver (hdfs-adhoc-24, target BlockPoolSliceStorage.java:421).
#
# Installs test_bugCR-6_rollback_missed_volume.java as SpeculaAdhocCR6Test in the workload's test
# package of a pristine checkout at 734dd8a67cd, compiles the module offline and runs the tests.
# No main-source file is changed.
#
#   bash test_bugCR-6_rollback_missed_volume.sh [TestMethod]      (default: all five tests)
#
# Env: SPECULA_SRC (checkout, default: the CR-6 confirmation worktree), SPECULA_ENV.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC=${SPECULA_SRC:-/users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/confirmation/CR-6/worktree}
ENV_SH=${SPECULA_ENV:-/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-24/env.sh}
MODULE=hadoop-hdfs-project/hadoop-hdfs
CLS=SpeculaAdhocCR6Test
TEST=${1:-$CLS}
[ "$TEST" = "$CLS" ] || TEST="$CLS#$TEST"
OUT=$HERE/test_bugCR-6_rollback_missed_volume

# shellcheck disable=SC1090
source "$ENV_SH"
cd "$SRC" || exit 2
[ "$(git rev-parse --short=11 HEAD)" = "734dd8a67cd" ] || { echo "checkout is not at 734dd8a67cd" >&2; exit 2; }
if [ -n "$(git status --porcelain -- "$MODULE/src/main")" ]; then
  echo "main sources are modified; refusing to run" >&2; exit 2
fi

cp "$HERE/test_bugCR-6_rollback_missed_volume.java" "$MODULE/src/test/java/org/apache/hadoop/hdfs/$CLS.java"

echo "== compile (mvn -o test-compile -pl $MODULE)"
timeout 1800 mvn -B -o test-compile -Dmaven.javadoc.skip=true -pl "$MODULE" > "$OUT.compile.log" 2>&1
rc=$?
if [ $rc -ne 0 ] || ! grep -q "BUILD SUCCESS" "$OUT.compile.log"; then
  echo "compile failed (exit $rc), see $OUT.compile.log" >&2
  grep -E "ERROR" "$OUT.compile.log" | head -20 >&2
  exit 1
fi

echo "== run $TEST"
start=$(date +%s)
timeout 2400 mvn -B -o surefire:test -pl "$MODULE" -Dtest="$TEST" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$OUT.mvn.log" 2>&1
rc=$?
echo "   mvn exit $rc after $(( $(date +%s) - start ))s"
cp "$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLS-output.txt" "$OUT.output.txt" 2>/dev/null
cp "$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLS.txt" "$OUT.surefire.txt" 2>/dev/null
cat "$OUT.surefire.txt" 2>/dev/null
grep -E "Tests run:|FAIL|ERROR\]" "$OUT.mvn.log" | head -20
echo "== [CR-6] lines (full log: $OUT.output.txt)"
grep -E "^\[CR-6\]|^    " "$OUT.output.txt" 2>/dev/null > "$OUT.cr6.txt"
head -600 "$OUT.cr6.txt"
exit $rc
