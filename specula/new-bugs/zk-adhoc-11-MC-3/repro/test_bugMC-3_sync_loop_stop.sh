#!/usr/bin/env bash
# MC-3 reproduction driver. Usage: test_bugMC-3_sync_loop_stop.sh <source-tree> <method> [log]
# Copies the test into the tree's quorum test package and runs one method through surefire.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
TREE="$1"; METHOD="$2"; OUT="${3:-$HERE/MC-3.$METHOD.log}"
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-11/env.sh
cp "$HERE/test_bugMC-3_SpeculaAdhocMC3Test.java" \
   "$TREE/zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/SpeculaAdhocMC3Test.java"
cd "$TREE"
timeout 15m mvn -B -o test -pl zookeeper-server \
    -Dtest="SpeculaAdhocMC3Test#$METHOD" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
    -Dcheckstyle.skip=true -Dmaven.javadoc.skip=true -Dspotbugs.skip=true > "$OUT.mvn" 2>&1
RC=$?
R=zookeeper-server/target/surefire-reports/org.apache.zookeeper.server.quorum.SpeculaAdhocMC3Test-output.txt
{
  echo "tree=$TREE head=$(git -C "$TREE" rev-parse --short HEAD 2>/dev/null || echo exported) method=$METHOD mvn_rc=$RC"
  grep -E 'Tests run:|BUILD |ERROR.*(SpeculaAdhoc|COMPIL)' "$OUT.mvn" | head -20
  [ -f "$R" ] && grep -E 'MC3\| ' "$R"
} | tee "$OUT"
[ -f "$R" ] && cp "$R" "$OUT.server-output.txt"
exit $RC
