# Baselines for GraphChecker's ad hoc coordination checks

Two baselines, each reproducing a paper's approach on the same systems GraphChecker checks:

| directory | approach | what it is |
| --- | --- | --- |
| [`crashfuzz/`](crashfuzz/README.md) | CrashFuzz | coverage-guided fault injection into a system's own cluster JUnit tests, Soot-selected I/O sites, the target check as oracle |
| [`mallory/`](mallory/README.md) | Mallory | greybox fuzzing guided by changes in the run's causal graph: GraphChecker's graph of every native run, Q-learning over injected faults |

Each directory holds its code, its per-system setup, how to run it on the CloudLab cluster, and its results.

## Results (2026-10-26, CloudLab)

Both baselines on the same bugs, each with its system's own unit test, unchanged; every figure is the whole
pipeline from nothing, run twice, wall clock to the first detection (details in each baseline's README).

| bug | unit test | Mallory | CrashFuzz |
| --- | --- | --- | --- |
| SOLR-40 (stale routed-alias cache after a ZooKeeper failure) | `TimeRoutedAliasUpdateProcessorTest#test` | 1909 s / 1819 s | 2719 s / 1999 s |
| HBase backup lock (lost compare-and-set reply) | `TestBackupManager#testStartBackupExclusiveOperation` | 478 s / 464 s | 1182 s / 783 s |
| ZooKeeper election recipe (orphaned offer) | `LeaderElectionSupportTest#testNodes3` | 504 s / 637 s | not detected (2 x ~270 trials) |
| HDFS-17967 (pipeline relay missing the block key) | `TestEncryptedTransfer#testLongLivedClientPipelineRecovery` | not detected (294 + 165 trials) | not detected (246 + 206 trials) |

### Do they transfer? Held-out checks

To check that neither baseline is fitted to these bugs, both ran with the code unchanged on three checks never
used while they were built, each on its system's own unit test, one run each (Mallory 1 hour of wall clock,
CrashFuzz 1 hour of JUnit time): Solr `DeleteReplicaCmd:278` (`DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup`;
SOLR-09 / `solr-adhoc-09`), HBase `ClusterSchemaServiceImpl.getNamespace:116`
(`TestNamespaceAuditor#testTableOperations`; HBASE-08 / `hbase-adhoc-08`) and ZooKeeper `Learner.java:525`
(`QuorumRestartTest#testRollingRestart`; ZOOKEEPER-07 / `zk-adhoc-07`). Each case is only data: a checklist row
for CrashFuzz, a GraphChecker case for Mallory.

| check | Mallory | CrashFuzz |
| --- | --- | --- |
| Solr DeleteReplicaCmd:278 | ran, 87 trials, no detection | ran, 120 trials, no candidate |
| HBase getNamespace:116 | ran, 96 trials, no detection | ran, 59 trials, no candidate |
| ZooKeeper Learner:525 | ran, all 19 fault points of the test tried, no detection | ran, 373 trials (1.5 h), no candidate |

Both ran every held-out case end to end without a code change and reported no false positive: no trial
failed any of the checks. The setup they needed was the one each documents: the ZooKeeper test's Surefire
classpath (`scripts/setup-deps.sh`) and GraphChecker's `build` of the case (`experiments/lib/run.sh <case> build`).
These checks are points the study selected, not known bugs, so no detection is the expected outcome.

