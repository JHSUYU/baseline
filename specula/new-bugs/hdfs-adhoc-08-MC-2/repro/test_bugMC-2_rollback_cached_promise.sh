#!/usr/bin/env bash
# Specula MC-2 reproduction runner (target hdfs-adhoc-08: Journal.checkRequest, Journal.java:487).
#
#   bash repro/test_bugMC-2_rollback_cached_promise.sh [--fix-control] [--repeat N]
#        [--only METHOD[+METHOD...]] [--l0-iters N] [--no-build]
#
# 1. Puts the hadoop-hdfs sources of the pinned tree (734dd8a67cd) back to pristine. The harness
#    trace instrumentation is set aside; it is byte-identical to the copy in
#    confirmation/MC-2/repro-work/saved-instrumentation and is restored on exit.
# 2. Installs repro/test_bugMC-2_rollback_cached_promise.java as
#    org.apache.hadoop.hdfs.qjournal.client.TestBugMC2RollbackCachedPromise, in module hadoop-hdfs
#    and the same package as the workload TestQuorumJournalManager.
# 3. With --fix-control only, adds `refreshCachedData();` at the end of Journal.doRollback.
#    The bug runs never modify the code under test.
# 4. Builds the module offline (mvn -o test-compile) and runs the class with surefire.
#    Bug runs set MC2_EXPECT=bug; fix-control runs set MC2_EXPECT=fixed.
# 5. Prints the MC2 lines, the JN-side frame of the target throw, and the javap line table of
#    Journal.checkRequest.
set -u -o pipefail

OUT=/users/ZhenyuLi/Specula/runs/20261028-194804-49b4/hdfs-adhoc-08/.specula-output
WORK=$OUT/confirmation/MC-2
TREE=$WORK/worktree
MOD=hadoop-hdfs-project/hadoop-hdfs
SAVE=$WORK/repro-work/saved-instrumentation
TEST_SRC=$OUT/repro/test_bugMC-2_rollback_cached_promise.java
TEST_REL=$MOD/src/test/java/org/apache/hadoop/hdfs/qjournal/client/TestBugMC2RollbackCachedPromise.java
JOURNAL_REL=$MOD/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java
CLS=org.apache.hadoop.hdfs.qjournal.client.TestBugMC2RollbackCachedPromise
LOGDIR=${MC2_LOGDIR:-$WORK/repro-work/turn2}
ENV_SH=/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-08/env.sh

FIX=0; REPEAT=1; ONLY=""; BUILD=1; L0_ITERS=20
while [ $# -gt 0 ]; do
  case "$1" in
    --fix-control) FIX=1 ;;
    --repeat) REPEAT=$2; shift ;;
    --only) ONLY=$2; shift ;;
    --l0-iters) L0_ITERS=$2; shift ;;
    --no-build) BUILD=0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
MODE=bug; [ "$FIX" = 1 ] && MODE=fixed

log() { echo "[runner] $*"; }
mkdir -p "$LOGDIR"
# shellcheck disable=SC1090
source "$ENV_SH"
cd "$TREE" || exit 2

REMOVED=0
restore() {
  cd "$TREE" || return
  rm -f "$TEST_REL"
  git checkout -q HEAD -- "$JOURNAL_REL"
  if [ "$REMOVED" = 1 ]; then
    while read -r f; do [ -n "$f" ] && cp -p "$SAVE/$f" "$f"; done < "$SAVE/modified.txt"
    while read -r f; do [ -n "$f" ] && cp -p "$SAVE/$f" "$f"; done < "$SAVE/untracked.txt"
    log "harness instrumentation restored from $SAVE"
  fi
}
trap restore EXIT
trap 'exit 143' TERM INT HUP

# ---- 1. pristine sources ---------------------------------------------------------------------
while read -r f; do
  [ -n "$f" ] || continue
  if ! git diff --quiet HEAD -- "$f"; then
    if cmp -s "$f" "$SAVE/$f"; then git checkout -q HEAD -- "$f"; REMOVED=1
    else log "ERROR: $f differs from HEAD and from the saved instrumentation; not touching it"; exit 3; fi
  fi
done < "$SAVE/modified.txt"
while read -r f; do
  [ -n "$f" ] || continue
  if [ -e "$f" ]; then
    if cmp -s "$f" "$SAVE/$f"; then rm -f "$f"; REMOVED=1
    else log "ERROR: $f differs from the saved copy; not removing it"; exit 3; fi
  fi
