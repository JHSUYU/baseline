#!/usr/bin/env bash
# MC-3 reproduction runner.
#
# Copies test_bugMC-3_SpeculaAdhocMC3Test.java into the pinned worktree as a
# workload variant (org.apache.hadoop.hdfs.SpeculaAdhocMC3Test, same module
# and package as TestDFSUpgrade#testUpgrade), compiles the hadoop-hdfs module
# offline and runs the three test methods REPEAT times:
#   - testStaleRuMarkerBreaksRegularUpgradeRollback  (Level 0)
#   - testCounterexampleOrderFinalizeThenDnStop      (Level 1, CE order only)
#   - testControlDnUpAcrossRuFinalize                (negative control)
# Each bug test passes only if the DN rollback throws the target IOException
# from BlockPoolSliceStorage.doTransition (the throw statement at L421-424);
# the control passes only if the rollback succeeds.
# Exit 0 iff every run passes all three tests.
#
# Usage: [REPEAT=3] test_bugMC-3_ru_marker_rollback.sh [WORKTREE] [LOGDIR]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${1:-/users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/confirmation/MC-3/worktree}"
LOGDIR="${2:-$HERE}"
REPEAT="${REPEAT:-3}"
MOD=hadoop-hdfs-project/hadoop-hdfs
CLS=SpeculaAdhocMC3Test
DEST="$WT/$MOD/src/test/java/org/apache/hadoop/hdfs/$CLS.java"
REPORTS="$WT/$MOD/target/surefire-reports"
MVN_ARGS=(-B -o -pl "$MOD" -Dtest="$CLS" -DfailIfNoTests=false
  -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.javadoc.skip=true)

source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-24/env.sh
cd "$WT" || exit 2
echo "worktree HEAD: $(git rev-parse HEAD)"
echo "tracked-file changes in worktree (expect none):"
git status --short --untracked-files=no
cp "$HERE/test_bugMC-3_SpeculaAdhocMC3Test.java" "$DEST"
echo "dependency jars used from the local repo:"
for a in hadoop-common hadoop-hdfs-client hadoop-auth hadoop-annotations; do
  ls -l --time-style=+%F_%T "$SPECULA_CASE_M2/org/apache/hadoop/$a/3.6.0-SNAPSHOT/"*.jar 2>/dev/null \
    | awk '{print "  "$6" "$7}'
done

ok=1
for i in $(seq 1 "$REPEAT"); do
  MVNLOG="$LOGDIR/MC-3.mvn.run$i.log"
  if [ "$i" = 1 ]; then goal=test; else goal=surefire:test; fi
  rm -f "$REPORTS/"*"$CLS"*
  timeout 45m mvn "$goal" "${MVN_ARGS[@]}" >"$MVNLOG" 2>&1
  echo "=== run $i/$REPEAT: mvn $goal exit=$? (log: $MVNLOG)"
  if [ "$i" = 1 ]; then
    echo "--- target throw in the compiled class (javap -l): bytecode -> source line"
    javap -c -l -p -cp "$WT/$MOD/target/classes" \
      org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage \
      >"$LOGDIR/MC-3.javap.txt"
    python3 -I - "$LOGDIR/MC-3.javap.txt" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
i = t.index('private boolean doTransition(')
body = t[i:t.index('\n\n', i)]
code, lnt = body.split('LineNumberTable', 1)
pairs = [(int(a), int(b)) for a, b in re.findall(r'line (\d+): (\d+)', lnt)]
def line_of(bci):
    return max((p for p in pairs if p[1] <= bci), key=lambda p: p[1])[0]
for m in re.finditer(r'^\s*(\d+): (new|invokespecial|athrow)\b(.*)$', code, re.M):
    bci = int(m.group(1))
    if 421 <= line_of(bci) <= 424:
        print("  bci %d -> line %d: %s%s" % (bci, line_of(bci), m.group(2), m.group(3).split('//')[-1]))
PY
  fi
  summary=$(grep -E "Tests run: [0-9]+, Failures: [0-9]+, Errors: [0-9]+, Skipped: [0-9]+$" "$MVNLOG" | tail -1)
  echo "surefire: ${summary:-<no summary>}"
  case "$summary" in
    *"Tests run: 3, Failures: 0, Errors: 0, Skipped: 0") ;;
    *) ok=0; grep -E "<<< (FAILURE|ERROR)|expected" "$MVNLOG" | head -10 ;;
  esac
  OUT="$REPORTS/org.apache.hadoop.hdfs.$CLS-output.txt"
  if [ -f "$OUT" ]; then
    cp "$OUT" "$LOGDIR/MC-3.surefire-output.run$i.txt"
    if [ "$i" = 1 ]; then
      echo "--- [MC-3] lines (run 1), with continuation lines"
      awk '/\[MC-3\]/{f=1; print; next} /^[0-9]{4}-[0-9]{2}-[0-9]{2} /{f=0} f{print}' "$OUT"
    else
      grep -a "RESULT:" "$OUT"
    fi
  fi
  REP="$REPORTS/TEST-org.apache.hadoop.hdfs.$CLS.xml"
  [ -f "$REP" ] && cp "$REP" "$LOGDIR/MC-3.surefire-report.run$i.xml"
done
if [ "$ok" = 1 ]; then
  echo "MC-3 REPRODUCED in $REPEAT/$REPEAT runs (control clean in every run)"
  exit 0
fi
echo "MC-3: at least one run did not match (see logs above)"
exit 1
