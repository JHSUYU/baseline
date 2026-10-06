# HDFS-08 independent coverage and I/O campaign

## Target and original workload

- System: Hadoop HDFS 3.4.3.
- Released source: `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:486`.
- Function and guard: `Journal.checkRequest(RequestInfo)`, `reqInfo.getEpoch() < lastPromisedEpoch.get()`; the exact oracle is its `IOException` beginning `IPC's epoch ` after the final applied fault. This condition rejects a stale writer epoch, so an occurrence needs source review and same-selector replay before any bug claim.
- Original embedded-cluster JUnits: `org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter` and `#testChangeWritersLogsInSync`. Both use the original three-`JournalNode` `MiniJournalCluster`. The first writes/finalizes segments 1–3 and 4–4; the second creates a new QJM and recovers an unfinalized segment after a writer change.

## Independent instrumentation

`source/` contains byte-for-byte copies of the relevant Hadoop 3.4.3 release source-JAR members; `source-provenance.json` records their hashes. `system-test/OriginalHdfs08IndependentTest.java` invokes the selected unchanged original JUnit method. `system-test/build_probe.py` compiles case-local source overrides of `Journal`, the JournalNode RPC server, Hadoop IPC `Client`, `PersistentLongFile`, and `EditLogFileOutputStream`; the original JUnits and release JARs remain unmodified. `system-test/Probe.java` records the exact guard, its JournalNode, caller, journal ID, segment identity, epoch values, and ordered RPC or file I/O. JaCoCo plus `CoverageDump.java` records only HDFS production method, branch-unit, and class-probe IDs. A branch unit is a covered branch count at a source line; it does not identify the branch outcome.

The single-writer healthy instrumented JUnit passed in 9.043 seconds. It reached the selected guard on `jn2` for segment 1–3 and again for segment 4–4, both with request and promised epoch 1 and normal outcomes. Its trace contains 54 mapped RPC response, epoch-file write, and edit-log flush I/O points; none has an unknown node. Production coverage is 1,202 methods, 1,072 branch units, and 3,991 probes.

After 17 single-writer trials, the campaign preserved that checkpoint and moved the remaining case budget to the unchanged original `TestQuorumJournalManager#testChangeWritersLogsInSync` JUnit. It creates a second `QuorumJournalManager` and recovers the first writer's unfinalized segment. The original multi-writer JUnit passed in 6.884 seconds and the independently instrumented run passed in 10.512 seconds. The exact `jn2` finalization guard for segment 1–3 was reached with request and promised epoch 2. The healthy multi-writer trace has 54 mapped RPC/file I/O points, zero unknown nodes, and production coverage of 1,426 methods, 1,344 branch units, and 4,757 probes. The earlier 64 GraphChecker-prewoven HDFS-08 trials are preserved separately in `../legacy-graph-result.json` and are not counted as independent trials. No GraphChecker graph, static slice, closure, skeleton, prewoven artifact, or Docker cluster is read by either independent stage.

## Fault campaign and evidence

Each ordered selector identifies `(marker, API, node, ordinal, exception type)`. A trial counts as strict only when all requested selectors match and apply in order. The campaign also requires the same `jn2` finalization segment's exact guard after the final applied fault; another segment's guard cannot substitute for it. Trials losing that guard are recorded and do not seed mutation. The exact oracle is recorded separately from JUnit exit status and from an injected exception. A target exception is only a candidate until the same selector reproduces it and released source review supports a correctness failure.

The combined budget is 80 trials with at most eight ordered faults: 17 completed single-writer trials and a 63-trial multi-writer stage. If the final eight multi-writer trials discover a new HDFS production method or branch unit, or a stable I/O family, the same multi-writer checkpoint extends the case to 128 total trials and ten faults. `campaign/checkpoint.json` preserves the single-writer completed rows, remaining queue, and `stage-pause.json`; `campaign-multiwriter/checkpoint.json` contains the independent multi-writer queue and results. Each `trial-XX/` holds the exact plan, manifest, runtime trace, production coverage, result, and elapsed time. `combined-trial-ledger.csv` records all completed independent trials in order, including the stage and global trial number. The 17 completed single-writer trials were not repeated.