done < "$SAVE/untracked.txt"
log "tree $(git rev-parse --short HEAD); git status of $MOD/src after setting instrumentation aside:"
git status --short -- "$MOD/src" | sed 's/^/[runner]   /'
log "pristine $JOURNAL_REL:484-494 (target) and :1189-1196 (doRollback):"
sed -n '484,494p;1189,1196p' "$JOURNAL_REL" | sed 's/^/[runner]   | /'

# ---- 2./3. test class and optional fix ---------------------------------------------------------
cp "$TEST_SRC" "$TEST_REL"
if [ "$FIX" = 1 ]; then
  sed -i '1195s/^    storage\.refreshStorage();$/    storage.refreshStorage();\n    refreshCachedData();/' "$JOURNAL_REL"
  log "FIX CONTROL applied:"
  git diff -- "$JOURNAL_REL" | sed 's/^/[runner]   /'
  grep -q '^    refreshCachedData();$' <(sed -n '1196p' "$JOURNAL_REL") || { log "ERROR: fix not applied"; exit 3; }
fi

# ---- 4. build and run --------------------------------------------------------------------------
if [ "$BUILD" = 1 ]; then
  log "building $MOD: mvn -B -o test-compile (log $LOGDIR/build-$MODE.log)"
  timeout 25m mvn -B -o test-compile -pl "$MOD" -Dmaven.javadoc.skip=true > "$LOGDIR/build-$MODE.log" 2>&1
  rc=$?
  log "build rc=$rc; $(grep -m1 'Total time' "$LOGDIR/build-$MODE.log")"
  if [ "$rc" != 0 ]; then grep -E "ERROR" "$LOGDIR/build-$MODE.log" | head -40; exit 4; fi
fi

log "javap -c -l of the compiled Journal.checkRequest (target throw = new IOException ... athrow):"
javap -c -l -p -classpath "$MOD/target/classes" org.apache.hadoop.hdfs.qjournal.server.Journal \
  | awk '/ void checkRequest\(/{on=1} on&&/^  [a-z].*\(.*\).*;$/&&!/checkRequest/{on=0} on' \
  | grep -E "checkRequest|ifge|new +#|java/io/IOException.\"<init>\"|athrow|LineNumberTable|line 48[5-9]|line 49[0-1]" \
  | head -20 | sed 's/^/[runner] /'

SEL=$CLS; [ -n "$ONLY" ] && SEL="$CLS#$ONLY"
SUMMARY=$LOGDIR/summary-$MODE.txt
: > "$SUMMARY"
for i in $(seq 1 "$REPEAT"); do
  RUNLOG=$LOGDIR/run-$MODE-$i.log
  log "run $i/$REPEAT ($MODE): MC2_EXPECT=$MODE MC2_L0_ITERS=$L0_ITERS mvn -B -o surefire:test -pl $MOD -Dtest='$SEL'"
  MC2_EXPECT=$MODE MC2_L0_ITERS=$L0_ITERS timeout 25m mvn -B -o surefire:test -pl "$MOD" \
    -Dtest="$SEL" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$RUNLOG" 2>&1
  rc=$?
  log "mvn rc=$rc"
  grep -E "Tests run:|FAILURE|BUILD|AssertionFailedError|expected:" "$RUNLOG" | head -12 | sed 's/^/[runner]   /'
  OUTF=$MOD/target/surefire-reports/$CLS-output.txt
  cp "$OUTF" "$LOGDIR/surefire-output-$MODE-$i.txt" 2>/dev/null
  cp "$MOD/target/surefire-reports/TEST-$CLS.xml" "$LOGDIR/TEST-$MODE-$i.xml" 2>/dev/null
  awk '/^MC2: /{print; n=0; m=0}
       /JN-side (stack )?trace/{n=4; next}
       /epoch RPCs as its IPC client saw them/{m=1; next}
       m && /^    [0-9]/{print; next}
       m {m=0}
       n>0{print; n--}' "$OUTF" \
    | sed 's/^/    /' | tee -a "$SUMMARY"
done

# ---- 5. verdict lines --------------------------------------------------------------------------
fired=$(grep -c "MC2-RESULT scenario=CE_STEPS_RESTART_AFTER_ROLLBACK .*targetFiredOnJ1=true" "$SUMMARY")
ran=$(grep -c "MC2-RESULT scenario=CE_STEPS_RESTART_AFTER_ROLLBACK" "$SUMMARY")
log "CE scenario (CE steps, JNRestart(j0) after the rollback): target fired on j1 in $fired of $ran runs ($MODE)"
grep -h "MC2-L0-RESULT" "$SUMMARY" | sed 's/^ */[runner] Level 0: /'
grep -h -m1 "at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:" "$SUMMARY" \
  | sed 's/^ */[runner] target frame: /'
exit 0
