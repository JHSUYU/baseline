# HDFS-43 independent original-JUnit fault campaign

**Current status: `quality_complete` for the actor-aware V2 campaign.** Two
fresh healthy original MiniDFSCluster JUnit runs reached the exact target.
The new campaign completed 125 attempts, 84 fully applied sequences, and 80
same-file/block target reaches after the last fault. All 80 target exceptions
were the `AlreadyBeingCreatedException` expected by the original JUnit;
independent raw audit found zero errors and no new target bug. The last eight
effective trials added no production coverage or stable I/O family, so the
budget stopped at 80/max8. [Actor V2 methods and evidence](actor-v2/README.md)
include the source review, selector and actor rules, per-trial records,
timings, coverage, archive, and audit.

The 80 main trials and 128 supplementary equal-branch trials described below
are historical, graph-free coverage/I/O measurements. Their
`Client.getRpcResponse` selectors used normalized thread names and did not
record the RPC request, physical DataNode, or target block identity. None
count toward the actor-aware completed budget; the old result is preserved
in [its snapshot](actor-v2/legacy-pre-v2-result.json).

- Target: `hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp.java:117` in `FSDirTruncateOp.truncate(FSNamesystem,String,long,String,String,long,BlocksMapUpdateInfo,FSPermissionChecker)`; guard `newLength == truncateLength for a block UNDER_RECOVERY`. Exact bytecode sites: `FSDirTruncateOp.truncate#L113-IFNE`.
- Workload: unchanged Hadoop 3.4.3 `org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testTruncateTwiceTogether` (MiniDFSCluster).
- Healthy run: 1 exact branch events, 1 target exceptions.
- Equal-branch calibration: original `org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testMultipleTruncate` passed and reached the equal branch 4 times with no selected exception; this calibration is not a fault trial.
- Fault campaign: 80 trials in 2684.979 attributed JUnit seconds; 78 exact ordered injections; 49 target-retaining trials.
- Post-fault target exceptions: 49; 49 trials matched the expected truncate guard. Bug mark: `none`.
- New production coverage with target retained: 59 methods, 175 covered-branch counts, 376 probes, 384 lines.
- Post-fault target branch outcomes by exact bytecode site: `{"FSDirTruncateOp.truncate#L113-IFNE": {"false": 49, "true": 0}}`.
- Historical budget: 80 trials / 8 ordered faults; actor identity recheck pending.

- I/O family feedback was reconciled at trial 53: 67 raw thread-name families became 6 stable families after canonicalizing random thread object IDs. Exact runtime selectors and completed trials did not change; see [audit](independent/evidence/stable-io-reconciliation.json).

- Tested sequence depths: `{1: 57, 2: 10, 3: 7, 4: 6}`; target-retaining depths: `{1: 42, 2: 4, 3: 3}`; applied fault types: `{'EOFException': 39, 'IOException': 29, 'SocketTimeoutException': 52}`.

The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 records production coverage. Fault selection uses only observed RPC I/O and production coverage feedback. A FSEditLog.logSync hook is installed, but the healthy JUnit invokes the asynchronous subclass; no edit-log marker was observed or selected. No GraphChecker prewoven classes, runtime jar, region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten workload is used. Target-lost trials count toward the budget but provide no feedback.

Source review: FSDirTruncateOp.truncate compares a second requested length with the length already being truncated while the last block is UNDER_RECOVERY. Equal lengths return an idempotent result; different lengths raise AlreadyBeingCreatedException. TestFileTruncate#testTruncateTwiceTogether deliberately requests a different length and expects that exception. A new post-fault length/state pair needs replay and source review.

Evidence: [result](result.json), [trial ledger](trial-ledger.csv), [checkpoint](independent/evidence/campaign-state.json), [healthy manifest](independent/evidence/healthy/manifest.json), [equal-branch manifest](independent/evidence/equal-calibration/manifest.json), [ASM probe](independent/src/HdfsStorageProbe.java), [patcher](independent/src/PatchHdfsStorage.java).

## Supplementary equal-branch phase

The original `TestFileTruncate#testMultipleTruncate` reaches the equal-length idempotent branch four times in its healthy run and raises no selected exception. Its separate campaign completed 128 trials in 3396.968 attributed JUnit seconds: 119 exact ordered injections, 41 target-retaining trials, and 148 post-fault equal-branch checks. No target exception occurred; bug mark: `none`. This is supplementary evidence for the same HDFS-43 checklist entry.

Production coverage gained 270 methods, 613 covered-branch counts, 1494 probes, and 1653 lines. Tested depths: `{'1': 89, '2': 7, '3': 11, '4': 21}`; target-retaining depths: `{'1': 34, '2': 3, '3': 3, '4': 1}`. The last-eight novelty at trial 80 extended the budget from 80/8 to 128/10; no completed trial was rerun. At trial 104, the selection queue was rebalanced toward target-retaining depth-two and depth-three parent sequences; pre/post statistics and the stopped checkpoint are in [selection audit](independent/equal_phase/evidence/choice-rebalance-audit.json).

The main phase and supplementary phase used 6081.947 attributed JUnit seconds combined. The main phase's `elapsed_seconds` remains its own 2684.979 seconds. [Supplementary result](independent/equal_phase/equal-result.json), [per-trial ledger](independent/equal_phase/trial-ledger.csv), and [raw evidence audit](independent/equal_phase/evidence/final-raw-audit.json).
