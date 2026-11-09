#!/usr/bin/env bash
# MC-1 reproduction runner (hdfs-adhoc-07, target Journal.java:926 AssertionError).
#
# Installs repro/test_bugMC-1_purge_restart.java as TestBugMC1PurgeRestart in the hadoop-hdfs test tree of the
# pinned worktree (base commit 734dd8a67cd, no other local changes), compiles offline and runs it with surefire.
#
#   bash repro/test_bugMC-1_purge_restart.sh            # build, then run once per JVM mode
#   RUNS=5 bash repro/test_bugMC-1_purge_restart.sh     # 5 runs per mode
#
# Modes: "ea" = surefire default (java -ea); "da" = -DenableAssertions=false, i.e. assertions off as in a
# production JournalNode/NameNode JVM. The target AssertionError (Journal.java:926) is an explicit throw and must
# fire in both; only "da" lets the new writer finish recovery, so only "da" shows the lost committed txn.
#
# Exit 0 = in every run both bug tests reproduced (they assert the buggy outcome) and the control kept txn 2.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WT="${MC1_WORKTREE:-/users/ZhenyuLi/Specula/runs/20261028-202514-8167/hdfs-adhoc-07/.specula-output/confirmation/MC-1/worktree}"
ENV_SH="${HADOOP_ENV:-/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-07/env.sh}"
LOGDIR="${MC1_LOGDIR:-/users/ZhenyuLi/Specula/runs/20261028-202514-8167/hdfs-adhoc-07/.specula-output/confirmation/MC-1/logs}"
RUNS="${RUNS:-1}"
MODULE=hadoop-hdfs-project/hadoop-hdfs
CLS=TestBugMC1PurgeRestart
FQCN=org.apache.hadoop.hdfs.qjournal.client.$CLS
DEST="$WT/$MODULE/src/test/java/org/apache/hadoop/hdfs/qjournal/client/$CLS.java"

# shellcheck disable=SC1090
source "$ENV_SH"
mkdir -p "$LOGDIR"
cd "$WT" || exit 2

echo "[runner] tree $(git rev-parse --short HEAD); tracked-file changes vs base commit:"
git status --short --untracked-files=no | sed 's/^/[runner]   /'
echo "[runner] (none listed = pristine sources)"
cmp -s "$HERE/test_bugMC-1_purge_restart.java" "$DEST" || cp "$HERE/test_bugMC-1_purge_restart.java" "$DEST"

echo "[runner] offline test-compile of $MODULE"
if ! timeout 1800 mvn -B -o test-compile -pl "$MODULE" -Dmaven.javadoc.skip=true \
    > "$LOGDIR/build.log" 2>&1; then
  echo "[runner] BUILD FAILED"; tail -60 "$LOGDIR/build.log"; exit 2
fi

# Bytecode line table of Journal.acceptRecovery around the target throw (source lines 924-934).
javap -c -l -p -classpath "$WT/$MODULE/target/classes" \
    org.apache.hadoop.hdfs.qjournal.server.Journal > "$LOGDIR/Journal.javap.txt" 2>&1
python3 -I - "$LOGDIR/Journal.javap.txt" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r"public synchronized void acceptRecovery\(.*?\n(.*?)\n\n", text, re.S)
body = m.group(1) if m else ""
lt = re.search(r"LineNumberTable:\n((?:\s+line \d+: \d+\n)+)", body + "\n")
rows = [tuple(map(int, r)) for r in re.findall(r"line (\d+): (\d+)", lt.group(1))] if lt else []
code = dict((int(pc), ins) for pc, ins in re.findall(r"^\s+(\d+): (.*)$", body, re.M))
for line, pc in rows:
    if 924 <= line <= 934:
        print(f"[javap] Journal.acceptRecovery source line {line} starts at bytecode pc {pc}: {code.get(pc, '')}")
for pc, ins in sorted(code.items()):
    if "java/lang/AssertionError" in ins or ins.strip() == "athrow":
        eff = max((r for r in rows if r[1] <= pc), key=lambda r: r[1], default=None)
        print(f"[javap]   pc {pc}: {ins.strip()}   -> reported as source line {eff[0] if eff else '?'}")
PY

fail=0
for mode in ${MODES:-ea da}; do
  extra=()
  [[ "$mode" == da ]] && extra=(-DenableAssertions=false)
  for i in $(seq 1 "$RUNS"); do
    tag="$mode-run$i"
    echo "[runner] $tag: mvn -B -o surefire:test -pl $MODULE -Dtest=$CLS ${extra[*]:-}"
    timeout 900 mvn -B -o surefire:test -pl "$MODULE" -Dtest="$CLS" -DfailIfNoTests=false \
        -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.test.failure.ignore=false "${extra[@]}" \
        > "$LOGDIR/test-$tag.log" 2>&1
    rc=$?
    out="$WT/$MODULE/target/surefire-reports/$FQCN-output.txt"
    rm -f "$LOGDIR/test-$tag-output.txt"
    [[ -f "$out" ]] && cp "$out" "$LOGDIR/test-$tag-output.txt"
    grep -E "^\[(INFO|ERROR)\] Tests run:.*$CLS" "$LOGDIR/test-$tag.log" | sed 's/^/[runner]   /'
    if [[ $rc -eq 124 ]]; then
      echo "[runner] $tag: TIMEOUT"; fail=1
    elif grep -q "Tests run: 3, Failures: 0, Errors: 0, Skipped: 0" "$LOGDIR/test-$tag.log"; then
      echo "[runner] $tag: PASS (bug reproduced)"
    else
      echo "[runner] $tag: FAIL (mvn rc=$rc)"; fail=1
      sed -n '/<<< FAILURE\|<<< ERROR/,+25p' "$LOGDIR/test-$tag.log" | head -60
    fi
    if [[ $i -eq 1 && -f "$LOGDIR/test-$tag-output.txt" ]]; then
      grep "^\[MC-1\]" "$LOGDIR/test-$tag-output.txt"
    fi
  done
done
exit $fail
