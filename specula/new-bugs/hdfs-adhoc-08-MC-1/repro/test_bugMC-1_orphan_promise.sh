#!/usr/bin/env bash
# Specula MC-1 reproduction driver (target hdfs-adhoc-08: Journal.checkRequest, Journal.java:487).
#
# Runs repro/test_bugMC-1_orphan_promise.java (a variant of
# TestQuorumJournalManager#testSingleWriter) against the PRISTINE tree at base_commit 734dd8a67cd:
#   1. stashes any harness instrumentation in the worktree (restored on exit),
#   2. installs the test as org.apache.hadoop.hdfs.qjournal.client.TestSpeculaMC1OrphanPromise and a
#      small helper that drives the NameNode's own JournalSet (org.apache.hadoop.hdfs.server.namenode),
#   3. test-compiles hadoop-hdfs offline and runs the test class with surefire,
#   4. prints the evidence: JN0's server-side stack frames, the consequence, the controls, and the
#      javap line table of Journal.checkRequest.
# Exit status 0 = every reproduction asserted the target throw and both controls stayed clean.
#
# Usage: test_bugMC-1_orphan_promise.sh [WORKTREE] [LOGDIR]
set -u -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${1:-/users/ZhenyuLi/Specula/runs/20261028-194804-49b4/hdfs-adhoc-08/.specula-output/confirmation/MC-1/worktree}"
LOGDIR="${2:-$HERE/MC-1-logs/run2-$(date -u +%Y%m%dT%H%M%SZ)}"
ENV_SH=/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-08/env.sh
BASE_COMMIT=734dd8a67cd6df56b59ff75aa43de57834a0d248
MOD=hadoop-hdfs-project/hadoop-hdfs
TEST_DIR=$MOD/src/test/java/org/apache/hadoop/hdfs/qjournal/client
HELPER_DIR=$MOD/src/test/java/org/apache/hadoop/hdfs/server/namenode
CLASS=TestSpeculaMC1OrphanPromise
FQCN=org.apache.hadoop.hdfs.qjournal.client.$CLASS

mkdir -p "$LOGDIR"
LOGDIR="$(cd "$LOGDIR" && pwd)"
# shellcheck disable=SC1090
source "$ENV_SH"
cd "$WT" || exit 2

# ---- 1. pristine system under test ----
[ "$(git rev-parse HEAD)" = "$BASE_COMMIT" ] || { echo "worktree not at $BASE_COMMIT"; exit 2; }
STASH="$LOGDIR/instrumentation-stash"
STASHED=0
if [ -n "$(git status --porcelain -- "$MOD/src")" ]; then
  mkdir -p "$STASH"
  git diff -- "$MOD/src" > "$STASH/instrumentation.patch"
  git ls-files --others --exclude-standard -- "$MOD/src" > "$STASH/untracked.txt"
  if [ -s "$STASH/untracked.txt" ]; then
    tar cf "$STASH/untracked.tar" -T "$STASH/untracked.txt"
    xargs rm -f < "$STASH/untracked.txt"
  fi
  git checkout -- "$MOD/src"
  STASHED=1
  echo "stashed harness instrumentation into $STASH"
fi
cleanup() {
  rm -f "$WT/$TEST_DIR/$CLASS.java" "$WT/$HELPER_DIR/SpeculaMC1JournalSetHelper.java"
  if [ "$STASHED" = 1 ]; then
    (cd "$WT" && git apply "$STASH/instrumentation.patch" &&
      { [ ! -s "$STASH/untracked.txt" ] || tar xf "$STASH/untracked.tar"; } &&
      echo "restored harness instrumentation (sources only; target/ holds the pristine build)")
  fi
}
trap cleanup EXIT
{
  echo "HEAD=$(git rev-parse HEAD)"
  echo "git status --porcelain -- $MOD/src/main (must be empty):"
  git status --porcelain -- "$MOD/src/main"
  echo "java: $(java -version 2>&1 | head -1)"
  echo "mvn:  $(mvn -v 2>/dev/null | head -1)"
} | tee "$LOGDIR/provenance.txt"
[ -z "$(git status --porcelain -- "$MOD/src/main")" ] || { echo "src/main not pristine"; exit 2; }

# ---- 2. install the test ----
cp "$HERE/test_bugMC-1_orphan_promise.java" "$TEST_DIR/$CLASS.java"
cat > "$HELPER_DIR/SpeculaMC1JournalSetHelper.java" <<'EOF'
package org.apache.hadoop.hdfs.server.namenode;

import java.io.IOException;

import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.test.GenericTestUtils;

/**
 * Specula MC-1: drives a JournalManager through the NameNode's own JournalSet, configured the way
 * FSEditLog#initJournals configures the shared QJM edits dir: required (shared edits dirs are
 * always required, FSNamesystem#getRequiredNamespaceEditsDirs) and shared.
 */
