#!/usr/bin/env bash
# MC-1 runner: checks that the tree is pristine at the pinned commit, installs the test, builds offline,
# runs the workload as written and then the variant, and prints the evidence.
#
#   bash repro/test_bugMC-1_append_after_ancestor_lazy_persist.sh [surefire -Dtest filter]
#
# WT=<tree> selects the tree (default: this finding's worktree). Output goes to repro/MC-1.log.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd -P)
OUT=$(cd "$HERE/.." && pwd -P)
WT=$(cd "${WT:-$OUT/confirmation/MC-1/worktree}" && pwd -P)
ENV_SH=${ENV_SH:-/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-38/env.sh}
BASE_COMMIT=734dd8a67cd
MOD=hadoop-hdfs-project/hadoop-hdfs
CLS=SpeculaAdhocFSDirAppendOpMC1Test
SRC="$HERE/test_bugMC-1_append_after_ancestor_lazy_persist.java"
DST="$WT/$MOD/src/test/java/org/apache/hadoop/hdfs/$CLS.java"
REPORTS="$WT/$MOD/target/surefire-reports"
TARGET_JAVA=$MOD/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java
LOG="$HERE/MC-1.log"
FILTER=${1:-$CLS}

# shellcheck disable=SC1090
source "$ENV_SH"
exec > >(tee "$LOG") 2>&1

echo "== provenance"
head=$(git -C "$WT" rev-parse HEAD)
echo "tree: $WT"
echo "HEAD: $head"
case $head in "$BASE_COMMIT"*) ;; *) echo "FAIL: not at $BASE_COMMIT"; exit 2 ;; esac
rm -f "$DST"
if [ -n "$(git -C "$WT" status --short)" ]; then
  echo "FAIL: tree is not pristine:"; git -C "$WT" status --short; exit 2
fi
echo "git status: clean"
sed -n '118,124p' "$WT/$TARGET_JAVA"

cp "$SRC" "$DST"
trap 'rm -f "$DST"' EXIT

echo "== build (offline test-compile)"
if ! (cd "$WT" && timeout 1200 mvn -B -o test-compile -pl "$MOD" -Dmaven.javadoc.skip=true) \
     > "$HERE/MC-1.build.log" 2>&1 || ! grep -q 'BUILD SUCCESS' "$HERE/MC-1.build.log"; then
  echo "FAIL: build, see $HERE/MC-1.build.log"; tail -30 "$HERE/MC-1.build.log"; exit 2
fi
echo "build: SUCCESS"
CLASSES="$WT/$MOD/target/classes"
echo "SpeculaNNTrace in FSDirAppendOp bytecode: $(javap -p -c -cp "$CLASSES" \
  org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp | grep -c SpeculaNNTrace)"
echo "SpeculaNNTrace class files: $(find "$CLASSES" -name 'Specula*' | wc -l)"

run_test() {  # run_test <-Dtest> <mvn log>
  (cd "$WT" && timeout 900 mvn -B -o surefire:test -pl "$MOD" -Dtest="$1" \
      -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false) > "$2" 2>&1
  local rc=$?
  [ "$rc" = 124 ] && echo "TIMEOUT: $1 (a fired timeout is a finding, see $2)"
  grep -E 'Tests run:|BUILD|ERROR.*(t[0-9]_|testAppendTwice)' "$2" | sed 's/^/  /'
}

echo "== control: the workload as written, on the same pristine classes"
run_test 'TestFileAppend#testAppendTwice' "$HERE/MC-1.workload.mvn.log"

echo "== variant: $FILTER"
run_test "$FILTER" "$HERE/MC-1.variant.mvn.log"

REPORT="$REPORTS/org.apache.hadoop.hdfs.$CLS-output.txt"
cp -f "$REPORT" "$HERE/MC-1.surefire-output.txt" 2>/dev/null
echo "== evidence (MC1| lines from $REPORT)"
sed -n '/MC1|/,/^[0-9]\{4\}-[0-9-]* [0-9:,]* /{/^[0-9]\{4\}-[0-9-]* [0-9:,]* /!p}' "$REPORT"

echo "== NameNode log lines"
echo "count of NameNode frames FSDirAppendOp.appendFile(FSDirAppendOp.java:122): $(grep -c 'at org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp.appendFile(FSDirAppendOp.java:122)' "$REPORT")"
grep -m1 -B2 -A3 'at org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp.appendFile(FSDirAppendOp.java:122)' "$REPORT"
grep -E 'Removing lazyPersist file' "$REPORT"

grep -q "Tests run: [0-9]*, Failures: 0, Errors: 0" "$HERE/MC-1.variant.mvn.log"
