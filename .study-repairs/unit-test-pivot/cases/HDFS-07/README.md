# HDFS-07: independent recorder replay pending

The earlier 24 fault trials used a static-analysis/region-woven recorder. Those trials are preserved in [legacy-graph-result.json](legacy-graph-result.json) and excluded from the current graph-independent campaign. The original cluster JUnit and target check must be recorded with case-local I/O/coverage probes before new trials count.

The independent campaign now runs the unchanged Hadoop 3.4.3 three-JournalNode
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

The resumable campaign is in tmux `hdfs07-independent`, with an 80-trial,
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
