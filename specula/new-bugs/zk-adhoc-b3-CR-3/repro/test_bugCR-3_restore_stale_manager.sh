#!/bin/bash
# CR-3 reproduction driver. Usage: test_bugCR-3_restore_stale_manager.sh [method] [extra mvn -D args]
# Level 0: real ZooKeeperServerMain, HTTP admin snapshot/restore, plain client. JDI watcher only observes.
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(dirname "$HERE")/confirmation/CR-3
W=$OUT/worktree
METHOD=${1:-restoreLeavesManagerOnOldTree}; shift
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-b3/env.sh
T=$W/zookeeper-server/src/test/java/org/apache/zookeeper/server/SpeculaAdhocB3RestoreCR3Test.java
cp "$HERE/test_bugCR-3_SpeculaAdhocB3RestoreCR3Test.java" "$T"
TMP=$(mktemp -d); mkdir -p "$TMP/bin"
cp "$HERE/test_bugCR-3_NoNodeWatcher.java" "$TMP/NoNodeWatcher.java"
javac -d "$TMP/w" "$TMP/NoNodeWatcher.java" || exit 3
PORT=$(( 40000 + RANDOM % 20000 ))
cat > "$TMP/bin/java" <<W
#!/bin/bash
exec $JAVA_HOME/bin/java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,quiet=y,address=127.0.0.1:$PORT "\$@"
W
chmod +x "$TMP/bin/java"
LOG=$OUT/repro-$METHOD-$(date +%s).log
java -cp "$TMP/w" NoNodeWatcher $PORT > "$TMP/watch.log" 2>&1 &
WP=$!
cd "$W" || exit 3
timeout ${CR3_TIMEOUT:-540} mvn -B -o test -pl zookeeper-server -Dtest="SpeculaAdhocB3RestoreCR3Test#$METHOD" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -Dcheckstyle.skip=true -Dspotbugs.skip=true \
  -Djvm="$TMP/bin/java" "$@" > "$TMP/mvn.log" 2>&1
RC=$?
kill $WP 2>/dev/null; wait $WP 2>/dev/null
{
  echo "### method=$METHOD mvn_exit=$RC extra=$*"
  git -C "$W" rev-parse --short HEAD
  grep -E 'Tests run:|BUILD|ERROR.*(Test|COMPIL)|Corrupted' "$TMP/mvn.log" | head -20
  echo '### test output'
  cat "$W"/zookeeper-server/target/surefire-reports/*SpeculaAdhocB3RestoreCR3Test-output.txt 2>/dev/null \
    | grep -E '\[CR3\]|Attempting to delete candidate|Restored to a new database|After restore database|Using checkIntervalMs' | cut -c1-230
  echo '### JDI watcher'
  cat "$TMP/watch.log"
} | tee "$LOG"
cp "$TMP/mvn.log" "$LOG.mvn"
echo "log: $LOG"
exit $RC
