#!/usr/bin/env bash
# Runs one mode of the MC-3 reproduction. Usage: test_bugMC-3_eviction_trunc.sh <ceOrder|ceOrderJuteMaxBuffer|afterUptodate|controlRetainedQueue|level0Stress> [source tree]
# Exit status: the surefire result of that mode.
# Optional arg 3 is a log-name suffix. For the pristine runs (logs named *_pristine*), arg 2 was an export of the pinned commit:
#   mkdir P; git -C <worktree> archive eab16599 | tar -x -C P
# Then read the MC3> lines; the mode installs BugMC3EvictionTest.java into the tree it runs on.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:?mode}"
TREE="${2:-/users/ZhenyuLi/Specula/runs/20261105-033900-36d9/zk-adhoc-b6/.specula-output/confirmation/MC-3/worktree}"
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-b6/env.sh
cp "$HERE/test_bugMC-3_eviction_trunc.java" "$TREE/zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/BugMC3EvictionTest.java"
EXTRA=""
[ "$MODE" = ceOrderJuteMaxBuffer ] && EXTRA="-Dmc3.jute=31000000"
cd "$TREE"
LOG="$HERE/MC-3_${MODE}${3:-}.log"
rm -f "$TREE"/zookeeper-server/target/surefire-reports/*BugMC3*
timeout 9m mvn -B -o test -pl zookeeper-server -Dtest="BugMC3EvictionTest#$MODE" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false -Dsurefire.redirectTestOutputToFile=false -Dcheckstyle.skip=true \
  -Dspotbugs.skip=true -Dmaven.javadoc.skip=true $EXTRA > "$LOG" 2>&1
RC=$?
OUT="$TREE/zookeeper-server/target/surefire-reports/org.apache.zookeeper.server.quorum.BugMC3EvictionTest-output.txt"
cp "$OUT" "$HERE/MC-3_${MODE}${3:-}.server.log" 2>/dev/null
grep -E 'MC3>' "$OUT" | cut -c1-300
grep -E 'Tests run:|BUILD|ERROR.*(BugMC3|Compilation|COMPILATION)' "$LOG" | cut -c1-260
echo "mvn exit status: $RC; full log: $LOG"
exit $RC