After nine completed multi-writer trials, the selector score added preference for I/O families and fault types not yet tried at the last fault, with a cap on inherited coverage priority. This kept repeated writes to the same epoch file from consuming the remaining budget; `campaign-multiwriter/scheduler-change.json` records the exact rule and boundary. Trial 10 had already been selected and its remote JUnit completed during the change; its existing manifest and trace were reused on resume. No completed JUnit was rerun.

Source review of `Journal.acceptRecovery` found its released `JournalFaultInjector` hooks immediately before and after `persistPaxosData`, the atomic recovery metadata write. After multi-writer trial 37, the case-only wrapper installed a Probe callback at those existing hooks; no production class or original JUnit method changed. A new healthy run passed in 9.493 seconds, observed six mapped Paxos-file I/O points (before/after on each JournalNode), and reached the same `jn2` epoch-2 finalization guard. Its 7,523 production coverage IDs are a subset of the earlier healthy run's 7,527 IDs, and the five production override class hashes match byte-for-byte. `campaign-multiwriter/recorder-migration.json` records these comparisons and the exact boundary. The six new healthy I/O selectors were added to the existing checkpoint for trial 38 onward; the first 37 multi-writer trials were not repeated. This added healthy run is included in the case-level elapsed time.

Resume the multi-writer stage with `HDFS08_STAGE=multiwriter python3 -u .study-repairs/unit-test-pivot/cases/HDFS-08/independent-coverage-io/campaign/run_campaign.py` from `/users/ZhenyuLi/baseline`. The sustained run uses tmux session `hdfs08-independent-multiwriter-63` on node0 and executes each isolated JUnit on node1. A completed trial is not run again; an interrupted current trial with a remote manifest reuses its existing execution.

The independently measured healthy manifests, traces, and coverage are under `healthy/`. The case-level `../result.json` is updated atomically after each completed trial with per-stage and combined strict injection, retained target, exact oracle, bug mark, production coverage gain, and total elapsed time. Since the healthy methods exercise different code, the combined coverage gain removes IDs already covered by either healthy run.

## Completed result

The combined 80-trial budget completed with 17 single-writer and 63 multi-writer trials. All 80 per-trial plans, manifests, traces, coverage files, results, checkpoint rows, and combined ledger entries passed the independent checks in `audit.json`. The per-trial coverage TSVs are also stored compactly in `coverage-evidence.tar.gz`; `campaign/audit_case.py` reads them from the archive when raw TSVs are absent. The final eight multi-writer trials added no new production method, branch unit, or stable I/O family, so the conditional 128-trial extension did not apply. The untested queue remains in its checkpoint for an explicitly larger future budget.

| Measure | Result |
| --- | ---: |
| Requested / matched / applied fault events | 201 / 198 / 198 |
| Strict trials | 77 |
| Strict trials retaining the same `jn2` segment guard after the last fault | 69 |
| Target lost after strict injection / incomplete injection | 8 / 3 |
| Multi-fault trials; maximum requested sequence depth | 66; 5 faults |
| New HDFS production methods / branch units / class probes | 17 / 35 / 109 |
| Exact target exceptions after fault; any-context target exceptions | 0; 0 |
| Confirmed new bugs | 0 |
| Sum of measured healthy and fault-trial active time | 1,469.479 seconds |

The injected `last-writer-epoch` file-write error in multi-writer trial 46 reached previously unseen `Journal.syncLog`, `JNStorage.getSyncLogTemporaryFile`, and `TransferFsImage` HTTP recovery code while retaining the selected guard. Fifteen original JUnit runs exited nonzero under injected I/O errors; they were recorded as workload outcomes and did not satisfy the exact target oracle. The total elapsed time excludes pauses between tmux sessions; the interrupted and resumed multi-writer trial 10 records at least its completed JUnit time and may undercount setup by several seconds.
