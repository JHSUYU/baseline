#!/usr/bin/env bash
# MC-3 reproduction driver. Runs test_bugMC-3_SpeculaAdhoc04MC3Test.java (a variant of
# TestAdhocWorkload04, in its module) against a source tree at base commit 1790942bb2.
#   test_bugMC-3_master_crash_enable.sh <source tree> [method+method+...]
# The tree must have been test-compiled once. In a reactor run the four modules load from their
# target/ directories, so an uninstrumented tree really is what runs.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TREE="$(cd "$1" && pwd)"
METHODS="${2:-}"
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-04/env.sh
PKG=hbase-server/src/test/java/org/apache/hadoop/hbase/quotas
cp "$HERE/test_bugMC-3_SpeculaAdhoc04MC3Test.java" "$TREE/$PKG/SpeculaAdhoc04MC3Test.java"
SEL=SpeculaAdhoc04MC3Test
[ -n "$METHODS" ] && SEL="SpeculaAdhoc04MC3Test#$METHODS"
cd "$TREE" || exit 2
timeout 570 mvn -B -o test -pl hbase-common,hbase-client,hbase-procedure,hbase-server \
  -Denforcer.skip=true -Dcheckstyle.skip -Dtest="$SEL" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false > "$HERE/MC-3.mvn.$$.log" 2>&1
rc=$?
R=hbase-server/target/surefire-reports/org.apache.hadoop.hbase.quotas.SpeculaAdhoc04MC3Test
echo "mvn rc=$rc (124 = the outer timeout fired)"
grep -E 'Tests run:.*(Fail|Err)|BUILD (SUCCESS|FAILURE)' "$HERE/MC-3.mvn.$$.log" | tail -4
rm -f "$HERE/MC-3.mvn.$$.log"
echo "--- classpath check: where the modules loaded from"
grep -o 'name="java.class.path" value="[^"]*"' "$R"*.xml 2>/dev/null | head -1 | tr ':' '\n' \
  | grep -E '/(hbase-common|hbase-client|hbase-procedure|hbase-server)(/target/classes|-[0-9])' 
grep -oE 'name="surefire.test.class.path" value="[^"]*"' "$(ls $(dirname "$R")/TEST-*MC3Test.xml)" | tr ':' '\n' \
  | grep -E '(hbase-common|hbase-client|hbase-procedure|hbase-server)(/target/classes|-[0-9])' | sed 's/.*value="//'
echo "--- evidence"
grep -hE "MC3-EVIDENCE" "$R-output.txt" | sed 's/^\([^ ]*\) .*MC3-EVIDENCE/\1/' | cut -c1-330
exit $rc
