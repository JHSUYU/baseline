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

