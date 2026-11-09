#!/usr/bin/env bash
# Specula repro runner for MC-1 (stale Balancer/Mover DEK).
# Builds hadoop-hdfs-client + hadoop-hdfs from a PRISTINE checkout of the
# target base_commit (595e4680154; trace instrumentation reverted) and runs the
# Level-0 variant of TestBalancerWithEncryptedTransfer.
# Usage: test_bugMC-1_stale_balancer_dek.sh [SOURCE_TREE]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${1:-/users/ZhenyuLi/Specula/runs/20261107-165520-7804/hdfs-adhoc-k1/.specula-output/confirmation/MC-1/worktree}"
source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-k1/env.sh
cd "$SRC"
echo "HEAD: $(git log --oneline -1)"; echo "modified tracked files: $(git status --short --untracked-files=no | wc -l)"
DST=hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/TestBugMC1StaleBalancerDek.java
cp "$HERE/test_bugMC-1_stale_balancer_dek.java" "$DST"
timeout 45m mvn -B -o test \
  -pl hadoop-hdfs-project/hadoop-hdfs-client,hadoop-hdfs-project/hadoop-hdfs \
  -Dtest='TestBugMC1StaleBalancerDek' -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.javadoc.skip=true \
  -Dsurefire.timeout=1200
