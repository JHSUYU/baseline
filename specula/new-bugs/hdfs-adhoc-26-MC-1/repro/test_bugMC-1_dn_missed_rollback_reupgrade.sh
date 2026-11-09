#!/usr/bin/env bash
# Specula MC-1 reproduction driver (escalation Level 0).
#
# Installs test_bugMC-1_dn_missed_rollback_reupgrade.java into the hadoop-hdfs test
# sources as org.apache.hadoop.hdfs.SpeculaAdhocMC1DnMissedRollbackTest (a variant of
# the workload TestDFSRollback#testRollback), checks that the main sources are the
# pristine base_commit, runs the test through surefire and prints the evidence.
#
# Usage: test_bugMC-1_dn_missed_rollback_reupgrade.sh [HADOOP_WORKTREE]
set -u -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WT="${1:-$HERE/../confirmation/MC-1/worktree}"
WT="$(cd "$WT" && pwd)"
MOD=hadoop-hdfs-project/hadoop-hdfs
CLS=SpeculaAdhocMC1DnMissedRollbackTest
BASE_COMMIT=734dd8a67cd
ENV_SH=/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-26/env.sh

# shellcheck disable=SC1090
source "$ENV_SH"
cd "$WT" || exit 2

echo "== provenance"
echo "worktree   : $WT"
echo "HEAD       : $(git rev-parse HEAD)"
[[ "$(git rev-parse HEAD)" == "$BASE_COMMIT"* ]] \
  || { echo "worktree is not at base_commit $BASE_COMMIT"; exit 2; }
if git diff --quiet HEAD -- "$MOD/src/main" && [ -z "$(git status --porcelain -- "$MOD/src/main")" ]; then
  echo "main srcs  : pristine (no diff vs $BASE_COMMIT, no untracked files)"
else
  echo "main srcs  : MODIFIED -- refusing to run"; git status --short -- "$MOD/src/main"; exit 2
fi

echo "== install test variant"
cp "$HERE/test_bugMC-1_dn_missed_rollback_reupgrade.java" \
   "$MOD/src/test/java/org/apache/hadoop/hdfs/$CLS.java"

echo "== run (mvn -o test -Dtest=$CLS)"
LOG="$HERE/test_bugMC-1_dn_missed_rollback_reupgrade.mvn.log"
timeout 30m mvn -B -o test -pl "$MOD" -Dtest="$CLS" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$LOG" 2>&1
RC=$?
grep -E "Tests run:|BUILD (SUCCESS|FAILURE)|FAIL|ERROR\]" "$LOG" | grep -v "^\[INFO\] *$" | head -20
OUT="$MOD/target/surefire-reports/org.apache.hadoop.hdfs.$CLS-output.txt"
cp -f "$OUT" "$HERE/test_bugMC-1_dn_missed_rollback_reupgrade.output.txt" 2>/dev/null || true

echo "== [MC-1] step log (from $OUT)"
grep -E "^\[MC-1\]" "$OUT" | grep -vE "TARGET stack trace" | cut -c1-400

echo "== target stack trace (first log record; each throw is logged at BPSS:230 and DS:474)"
grep -m1 -B2 -A14 "Cannot rollback to a newer state" "$OUT" | cut -c1-300

echo "== bytecode line table of BlockPoolSliceStorage.doRollback (the throw statement)"
javap -c -l -p -classpath "$MOD/target/classes" \
  org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage > /tmp/mc1-bpss-javap.txt
awk '/void doRollback\(/,/LocalVariableTable/' /tmp/mc1-bpss-javap.txt \
  | grep -nE "new .*InconsistentFSStateException|invokespecial .*InconsistentFSStateException|athrow|line 6(1[89]|2[0-9])" | head -20
echo "source BPSS:618-626 at $BASE_COMMIT:"
git show "HEAD:$MOD/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java" \
  | awk 'NR>=618 && NR<=626 {printf "%d\t%s\n", NR, $0}'

echo "== exit code of mvn: $RC"
exit $RC
