# Baselines for GraphChecker's ad hoc coordination checks

Two baselines, each reproducing a paper's approach on the same systems GraphChecker checks:

| directory | approach | what it is |
| --- | --- | --- |
| [`crashfuzz/`](crashfuzz/README.md) | CrashFuzz | coverage-guided fault injection into a system's own cluster JUnit tests, Soot-selected I/O sites, the target check as oracle |
| [`mallory/`](mallory/README.md) | Mallory | greybox fuzzing guided by changes in the run's causal graph: GraphChecker's graph of every native run, Q-learning over injected faults |

Each directory holds its code, its per-system setup, how to run it on the liftlab cluster (lift02-14, the cluster
GraphChecker's results come from), and its results; the first results were made on CloudLab and are kept below.
Neither baseline changes a system's source:

- CrashFuzz runs the Apache releases and their unchanged tests (`crashfuzz/scripts/setup-deps.sh` fetches and
  verifies them); its per-system code is one runner per system under `crashfuzz/crashfuzz/runners/`. For the old
  bugs it runs on a built source tree instead (tree mode, `crashfuzz/README.md`), with a neutral stand-in for the
  GraphChecker classes a tree's adapter calls.
- Mallory runs on GraphChecker (`git@github.com:JHSUYU/GraphChecker.git`, `system/<system>-buggy-detect`, the
  liftlab branches) with the patches in `mallory/graphchecker/<system>/` (`apply.sh` applies them). The system trees
  it runs against are pinned by each fork's `baseline/mallory` branch (`JHSUYU/hadoop`, `JHSUYU/hbase`, `JHSUYU/solr`,
  `JHSUYU/zookeeper`) for the baseline bugs, and by its `graphchecker/<system>-bug-<jira>` branches for the old bugs.

## Results on liftlab (2026-10-29/30)

Both baselines were run again on liftlab, the cluster GraphChecker's results now come from. Each baseline's README has
the protocol, every figure, the evidence and how to reproduce it from a fresh clone.

### The baseline bugs

The bugs below are each run on their system's own unit test, unchanged. Each pipeline was run twice from nothing, alone
on a node. The time is wall clock to the first detection, followed by the replays of the detecting plan (k/10).
"aid" is the broadened replay each baseline offers where its exact plan races: Mallory's `--generalize`, CrashFuzz's
siblings.

| bug | Mallory a | Mallory b | CrashFuzz a | CrashFuzz b | CloudLab: Mallory / CrashFuzz |
| --- | --- | --- | --- | --- | --- |
| SOLR-40 | 2201 s, replay 10/10 | 2083 s, replay 9/10 | 1595 s, replay 4/10 (aid 8/10) | 5749 s, replay 1/10 | 1909, 1819 s / 2719, 1999 s |
| HBase backup lock | 620 s, replay 3/10 (aid 10/10) | 656 s, replay 3/10 (aid 10/10) | 760 s, replay 10/10 | 946 s, replay 10/10 | 478, 464 s / 1182, 783 s |
| ZooKeeper election recipe | not detected (every point tried) | not detected (every point tried) | not detected (a false positive at trial 1326: the JUnit passes, replay 0/10) | not detected (1383 trials) | 504, 637 s / not detected |
| HDFS-17967 | not detected (4 h) | not detected (4 h) | not detected (454 trials, 4 h) | not detected (445 trials, 4 h) | not detected / not detected |

Notes on the runs:
- **What reproduced:** both baselines detect SOLR-40 and the HBase lock on liftlab again, with the bugs' symptoms.
- **Why the replays race:**
  - SOLR-40: which node gets the next update is the system's own randomness (an unseeded shuffle).
  - The HBase lock: which of the test's two sessions commits its compare-and-set first.
- **ZooKeeper:**
  - Mallory: on liftlab two of three fault-free runs already fail the recipe's check once, so its oracle asks for more.
  - CrashFuzz: its one oracle candidate passes the JUnit, so it is no detection.
- **Defects found on the way, both fixed in general form:**
  - Mallory: an NFS lookup cache hid about half of the driver's trial traces. The runs above are all after the fix.
  - CrashFuzz: fault identities named per-run ids (ZooKeeper session ids, unnamed-thread numbers).

### The old bugs

The old bugs GraphChecker's buggy-detect branches put back by hand on today's trees
(`docs/handover/BUGGY-DETECT.md` on GraphChecker's `system/<system>-buggy-detect`): 16, of which 14 are runnable.
HBASE-28533 has no workload (its throw is unreachable on today's code), and SOLR-6763 has no tree.

Both baselines ran each once:
- on the bug's tree (`graphchecker/<system>-bug-<jira>` in each system's fork; the Apache releases carry the fixes);
- with the workload GraphChecker detected the bug with: the case's test, mostly a bug-shaped `TestCausynth*` test,
  which both baselines exclude for the bugs above and which is used here so that the three tools see one input;
- with the oracle at the point's own declared throw;
- for 4 hours.

GraphChecker's column is its round E1 (each case alone, to the first confirmed witness).

| bug | GraphChecker | Mallory | CrashFuzz |
| --- | --- | --- | --- |
| HDFS-11741 | 1123 s | 572 s, 10/10 * | 164 s, 10/10 * |
| HDFS-17383 | 530 s | 790 s, 10/10 | not detected |
| HDFS-12931 | 400 s | 205 s, 10/10 | not detected |
| HDFS-5766 | 391 s | 242 s, 10/10 | not detected |
| HDFS-10609 | 556 s | 565 s, 10/10 | not detected (stopped at 833 trials, 13714 JUnit s) |
| HDFS-14075 | 490 s | 308 s, 10/10 | not detected |
| HDFS-14311 | not detected | not detected | not detected |
| HBASE-15039 | 850 s | 394 s, 10/10 | not detected |
| HBASE-20642 | 1504 s | 3889 s, 10/10 | 2669 s, 2/10 (by shape 9/10) |
| ZOOKEEPER-710 | 311 s | not detected (every point tried) | not detected |
| ZOOKEEPER-2886 | 300 s | not detected (every point tried) | a candidate that replays 0/10: not detected |
| SOLR-9440 | 576 s | 1497 s, 10/10 * | 1608 s, 10/10 * |
| SOLR-6101 | 632 s | not detected | not detected |
| SOLR-6197 | 539 s | not detected | not detected |
| **detected** | **13** | **9** | **3** |

\* The point's own throw, reached by other faults than the bug's mechanism:
- HDFS-11741: a lost key-update heartbeat, not the Balancer's expired cached key. The bug's fix would not prevent it.
- SOLR-9440: a lost Overseer state write (Mallory also fails a ZooKeeper read before it), not GraphChecker's witness,
  a session expiry on node1's leader-election create. Whether the view the guard reads is the bug's frozen one was not
  checked.

The bugs neither baseline detects need what a fault injector does not make:
- a request paired with a session's move to another server (ZOOKEEPER-710, -2886);
- a cluster-wide configuration change (SOLR-6101, -6197);
- a state re-pairing that GraphChecker misses too (HDFS-14311).

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

