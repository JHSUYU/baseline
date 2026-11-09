#!/usr/bin/env bash
# Specula CR-3 reproduction runner (Level 0, black-box).
# Copies the TestCloudRecovery variant SpeculaCR3FrozenViewTest.java into solr/core tests
# of the CR-3 worktree (pinned at base_commit 1eaa00b; observe-only tracing inert since
# -Dspecula.trace.file is not set) and runs it with the target's test_command.
set -u
OUT=/users/ZhenyuLi/Specula/runs/20261107-215448-46f0/solr-adhoc-k1/.specula-output
WT=${WT:-$OUT/confirmation/CR-3/worktree}
LOG=${LOG:-$OUT/repro/CR-3_L0_$(date +%Y%m%d-%H%M%S).log}
source /bulk/specula-adhoc/solr/cases/solr-adhoc-k1/env.sh
cp "$OUT/repro/SpeculaCR3FrozenViewTest.java" "$WT/solr/core/src/test/org/apache/solr/cloud/"
cd "$WT/solr/core"
timeout 20m ant -lib "$IVY_USER_DIR/lib" test -Dtestcase=SpeculaCR3FrozenViewTest \
  -Dtests.method=frozenViewAfterLastWatcherRemoved -Dtests.jvms=1 -Dtests.useSecurityManager=false \
  -Divy_install_path="$IVY_USER_DIR/lib" ${EXTRA:-} > "$LOG" 2>&1
rc=$?
echo "ant exit=$rc  log=$LOG"
grep -ah "CR3:" "$LOG" "$WT/solr/build/solr-core/test/temp/"junit4-J0-*.events 2>/dev/null | sed 's/^.*\(CR3:\)/\1/' | awk '!seen[$0]++'
grep -aE "BUILD (SUCCESSFUL|FAILED)|Tests summary" "$LOG"
exit $rc
