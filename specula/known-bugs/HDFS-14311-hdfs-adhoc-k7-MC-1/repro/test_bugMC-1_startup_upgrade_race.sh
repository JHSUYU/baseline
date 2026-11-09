#!/usr/bin/env bash
# MC-1 reproduction runner: BlockPoolSliceStorage.java:422 IOException fired by
# the startup parallel-upgrade race (variant of TestAdhocWorkload7).
#
# Runs against the CLEAN pinned tree (base_commit b0c5a8f9, no instrumentation).
# Level 0: the workload, repeated, black-box.
# Level 1: the same workload; a JDWP debugger orders threads with breakpoints
#          (timing control only; no source change, no value / state injection).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${MC1_WORKTREE:-/users/ZhenyuLi/Specula/runs/20261107-165604-90a4/hdfs-adhoc-k7/.specula-output/confirmation/MC-1/worktree}"
source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-k7/env.sh
TESTDIR="$WT/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs"
cp "$HERE/test_bugMC-1_startup_upgrade_race.java" "$TESTDIR/TestBugMC1StartupUpgradeRace.java"
cd "$WT"
echo "== pinned tree: $(git rev-parse --short HEAD); modified tracked files:"
git status --short --untracked-files=no
PORT=$(( 40000 + RANDOM % 20000 ))
COMMON=(-B -o -pl hadoop-hdfs-project/hadoop-hdfs -DfailIfNoTests=false
  -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.javadoc.skip=true
  -Dmaven.test.additionalClasspath="$JAVA_HOME/lib/tools.jar")

echo "== Level 0 (black-box, ${MC1_L0_ROUNDS:-10} rounds)"
timeout 30m mvn "${COMMON[@]}" test \
  -Dtest='TestBugMC1StartupUpgradeRace#level0BlackBox' \
  -Dmaven-surefire-plugin.argLine="-Xmx2048m -Dmc1.level0.rounds=${MC1_L0_ROUNDS:-10}" \
  > "$HERE/test_bugMC-1_level0.mvn.log" 2>&1
echo "level0 mvn exit=$?"
grep -h "\[MC-1\]\[L0\] target fired\|Tests run:" "$HERE/test_bugMC-1_level0.mvn.log" | head -3
OUT0="$WT/hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/org.apache.hadoop.hdfs.TestBugMC1StartupUpgradeRace-output.txt"
[ -f "$OUT0" ] && cp "$OUT0" "$HERE/test_bugMC-1_level0.output.txt"

echo "== javap line table of the target statement (BPSS:422-425)"
javap -c -l -p -cp hadoop-hdfs-project/hadoop-hdfs/target/classes \
  org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage \
  | awk '/private boolean doTransition/,/LocalVariableTable/' \
  | grep -E "^ +(409|471|474): |line 42[0-6]:"

RC=0
for RUN in 1 2 3; do
PORT=$(( 40000 + RANDOM % 20000 ))
echo "== Level 1 run $RUN (JDWP thread schedule, port $PORT)"
timeout 20m mvn "${COMMON[@]}" surefire:test \
  -Dtest='TestBugMC1StartupUpgradeRace#level1DebuggerSchedule' \
  -Dmaven-surefire-plugin.argLine="-Xmx2048m -Dmc1.jdwp.port=$PORT -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=localhost:$PORT" \
  > "$HERE/test_bugMC-1_level1.run$RUN.mvn.log" 2>&1
R=$?; [ $R -ne 0 ] && RC=$R
echo "level1 run $RUN mvn exit=$R"
grep -h "Tests run:\|FAIL" "$HERE/test_bugMC-1_level1.run$RUN.mvn.log" | head -2
[ -f "$OUT0" ] && cp "$OUT0" "$HERE/test_bugMC-1_level1.run$RUN.output.txt" && \
  grep -h "^\[MC-1\]\|is newer than\|^	at org.apache.hadoop.hdfs.server.datanode" \
    "$HERE/test_bugMC-1_level1.run$RUN.output.txt" | awk '!seen[$0]++' | head -30
done
exit $RC
