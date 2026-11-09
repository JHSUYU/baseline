#!/usr/bin/env bash
# MC-3 reproduction. Usage: test_bugMC-3_metaSelfDependency.sh [method ...]
# Installs the variant test next to TestNamespaceAuditor, compiles, runs each method in its own JVM
# under an outer timeout, and reports the target frame (ClusterSchemaServiceImpl.java:111) per run.
set -uo pipefail
REPRO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(dirname "$REPRO")"
SRC="${SPECULA_SOURCE:-$OUT/confirmation/MC-3/worktree}"
LOGS="${MC3_LOGS:-$REPRO/MC-3-logs}"
CLASS=SpeculaAdhocMC3Test
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-08/env.sh
mkdir -p "$LOGS"
DEST="$SRC/hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/$CLASS.java"
# A tree without the harness (a pristine export of the pinned commit) has no SpeculaTrace class. Each
# use is on one line and only emits, so those lines are left out there.
WANT="$(mktemp)"
if [ -f "$SRC/hbase-server/src/main/java/org/apache/hadoop/hbase/SpeculaTrace.java" ]; then
  cp "$REPRO/test_bugMC-3_metaSelfDependency.java" "$WANT"
else
  grep -v SpeculaTrace "$REPRO/test_bugMC-3_metaSelfDependency.java" > "$WANT"
fi
if ! cmp -s "$WANT" "$DEST" || [ -n "${FORCE_BUILD:-}" ]; then
  cp "$WANT" "$DEST"
  (cd "$SRC" && timeout 1200 mvn -B -o -q test-compile -pl hbase-server -Denforcer.skip=true \
    -Dmaven.javadoc.skip=true) > "$LOGS/build.log" 2>&1 || { echo "BUILD FAILED"; exit 2; }
fi
METHODS=("$@")
[ ${#METHODS[@]} -eq 0 ] && METHODS=(testLevel0NoHookRace testLevel1CeOrderTakeover \
  testLevel1DefaultDispatchTakeover testLevel1FirstBootSingleMaster testControlRsGroupOff)
for m in "${METHODS[@]}"; do
  trace="$LOGS/$m.ndjson"; rm -f "$trace"
  echo "=== $m"
  start=$(date +%s)
  (cd "$SRC" && SPECULA_TRACE_FILE="$trace" timeout 1000 mvn -B -o surefire:test -pl hbase-server \
    -Dtest="$CLASS#$m" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false) \
    > "$LOGS/$m.mvn.log" 2>&1
  rc=$?
  cp "$SRC"/hbase-server/target/surefire-reports/*"$CLASS"*-output.txt "$LOGS/$m-output.txt" 2>/dev/null
  log="$LOGS/$m-output.txt"
  echo "exit=$rc wall=$(( $(date +%s) - start ))s $(grep -E 'Tests run:.*(Failures|Errors)' "$LOGS/$m.mvn.log" | tail -1)"
  echo "target frames (CSSI:111): $(grep -c 'ClusterSchemaServiceImpl.getNamespace(ClusterSchemaServiceImpl.java:111)' "$log")"
  grep -E 'MC3-(CONFIG|STEP|RESULT)' "$log" | sed -E 's/^[^ ]+ [^ ]+ //' | cut -c1-200
  frames=$(grep -c 'ClusterSchemaServiceImpl.getNamespace(ClusterSchemaServiceImpl.java:111)' "$log")
  aborted=$(grep -c 'ABORTING master .*Unhandled exception' "$log")
  if [ "$frames" -gt 0 ]; then
    n=$(grep -n 'NamespaceNotFoundException: hbase' "$log" | head -1 | cut -d: -f1)
    sed -n "$((n-6)),$((n+3))p" "$log" | cut -c1-130
  fi
  grep -E 'Failed to become active master|ABORTING master|Expected the service ClusterSchemaServiceImpl|^Caused by: .*RetriesExhausted' "$log" | head -4 | cut -c1-170
  echo "BUG TRIGGERED: $([ "$frames" -gt 0 ] && [ "$aborted" -gt 0 ] && echo yes || echo no) (target frames=$frames, master aborts=$aborted)"
done