public final class SpeculaMC1JournalSetHelper {
  private static volatile String lastCause = "";

  private SpeculaMC1JournalSetHelper() {
  }

  public static void startLogSegmentAsNameNode(JournalManager sharedEdits,
      long txId) throws IOException {
    JournalSet journalSet =
        new JournalSet(DFSConfigKeys.DFS_NAMENODE_EDITS_DIR_MINIMUM_DEFAULT);
    journalSet.add(sharedEdits, true, true);
    GenericTestUtils.LogCapturer logs =
        GenericTestUtils.LogCapturer.captureLogs(JournalSet.LOG);
    try {
      journalSet.startLogSegment(txId,
          NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    } finally {
      lastCause = logs.getOutput();
      logs.stopCapturing();
    }
  }

  /** What JournalSet logged on the last call (its error line and the QuorumException). */
  public static String lastLoggedCause() {
    StringBuilder b = new StringBuilder();
    for (String l : lastCause.split("\n")) {
      if (l.contains("Error:") || l.contains("QuorumException")
          || l.contains("exceptions thrown") || l.contains("successful responses")
          || l.contains("is less than the last promised epoch")
          || l.contains("Connection refused") || l.contains("[success]")) {
        b.append("\n    ").append(l.trim());
      }
    }
    return b.toString();
  }
}
EOF

# ---- 3. build (offline, this module only) ----
echo "building ($MOD, offline) ..."
if ! timeout 30m mvn -B -o test-compile -Dmaven.javadoc.skip=true -pl "$MOD" \
    > "$LOGDIR/build.log" 2>&1; then
  echo "BUILD FAILED"; grep -E "ERROR|error:" "$LOGDIR/build.log" | head -40; exit 3
fi

# ---- 4. run (REPEAT times, default 3: the schedule is deterministic) ----
REPEAT="${REPEAT:-3}"
RC=0
for i in $(seq 1 "$REPEAT"); do
  echo "running $FQCN (run $i/$REPEAT) ..."
  timeout 20m mvn -B -o surefire:test -pl "$MOD" -Dtest="$CLASS" \
    -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
    > "$LOGDIR/run$i.log" 2>&1 || RC=1
  mkdir -p "$LOGDIR/run$i"
  cp "$MOD"/target/surefire-reports/*"$CLASS"* "$LOGDIR/run$i/" 2>/dev/null
  grep -E "Tests run:.*in org" "$LOGDIR/run$i.log"
done
OUT="$LOGDIR/run1/$FQCN-output.txt"

# ---- 5. evidence ----
javap -p -c -l -classpath "$MOD/target/classes" org.apache.hadoop.hdfs.qjournal.server.Journal \
  | awk '/private synchronized void checkRequest/{p=1} p{print} p&&/LocalVariableTable|^$/{if(n++>1)exit}' \
  > "$LOGDIR/javap-checkRequest.txt" 2>&1

echo
echo "===== surefire, per run ====="
for i in $(seq 1 "$REPEAT"); do
  echo "run $i: $(grep -E 'Tests run:.*in org' "$LOGDIR/run$i.log" | sed 's/^.INFO. //')"
  grep -o 'testcase name="[^"]*"' "$LOGDIR/run$i/TEST-$FQCN.xml" | tr '\n' ' '; echo
  grep -E "<failure|<error" "$LOGDIR/run$i/TEST-$FQCN.xml" | head -5
done
echo
echo "===== test log of run 1 ([MC-1] lines and their indented continuation) ====="
awk '/\[MC-1\]/{sub(/^.* - \[MC-1\]/,"[MC-1]"); print; c=1; next} c&&/^    /{print; next} {c=0}' "$OUT"
echo
echo "===== JN0 IPC server log (org.apache.hadoop.ipc.Server): first target throw with its stack ====="
grep -n -m1 -B1 -A6 "java.io.IOException: IPC's epoch .* is less than the last promised epoch" "$OUT" | cut -c1-260
echo
echo "===== NameNode JournalSet termination (first occurrence) ====="
N=$(grep -n -m1 "failed for required journal" "$OUT" | cut -d: -f1)
[ -n "$N" ] && sed -n "${N},$((N+6))p;" "$OUT" | cut -c1-260
grep -m1 "Exiting with status 1" "$OUT" | cut -c1-260
echo
echo "===== javap: Journal.checkRequest (guard at 486; throw statement 487-489) ====="
sed -n '1,16p' "$LOGDIR/javap-checkRequest.txt"
grep -A5 "LineNumberTable" "$LOGDIR/javap-checkRequest.txt"
echo
echo "logs: $LOGDIR"
echo "overall status (0 = reproduced in every run, controls clean): $RC"
exit $RC
