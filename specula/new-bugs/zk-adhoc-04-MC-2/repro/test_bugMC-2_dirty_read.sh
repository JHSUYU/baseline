#!/usr/bin/env bash
# MC-2 reproduction driver.
# Usage: test_bugMC-2_dirty_read.sh <worktree> <Class#method> <NIO|NETTY> <logfile>
# Runs a variant of ReadOnlyModeTest#testSeekForRwServer (module zookeeper-server) from
# test_bugMC-2_ReadOnlyDirtyReadMC2Test.java against the unmodified tree at eab16599.
set -u
WT=$1; TESTSEL=$2; FACTORY=$3; OUT=$4
HERE=$(cd "$(dirname "$0")" && pwd)
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-04/env.sh
cp "$HERE/test_bugMC-2_ReadOnlyDirtyReadMC2Test.java" \
   "$WT/zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyDirtyReadMC2Test.java"
EXTRA=()
XLOG=
if [ "$FACTORY" = NETTY ]; then
  # The production Netty cnxn logs the swallowed exception with its stack trace.
  EXTRA+=(-Dzookeeper.serverCnxnFactory=org.apache.zookeeper.server.NettyServerCnxnFactory)
else
  # NIO swallows the exception silently, so the JVM's own exception log records the throw site.
  TMP=$(mktemp -d); mkdir -p "$TMP/bin"; WRAP=$TMP/bin/java; XLOG=$TMP/exceptions.log
  printf '#!/bin/sh\nexec "%s/bin/java" "-Xlog:exceptions=info:file=%s:uptime,tid:filesize=0" "$@"\n' "$JAVA_HOME" "$XLOG" > "$WRAP"
  chmod +x "$WRAP"
  EXTRA+=(-Djvm="$WRAP")
fi
cd "$WT"
# A failed run must not report an earlier run's output.
rm -f "$WT"/zookeeper-server/target/surefire-reports/*ReadOnlyDirtyReadMC2Test*
timeout 8m mvn -B -o test -pl zookeeper-server "-Dtest=$TESTSEL" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false -Dcheckstyle.skip=true -Dspotbugs.skip=true "${EXTRA[@]}" > "$OUT" 2>&1
RC=$?
CLS=${TESTSEL%%#*}
SURE="$WT/zookeeper-server/target/surefire-reports/org.apache.zookeeper.test.$CLS-output.txt"
[ -f "$SURE" ] && cp "$SURE" "$OUT.server-output.txt"
if [ -n "$XLOG" ] && [ -f "$XLOG" ]; then
  grep -a 'CloseRequestException' "$XLOG" > "$OUT.jvm-exceptions.txt"; rm -f "$XLOG"
fi
grep -aE 'Tests run:.*Time elapsed|BUILD ' "$OUT"
[ -f "$OUT.server-output.txt" ] && grep -a 'MC2-REPRO' "$OUT.server-output.txt"
[ -f "$OUT.server-output.txt" ] && echo "refusal-log-lines=$(grep -ac 'client must try another server$' "$OUT.server-output.txt")"
echo "mvn exit=$RC"
exit $RC
