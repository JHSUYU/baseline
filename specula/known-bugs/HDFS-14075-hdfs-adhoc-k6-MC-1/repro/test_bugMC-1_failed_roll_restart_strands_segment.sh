#!/usr/bin/env bash
# MC-1 reproduction runner (Level 0). Copies the JUnit variant of
# TestEditLogRace into the pristine (base_commit c37cda11, instrumentation
# stashed) worktree and runs it for both parameters ([0] sync, [1] async).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${WT:-/users/ZhenyuLi/Specula/runs/20261107-165603-d4a1/hdfs-adhoc-k6/.specula-output/confirmation/MC-1/worktree}"
source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-k6/env.sh
PKG=hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode
cp "$HERE/SpeculaAdhocMC1JournalStartFailureTest.java" "$WT/$PKG/"
cd "$WT"
# Guard: target check must sit at the pristine line 1409.
sed -n 1409p hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSEditLog.java | grep -q 'Preconditions.checkState(isSegmentOpen()'
timeout 40m mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs \
  -Dtest='SpeculaAdhocMC1JournalStartFailureTest' \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
  -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Denforcer.skip=true
OUT=hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/org.apache.hadoop.hdfs.server.namenode.SpeculaAdhocMC1JournalStartFailureTest-output.txt
grep -E '^MC1:|Rolling edit logs|Ending log segment|Unable to (start|finalize)|failed for too many journals|Disabling journal' "$OUT" || true
