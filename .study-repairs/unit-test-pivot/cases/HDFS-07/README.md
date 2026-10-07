# HDFS-07: endpoint-aware original-JUnit campaign complete

## Current actor-aware result

The current graph-free baseline uses the unchanged Hadoop 3.4.3
`TestQuorumJournalManager#testRecoverAfterIncompleteRecovery` in a fresh
three-JournalNode embedded cluster per run. The QJM V2 overlay maps each
`Client.getRpcResponse` connection's actual remote port to a physical
JournalNode and binds file I/O to that JournalNode's `test-journal` storage.
The target is the original `Journal.acceptRecovery` assertion at line 926.
Two original JUnit healthy seeds passed in 12.976 and 14.521 seconds with
stable actor-aware I/O and target identities. The [V2 design and runner](../../qjm-rpc-actor-v2/README.md)
document the no-graph hooks, exact ordered fault gate, JaCoCo feedback, and
resumable checkpoint.

The V2 campaign completed **220 attempted fault sequences, all fully applied;
128 also executed the same physical JournalNode/`test-journal` target after
the final fault**. The initial 80-effective/max-8/320-attempt budget extended
to 128-effective/max-10/512-attempt because effective trial 111 added Hadoop
RPC `Client.stop`/`Connection.interruptConnectingThread` production method and
branch coverage. The deepest executed sequence had three faults. There were
62 one-fault, 42 two-fault, and 24 three-fault effective sequences. The
original JUnit ran for 2757.980 seconds in aggregate; the controller's wall
time was 3058.696 seconds. The selected assertion true branch and
`AssertionError` were observed **zero** times. JUnit failures from the
injected I/O or lost quorum remain distinct observations and are not marked
as coordination bugs.

The [independent terminal audit](../../qjm-rpc-actor-v2/evidence/HDFS-07/audit-terminal-128.json)
recomputed every plan, actor/target receipt, original JUnit exit, raw trace
and JaCoCo SHA, and coverage/I/O feedback (pass; zero errors). The
[220-row ledger](qjm-v2-trial-ledger.csv) records faults, physical target
actor, exact postfault target count, time, coverage gain, and result. The
[raw archive](../../qjm-rpc-actor-v2/evidence/HDFS-07/final-raw-128.tar.gz)
contains the two healthy and 220 fault-trial manifests, traces, original JUnit
logs, plans, JaCoCo, controller checkpoint, and audit. Its SHA-256 is
`b0ac20218c450e5faa718d35af632314f96210c9c6f20d6c1b8fe486a947c2f6`.
The node1 tmux/JUnit exited naturally after the 128-effective terminal
checkpoint. No V2 trial imports the earlier 80 coarse actor trials.

## Historical coarse actor campaign

The earlier 24 fault trials used a static-analysis/region-woven recorder. Those trials are preserved in [legacy-graph-result.json](legacy-graph-result.json) and excluded from the current graph-independent campaign. The original cluster JUnit and target check must be recorded with case-local I/O/coverage probes before new trials count.

The earlier coarse actor campaign ran the unchanged Hadoop 3.4.3 three-JournalNode
`TestQuorumJournalManager#testRecoverAfterIncompleteRecovery` in a fresh
temporary directory per trial. It uses a case-local ASM overlay on the
original Hadoop classes and JaCoCo for production coverage; neither the
recorder nor the selector reads a graph, region skeleton, or GraphChecker
runtime. The two healthy runs passed in 12.155 and 11.470 seconds. The
selected condition was evaluated on journalnode-2 during the second recovery
with epoch 3, old segment [1,5], proposed segment [1,4], and committed
transaction 4. Thus the healthy second recovery shortens an incomplete
segment without discarding the committed transaction.

The recorder reports the original `Client.getRpcResponse` call, the
`Journal.acceptRecovery` Paxos file write, and its `FileUtil.replaceFile`
call. File selectors include the concrete JournalNode, journal ID, segment
start, site, and hit ordinal; RPC selectors include a stable logical thread
source, site, and ordinal. A calibration trial injected `IOException` at the
second Paxos write on journalnode-1: the fault matched exactly and the same
journalnode-2 target check still ran. The original JUnit failed because the
injected I/O error broke recovery; that failure alone is not a selected
coordination-check bug.

The earlier resumable campaign ran in tmux `hdfs07-independent`, with an 80-trial,
eight-fault initial budget. Each round records its exact ordered injections,
target identity after the final fault, target `AssertionError`, JaCoCo gain,
elapsed time, and original JUnit status under `independent/evidence/`. The
controller prioritizes newly observed recovery I/O and coverage, and mutates
sequences only after an exact injection and a subsequent execution of the
second-recovery check on journalnode-2. One interrupted calibration sequence
was left in the checkpoint's `current` field and requeued on restart; no
completed round was repeated.

After 33 completed trials, the queue selector was changed at a checkpoint to
give every third selection to the deepest available sequence, regardless of
whether its last fault is RPC or file I/O. This exercises combinations within
the eight-fault budget while the other rounds continue to sample both I/O
families. The interrupted in-flight sequence was requeued, and all 33
completed sequence IDs were preserved; see
`independent/evidence/scheduler-handoff.json`.

Coverage feedback was audited at completed trial 37. The original probe-ID
export also included original JUnit support classes; method and branch
coverage already used only released Hadoop classes. The exporter now admits
only class names present in the released HDFS, HDFS client, or common JAR.
The 37 saved per-run probe sets were filtered using those JAR indices and
the checkpoint was rebuilt in actual trial completion order from
`campaign.log`; no fault trial was rerun. This removed test-class probes from
the healthy baseline (7,437 to 7,245). The 37 valid-trial probe gains summed
to 49 before and after filtering, and every method/branch gain was unchanged.
The raw JaCoCo exec files remain available, while the compressed
`campaign-state.pre-production-coverage.json.gz` and
`coverage-migration-v3.json` record the exact handoff.

## Final result

The independent campaign finished all 80 planned trials without repeating a
completed sequence. Its [raw-event audit](independent/evidence/audit-result.json)
recomputed 80 exact ordered injections and 53 trials in which the selected
`journalnode-2` second-recovery check ran after the final fault. No trial
triggered the selected `AssertionError`; the deepest executed sequence had
three faults. Production branch coverage increased by 21 branch counters over
the healthy run. The original test writes transaction 5 to only one
JournalNode, then recovers to transaction 4. The selected assertion rejects a
shorter replacement only if it would discard an already committed
transaction. Some original-JUnit runs failed when an injected I/O exception
prevented quorum, but those failures are recorded separately from the target
assertion and are not counted as a new bug.

The [per-trial ledger](independent-trial-ledger.csv) records each sequence,
elapsed time, injection match, target outcome, coverage gain, and JUnit exit.
The [evidence archive](HDFS-07-independent-evidence.tar.gz) contains original
healthy and faulted trace/manifest/log/JaCoCo records without temporary
JournalNode scratch data; its checksum is in
[independent-archive-manifest.json](independent-archive-manifest.json).
The earlier 24 graph-based trials remain excluded.
The old graph-based execution script has been removed. The coarse actor
runner and resumable controller were `independent/run_original.py` and
`independent/campaign.py`; their historical result and raw evidence remain.
The workspace-local graph builders and closure-based trial controllers have
also been removed.
