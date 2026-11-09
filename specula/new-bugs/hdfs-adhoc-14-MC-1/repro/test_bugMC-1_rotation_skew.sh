#!/usr/bin/env bash
# MC-1 reproduction runner (Specula ad hoc target hdfs-adhoc-14).
#
# Installs test_bugMC-1_rotation_skew.java as SpeculaAdhoc14MC1Test into the
# confirmation worktree. The worktree is at the pinned base_commit 734dd8a67cd
# with no instrumentation. The script then builds hadoop-hdfs-client and
# hadoop-hdfs in one reactor, so the test runs on the clean classes and not on
# the instrumented jar in the shared local repo. It runs the requested test
# methods and prints the evidence lines.
#
# Usage: test_bugMC-1_rotation_skew.sh [method ...]
#   default methods: testRotationSkewOverwriteOn testRotationSkewOverwriteOffControl
#                    testRotationSkewOverwriteOnSixDns
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_ROOT="$(cd "$HERE/.." && pwd)"
WT="${WT:-$OUT_ROOT/confirmation/MC-1/worktree}"
ENV_SH="${ENV_SH:-/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-14/env.sh}"
LOGDIR="${LOGDIR:-$OUT_ROOT/confirmation/MC-1/runs}"
mkdir -p "$LOGDIR"

# shellcheck disable=SC1090
source "$ENV_SH"
cd "$WT" || exit 2

echo "== worktree $(pwd)"
echo "== HEAD $(git rev-parse HEAD)"
DIRTY="$(git status --porcelain -- '*/src/main/*')"
if [ -n "$DIRTY" ]; then
  echo "ERROR: main sources differ from the pinned commit:"; echo "$DIRTY"; exit 2
fi
echo "== main sources identical to pinned commit (no instrumentation)"

DEST=hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/SpeculaAdhoc14MC1Test.java
cp "$HERE/test_bugMC-1_rotation_skew.java" "$DEST"

METHODS=("$@")
if [ ${#METHODS[@]} -eq 0 ]; then
  METHODS=(testRotationSkewOverwriteOn testRotationSkewOverwriteOffControl testRotationSkewOverwriteOnSixDns)
fi

RC_ALL=0
for M in "${METHODS[@]}"; do
  LOG="$LOGDIR/mvn-$M.log"
  echo "== running SpeculaAdhoc14MC1Test#$M (log: $LOG)"
  timeout 30m mvn -B -o test \
    -pl hadoop-hdfs-project/hadoop-hdfs-client,hadoop-hdfs-project/hadoop-hdfs \
    -Dtest="SpeculaAdhoc14MC1Test#$M" -DfailIfNoTests=false \
    -Dsurefire.failIfNoSpecifiedTests=false -Dsurefire.fork.timeout=1700 \
    -Dmaven.javadoc.skip=true > "$LOG" 2>&1
  RC=$?
  REP=hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports
  cp "$REP/org.apache.hadoop.hdfs.SpeculaAdhoc14MC1Test-output.txt" "$LOGDIR/output-$M.txt" 2>/dev/null
  cp "$REP/org.apache.hadoop.hdfs.SpeculaAdhoc14MC1Test.txt" "$LOGDIR/report-$M.txt" 2>/dev/null
  echo "== mvn exit code for $M: $RC"
  grep -E "Tests run:|BUILD (SUCCESS|FAILURE)" "$LOG" | tail -3
  echo "== evidence ($M):"
  grep -h "MC1| " "$LOGDIR/output-$M.txt" 2>/dev/null | sed 's/^.*MC1| /MC1| /'
  [ $RC -ne 0 ] && RC_ALL=$RC
done
exit $RC_ALL
