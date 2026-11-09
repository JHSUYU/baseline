#!/usr/bin/env bash
# MC-4 reproduction driver: installs the JUnit variant next to the workload test and runs it.
# Level 0: Admin API calls plus the counterexample's master crash; no state injection, no source patch.
# The test passes only if the real restore throws QuotaExceededException with a stack frame at
# NamespaceStateManager.checkAndUpdateNamespaceRegionCount in the target statement (:130-133), and
# both controls admit the restore.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(dirname "$HERE")"
WT="${MC4_WORKTREE:-$OUT/confirmation/MC-4/worktree}"
LOG="$HERE/MC-4.log"
CLS=SpeculaAdhocMC4RebuildReplicasTest
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-21/env.sh
cp "$HERE/test_bugMC-4_rebuild_replicas.java" \
  "$WT/hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/$CLS.java"
cd "$WT" || exit 2
echo "HEAD: $(git rev-parse --short HEAD)"
sed -n '126,131p' hbase-server/src/main/java/org/apache/hadoop/hbase/namespace/NamespaceStateManager.java
timeout 25m mvn -B -o test -pl hbase-server -Dtest="$CLS" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false -Denforcer.skip=true -Dmaven.javadoc.skip=true \
  -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dspotless.check.skip=true > "$HERE/MC-4.mvn.log" 2>&1
RC=$?
OUTPUT="hbase-server/target/surefire-reports/org.apache.hadoop.hbase.namespace.$CLS-output.txt"
{
  echo "mvn exit code: $RC"
  grep -E 'Tests run:|BUILD |ERROR.*(Test|expected)' "$HERE/MC-4.mvn.log" | tail -15
  echo "--- test markers"
  [ -f "$OUTPUT" ] && grep -a 'MC4>>' "$OUTPUT"
  grep -a 'MC4>>' "$HERE/MC-4.mvn.log"
} | tee "$LOG"
[ -f "$OUTPUT" ] && cp "$OUTPUT" "$HERE/MC-4.test-output.txt"
exit $RC
