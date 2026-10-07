# HDFS-39: committed block during append

The Hadoop 3.4.3 check in `FSDirAppendOp.appendFile` throws
`RetriableException(NotReplicatedYetException)` when the last block is
`COMMITTED` but not yet `COMPLETE`. This comes after lease recovery in the
function. The originally proposed `TestFileAppend#testAppendTwice` uses one
DataNode: its second append is intentionally rejected as
`AlreadyBeingCreatedException` by the active lease, before this block-state
check can decide the second request.

The original `TestFileAppend#testMultipleAppends` starts one NameNode and four
DataNodes, enables closing with one committed block, then repeatedly appends
and closes `/testMultipleAppend/foo`. The unchanged JUnit passed in 14.307 s.
An isolated source probe then observed the exact `FSDirAppendOp.appendFile`
guard 10 times for the same path and block, with 151 relevant RPC or edit-log
I/O points before the last guard. Production-only healthy JaCoCo coverage is
recorded in `independent-coverage-io/healthy/probed/coverage.tsv`.

The successful healthy JUnit itself emitted one exact
`RetriableException(NotReplicatedYetException)` from the selected guard.
`DFSClient.callAppend` in the released 3.4.3 source retries that exception
every 500 ms for up to 5 s while the block becomes complete. Therefore a
target exception is recorded as a candidate observation and is never by
itself marked a new bug. A fault trial must apply its entire ordered selector
and revisit this exact source site for the same file and block after the last
fault to count toward the checked target. A failed JUnit plus an exact
post-fault target exception requires a same-selector replay and source review.

The healthy trace makes the expected transition concrete: target guard
`COMMITTED` at trace event 45, exact retriable exception at 46, DataNode
`blockReceivedAndDeleted` RPC responses at 47–49, and retry guard `COMPLETE`
at 51. Both guard events name `/testMultipleAppend/foo` and block
`1073741825`. This is the coordination state the campaign attempts to
perturb; test failure caused directly by an injected I/O exception is not
interpreted as a defect in this guard.

The current campaign uses case-local source-level probes for the selected
guard, Hadoop IPC responses, and durable edit-log flushes. Relevant RPCs
include client operations and DataNode `blockReceivedAndDeleted`, which the
healthy trace shows between `COMMITTED` and `COMPLETE`. Fault points come
only from observed I/O; Java I/O exceptions are injected by exact
marker, API, endpoint, and ordinal. JaCoCo method, branch and probe coverage
from released production classes guides subsequent selection and mutation.
The campaign reads no GraphChecker graph, static slice, skeleton, or closure.
Its resumable checkpoint, selectors, per-trial traces, coverage and elapsed
times are under `independent-coverage-io/campaign/`; the driver is hosted in
the `hdfs39-coverage-io` tmux session on node0 and runs isolated original
JUnit trials on node1. The nominal budget is 80 trials with up to eight
ordered faults; real production method/branch or stable I/O-family novelty in
the last eight trials extends it to 128 trials with up to ten faults. The
related [HDFS-40](../HDFS-40/README.md) checks replication after a complete
block.

Here, a budgeted **effective** trial means every requested fault was applied
in order and the same file/block guard ran after the final fault. Unmatched
and `lost_target` attempts remain in the ledger but do not consume the 80
effective-trial budget. To keep search bounded, attempted trials may be at
most twice the effective budget. Extension to 128 effective trials uses the
last eight effective trials' new production method/branch coverage or stable
I/O-family novelty.

After 11 completed trials, the seed selection was broadened to include the
already recorded DataNode block-report RPC family and to balance I/O families.
The source probes, JaCoCo collection and original JUnit remained identical;
the 11 finished trials were retained verbatim in the same checkpoint.

Source review of `Client.call` showed that the first recorder intercepted
`getRpcResponse` *after* `connection.sendRpcRequest(call)`: a lost response
cannot prevent the NameNode from receiving a DataNode block report. After
trial 23, a second healthy run with an additional `Client.sendRpcRequest`
probe passed (15.765 s), again reached the same guard 10 times, and observed
27 `blockReceivedAndDeleted` send points before the final guard. From trial
24, the campaign can inject at the observed pre-send boundary. The earlier
23 trials, their original recorder version and raw evidence are retained.
Only the common IPC `Client` override changed; JaCoCo feedback is restricted
to Hadoop HDFS production classes, so its method, branch and probe IDs remain
comparable across the two recorder phases. The new healthy trace and coverage
are under `healthy/probed-v2/`. The two healthy coverage and I/O sets were
unioned, then all completed trial novelty counts were recalculated from their
saved traces and JaCoCo TSVs with **zero JUnit reruns**. The exact before/after
changes are in `campaign/feedback-recompute.json`.

