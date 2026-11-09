#!/usr/bin/env bash
# MC-1 reproduction (Level 0: public Collections API only, no failpoints,
# no state injection, no source change).
#
# Workload: minimal variant of ShardSplitTest#testDistribSearch (same module,
# same inherited cluster setup): CLUSTERPROP legacyCloud=false, then the
# SPLITSHARD collection1/shard1 of splitByUniqueKeyTest. Positive control:
# the same SPLITSHARD after legacyCloud is unset.
#
# Runs against a PRISTINE checkout of base_commit 6e6ca4a (Specula trace
# instrumentation reverted; `git status` must be clean apart from the test).
#
# PASS (bug triggered) = server log has SolrException "non legacy mode
# coreNodeName missing" with frame CoreAdminHandler.handleCreateAction
# (CoreAdminHandler.java:560), and the test's assertions hold.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="${WT:-/users/ZhenyuLi/Specula/runs/20261107-215441-5b4d/solr-adhoc-k2/.specula-output/confirmation/MC-1/worktree}"
LOG="${LOG:-$HERE/MC-1.log}"
source /bulk/specula-adhoc/solr/cases/solr-adhoc-k2/env.sh

cd "$WT" || exit 2
echo "== base: $(git log --oneline -1); tracked changes: $(git status --short --untracked-files=no | wc -l)"
cp "$HERE/SpeculaMC1SplitNonLegacyTest.java" solr/core/src/test/org/apache/solr/cloud/
sed -n 560p solr/core/src/java/org/apache/solr/handler/admin/CoreAdminHandler.java

cd solr/core
timeout 50m ant -lib "$IVY_USER_DIR/lib" test \
  -Dtestcase=SpeculaMC1SplitNonLegacyTest -Dtests.method=testDistribSearch \
  -Dtests.jvms=1 -Dtests.useSecurityManager=false -Dtests.seed=${SEED:-1A2B3C4D} -Dtests.showOutput=always \
  -Divy_install_path="$IVY_USER_DIR/lib" > "$LOG" 2>&1
RC=$?
echo "== ant exit code: $RC (log: $LOG)"

echo "== evidence"
grep -n "MC1-REPRO" "$LOG" | cut -c1-600
grep -n -m3 "non legacy mode coreNodeName missing" "$LOG" | cut -c1-400
grep -n -m3 "at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:560)" "$LOG"
grep -n -m2 "SPLITSHARD failed to create subshard leaders" "$LOG" | cut -c1-300
grep -n -m2 "OverseerCollectionProcessor.splitShard(OverseerCollectionProcessor.java:1350)" "$LOG"
grep -n -m1 "Only INACTIVE (or custom-hashed) slices can be deleted" "$LOG" | cut -c1-300
grep -n "Tests summary\|BUILD SUCCESSFUL\|BUILD FAILED\|OK \[\|FAILURE\|ERROR   " "$LOG" | tail -5

if grep -q "at org.apache.solr.handler.admin.CoreAdminHandler.handleCreateAction(CoreAdminHandler.java:560)" "$LOG" \
   && grep -q "MC1-REPRO: RESULT bug triggered" "$LOG"; then
  echo "RESULT: BUG TRIGGERED (CAH:560 SolrException on SPLITSHARD sub-shard leader CREATE)"
  exit 0
fi
echo "RESULT: bug NOT triggered"
exit 1
