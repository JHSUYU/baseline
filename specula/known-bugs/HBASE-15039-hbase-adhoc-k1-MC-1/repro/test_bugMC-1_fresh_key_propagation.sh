#!/usr/bin/env bash
# Specula MC-1 (hbase-adhoc-k1): a freshly rolled token key is used before a follower learns it.
# Builds the PRISTINE hbase-client + hbase-server (base_commit 92aa67fd15, no Specula trace
# instrumentation) in a reactor (no install, so the shared local repo is untouched) and runs
# SpeculaAdhocMC1Test, a two-server variant of TestTokenAuthentication#testTokenAuthentication.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${WT:-/users/ZhenyuLi/Specula/runs/20261107-165549-2572/hbase-adhoc-k1/.specula-output/confirmation/MC-1/worktree}"
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-k1/env.sh
cd "$WT"
# main sources must be pristine: target line ATSM:147 must be the real throw site
git diff --quiet HEAD -- hbase-server/src/main hbase-client/src/main || { echo "main sources modified"; exit 2; }
sed -n 146,148p hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java
cp "$HERE/test_bugMC-1_SpeculaAdhocMC1Test.java" \
   hbase-server/src/test/java/org/apache/hadoop/hbase/security/token/SpeculaAdhocMC1Test.java
timeout 40m mvn -B -o test -pl hbase-client,hbase-server \
  -Dtest="${MC1_TEST:-SpeculaAdhocMC1Test}" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
  -Dmaven.javadoc.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true -Dfindbugs.skip=true \
  -Drat.skip=true -DredirectTestOutputToFile=false ${MC1_ARGLINE:+"-DargLine=$MC1_ARGLINE"} 2>&1 | tee "$HERE/MC-1.mvn.log" | grep -E "\[MC1\]|Tests run|BUILD|ERROR|FAIL" || true
OUT="$WT/hbase-server/target/surefire-reports/org.apache.hadoop.hbase.security.token.SpeculaAdhocMC1Test-output.txt"
[ -f "$OUT" ] && cp "$OUT" "$HERE/MC-1.${MC1_TAG:-run}.surefire-output.txt" && grep -a "\[MC1\]" "$OUT" | grep -av "at sun\.reflect\|at java\.lang\.reflect\|at org\.junit" || true
