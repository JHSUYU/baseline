#!/usr/bin/env bash
# MC-2 reproduction runner (hdfs-adhoc-24, target BlockPoolSliceStorage.java:421).
#
# Copies repro/test_bugMC-2_rollback_gap.java into the pinned worktree as
# org.apache.hadoop.hdfs.TestBugMC2RollbackGap (a variant of the workload TestDFSUpgrade#testUpgrade,
# same module), compiles the test sources offline and runs the four methods with surefire.
# Escalation level 0: real MiniDFSCluster NameNode/DataNode processes, public startup options and
# the documented upgrade/rollback commands, the workload's own UpgradeUtilities fixtures. No
# failpoints, no sleeps in system code, no source patch, no hand-written VERSION file.
#
#   bash repro/test_bugMC-2_rollback_gap.sh            # compile + run
#   SKIP_COMPILE=1 bash repro/test_bugMC-2_rollback_gap.sh
#
# Exit 0 iff all four test methods pass (the three bug methods assert the buggy outcome; the
# control asserts the correct one).
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WT=${MC2_WORKTREE:-/users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/confirmation/MC-2/worktree}
ENV_SH=${SPECULA_ENV:-/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-24/env.sh}
MODULE=hadoop-hdfs-project/hadoop-hdfs
CLS=TestBugMC2RollbackGap
OUT=$HERE/test_bugMC-2_rollback_gap.output.txt
MVNLOG=$HERE/test_bugMC-2_rollback_gap.mvn.log

# shellcheck disable=SC1090
source "$ENV_SH"
[ "$(git -C "$WT" rev-parse --short=11 HEAD)" = 734dd8a67cd ] || { echo "worktree not at 734dd8a67cd" >&2; exit 2; }
if ! git -C "$WT" diff --quiet -- "$MODULE/src/main"; then
  echo "worktree main sources are modified; refusing to run" >&2; exit 2
fi
cp "$HERE/test_bugMC-2_rollback_gap.java" "$WT/$MODULE/src/test/java/org/apache/hadoop/hdfs/$CLS.java"

if [ "${SKIP_COMPILE:-0}" != 1 ]; then
  echo "== compile (mvn -o test-compile -pl $MODULE)"
  ( cd "$WT" && timeout 1800 mvn -B -o test-compile -Dmaven.javadoc.skip=true -pl "$MODULE" ) \
    > "$HERE/test_bugMC-2_rollback_gap.compile.log" 2>&1
  if ! grep -q "BUILD SUCCESS" "$HERE/test_bugMC-2_rollback_gap.compile.log"; then
    echo "compile failed, see $HERE/test_bugMC-2_rollback_gap.compile.log" >&2
    grep -E "ERROR" "$HERE/test_bugMC-2_rollback_gap.compile.log" | head -20 >&2
    exit 1
  fi
fi

echo "== run $CLS (surefire, timeout 900 s)"
start=$(date +%s)
( cd "$WT" && timeout 900 mvn -B -o surefire:test -pl "$MODULE" -Dtest="$CLS" \
    -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false ) > "$MVNLOG" 2>&1
rc=$?
echo "   mvn exit $rc after $(( $(date +%s) - start ))s"
[ $rc -eq 124 ] && echo "   TIMEOUT: treat as a hang, not retried" >&2
rep=$WT/$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLS-output.txt
[ -f "$rep" ] && cp "$rep" "$OUT"
cp "$WT/$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLS.txt" "$HERE/test_bugMC-2_rollback_gap.surefire.txt" 2>/dev/null

echo "== evidence lines"
grep -h "^MC2-EVIDENCE" "$OUT" 2>/dev/null
echo "== test result"
grep -E "Tests run:|FAIL|ERROR\]" "$MVNLOG" | head -12
# hadoop-project ignores test failures (mvn says BUILD SUCCESS anyway): check the counts
if grep -q "Tests run: 4, Failures: 0, Errors: 0, Skipped: 0" "$MVNLOG"; then
  echo "== RESULT: all 4 methods passed (3 bug reproductions + control)"
  exit 0
fi
echo "== RESULT: not all methods passed" >&2
exit 1