After trial 43, queue selection gained a bounded depth bonus so already
observed two-fault block-report send sequences are sampled alongside
one-fault seeds. The 43 completed trials were retained, and no test or
instrumentation code changed at this policy step.

After trial 56, a bounded selection adjustment reduces priority for
near-duplicate sequences that share an already tested prefix and last I/O
family when two strict siblings both lost the target. It changes only queue
ordering. Candidate fault points still come from observed I/O, and production
coverage plus new I/O continue to influence mutation priority. All earlier
completed trials and their selectors remain in the checkpoint.

The version-2 healthy trace has its only `COMMITTED` target guard at event 69;
the later nine guards see `COMPLETE`. By trial 114, 84 effective post-fault
trials had covered only the `COMPLETE` branch. A bounded 20-attempt selection
stratum now samples already queued, observed I/O before that first
`COMMITTED` guard. Its family-aware ranking remains based on the same healthy
I/O trace and existing coverage/I/O feedback. It changes no workload,
instrumentation, fault model or completed trial. Trials 115–134 fully applied
20/20 ordered single-fault selectors; eight retained the same target after
fault and all eight reached the `COMMITTED` branch and exact exception. They
added three production branch units. The checkpoint identifies the change,
and `campaign/report_phase.py` reports before/after strict injections,
effective trials, branch states and exact target exceptions.

Trial 116 strictly injected an edit-log flush `IOException`, then reached
the same block's `COMMITTED` guard and exact `RetriableException` after the
fault. The unchanged JUnit passed; a same-selector replay confirmed the
expected retry. Trial 118 strictly injected an `EOFException` at the
client `append` RPC response-wait entry and also reached the `COMMITTED`
guard. The JUnit failed because that injected client exception propagated
from `fs.append`; replay and source review showed the server target
`RetriableException` was the same expected transient in the healthy test.
`campaign/candidate-reviews.json` retains trial 118 as a raw oracle
candidate and records why it is **not** a validated new bug. Trial 125 is the
analogous injected client `SocketTimeoutException`; its same-selector replay
likewise attributes the JUnit failure to the local injection rather than
the server's target exception. The raw candidate and rejection are retained.

Trial 144 is a four-fault candidate: three DataNode block-report response
exceptions, then a client `append` response-wait exception. All faults and
the same file/block target were observed after the final injection. The
original run reached `COMMITTED` and failed; the identical four-fault replay
failed from the injected client `IOException` but reached `COMPLETE`, so the
exact target exception did not reproduce. A three-fault prefix replay
strictly applied the DataNode faults and passed. The raw candidate, replay,
prefix ablation and source review are retained without a new-bug mark.

Trial 180 is a second four-fault target candidate with one DataNode
pre-send fault. The complete selector and target exception replayed, but
the JUnit failure again came from the final injected client timeout. A
strict three-DataNode-fault ablation produced two post-fault `COMMITTED`
target exceptions, then recovered to `COMPLETE` and passed. This separates
the expected target retry from the injected client operation failure.

After trial 180, queue ranking adds a bounded penalty when a precise later
I/O selector has repeatedly disappeared after the same applied prefix.
The preceding 20 attempts had seven strict injections and five effective
target-retaining trials, largely because deep sibling sequences could not
match their final I/O. This change uses only the saved runtime I/O and
fault-applied feedback; it retains every completed trial and every queued
selector. Production coverage and new I/O still guide mutation and priority.

## Final result

The campaign reached its conditional 128-effective-trial budget in 205
attempts. Of these, 171 applied every requested fault in order and 128 also
reached the exact guard for the same file/block after the last fault. The
largest attempted sequence had six faults; five faults were the largest
strictly applied sequence. Twelve effective trials reached the `COMMITTED`
branch and emitted the precise target `RetriableException` after injection.
Four failed-JUnit oracle candidates were replayed and audited individually;
all four failures were caused by a client I/O exception injected into the
original `append` call, while the target exception was a recoverable
`COMMITTED` transient. **Validated new HDFS bugs: 0.**

Against the union of the two healthy recorder phases, accepted fault trials
added 373 production method IDs, 599 production branch-unit IDs and 1,565
production JaCoCo probe IDs. Total measured time, including the original
healthy JUnit and both probe calibrations, was 5,748.106 seconds. The final
`result.json` links the atomic 205-row checkpoint/ledger, every exact plan,
manifest and raw target/fault trace, the lossless coverage archive, SHA-256
provenance for remote JaCoCo exec files and release JARs, the phase report,
candidate replays and the independent 205-trial audit. No Docker or
GraphChecker graph artifact was used in this case.
