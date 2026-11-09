#!/usr/bin/env bash
# MC-2 reproduction runner (Level 1: timing via a MasterObserver hook + one master crash via
# MiniHBaseCluster.abortMaster). Installs the JUnit variant of the workload test into the
# finding's worktree (hbase-server, package master.procedure) and runs it with the target's
# test command. No system source is modified.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${WT:-/users/ZhenyuLi/Specula/runs/20261107-215422-94b7/hbase-adhoc-k2/.specula-output/confirmation/MC-2/worktree}"
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-k2/env.sh
DST="$WT/hbase-server/src/test/java/org/apache/hadoop/hbase/master/procedure/TestSpeculaBugMC2FailoverAddColumn.java"
cp "$HERE/test_bugMC-2_TestSpeculaBugMC2FailoverAddColumn.java" "$DST"
cd "$WT"
timeout 15m mvn -B -o -q test-compile -pl hbase-server -Dmaven.javadoc.skip=true -Denforcer.skip=true \
  -Dcheckstyle.skip=true > "$HERE/MC-2.build.log" 2>&1 || { echo "BUILD FAILED"; tail -40 "$HERE/MC-2.build.log"; exit 2; }
timeout 15m mvn -B -o surefire:test -pl hbase-server -Dtest='TestSpeculaBugMC2FailoverAddColumn' \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$HERE/MC-2.log" 2>&1
rc=$?
OUT="$WT/hbase-server/target/surefire-reports/org.apache.hadoop.hbase.master.procedure.TestSpeculaBugMC2FailoverAddColumn-output.txt"
[ -f "$OUT" ] && cp "$OUT" "$HERE/MC-2.test-output.txt"
grep -h "SPECULA-MC2 [A-Z]\|Tests run:\|HMaster.addColumn(HMaster.java\|InvalidFamilyOperationException:" \
  "$HERE/MC-2.log" "$HERE/MC-2.test-output.txt" 2>/dev/null | grep -v "^\s*$" | head -60
echo "mvn exit code: $rc"
exit $rc
