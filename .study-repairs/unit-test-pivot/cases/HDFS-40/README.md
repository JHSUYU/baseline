# HDFS-40: under-replicated complete block during append

The Hadoop 3.4.3 check in `FSDirAppendOp.appendFile` throws `IOException`
when the last block is complete and `BlockManager.isSufficientlyReplicated`
returns false. The latter compares live replicas with minimum storage and
the number of live DataNodes. The originally proposed
`TestFileAppend#testAppendTwice` uses one DataNode and its second append is
rejected earlier by the lease check. Exact runtime calibration instead chose
the unchanged `TestFileAppend#testFailedAppendBlockRejection` operations,
which repeatedly reach this guard in an original `MiniDFSCluster` test.

## Original JUnit and exact runtime calibration

The released source condition is `lastBlock.isComplete() &&
!blockManager.isSufficientlyReplicated(lastBlock)` at
`FSDirAppendOp.java:136-139`. `BlockManager.java:1716-1725` counts live
replicas and compares with minimum storage and live DataNodes. The default
minimum replication is one; merely stopping one holder of a three-replica
block normally leaves this check false.

This is a cross-node state check: `BlockManager.countNodes` reads the
NameNode's view of replicas, which DataNode block-received reports update.
The original `testFailedAppendBlockRejection` creates three DataNodes,
stops dn0, and appends the same file three times before restarting dn0.
Therefore dn1/dn2 reports before a later append can change the value read by
this guard. The check is not a local redundant comparison, although an
injected report failure may also legitimately cause an append to fail.

The case-local, graph-free probe preserves the original short-circuit order,
records `complete`, `sufficient`, file path, block ID and target throw, and
observes Hadoop RPC send/response-wait and NameNode edit-log flush I/O. The
RPC fault identity includes the original append path or block-received block
ID. JaCoCo feedback is limited to released production classes. The original
JUnit operations and assertions were not changed; the class overrides,
runner, original source copies and provenance are under
`independent-coverage-io/`.

On node2, all following original MiniDFSCluster JUnit runs passed:

| Original JUnit | Cluster/behavior | Seconds | Exact guard | Target throw |
| --- | --- | ---: | ---: | ---: |
| `TestFileAppend#testMultipleAppends` | 1 NN, 4 DN, repeated appends | 19.416 | 9 nonfatal | 0 |
| `TestFileAppendRestart#testAppendWithPipelineRecovery` | 1 NN, 4 DN, stop one DN | 24.388 | 1 nonfatal | 0 |
| `TestFileAppend#testFailedAppendBlockRejection` | 1 NN, 3 DN, stop one DN, three deterministic appends | 19.678 final seed | 3 nonfatal | 0 |
| `TestFileAppend#testMultiAppend2` | 1 NN, 3 DN, stop/restart one DN | 26.602 | 3 nonfatal across distinct blocks | 0 |
| `TestFileAppend4#testUpdateNeededReplicationsForAppendedFile` | 1 NN, 1 DN, RF2 append | 18.418 | 1 nonfatal | 0 |
| `TestFileAppend4#testAppendInsufficientLocations` | 1 NN, 4 DN, stop all holders of last block | 32.560 | 1 fatal | 1 expected `IOException` |

The last test explicitly expects and catches that exception, so it is an
instrumentation positive control and is excluded from the fault bug oracle.
The final seed is the deterministic `testFailedAppendBlockRejection`, with
all three healthy guards on `/test`, block 1073741825. The first exact
`blockReceivedAndDeleted` RPC-send `IOException` trial matched, reached the
same guard after the fault, passed the original JUnit, and added released
production coverage. Its trace and elapsed time are in
`independent-coverage-io/campaign/trial-001/`. This first campaign was
paused after 13 single-fault trials because the block-received RPC selector
identified the block but did not identify which DataNode sent the report.
All 13 remain preserved as a separate semantic pilot, with an independent
audit at `independent-coverage-io/campaign/audit_snapshot.json` (13 exact
injections, 13 target-retaining runs, no target exception, no audit error).
A target exception is marked as a candidate only when it follows an exact
fault sequence and the same file/block guard; an unexpected JUnit result by
itself is not the oracle.

At a clean checkpoint after trial 7, source review found that the
`EditLogFileOutputStream.flushAndSync` method-entry marker precedes
`doubleBuf.isFlushed()` and can occur without a physical write. The original
seven completed trials all injected semantic RPC-send faults. We preserved
those trials and their original driver, then removed 37 untested file-entry
sequences from the queue; the queue went from 168 to 131. The unchanged
instrumentation continues to observe that marker, but `rpc_semantic_v2`
selects only semantic RPC send or response-wait fault points. See
`independent-coverage-io/campaign/file-gate-change.json`, the compressed
pre-change checkpoint, and the two driver hashes in
`independent-coverage-io/source-provenance.json`. A real `flushTo`/`force`
file-I/O supplement would use a separate instrumentation epoch.

## Actor-aware campaign

The follow-up uses the same original
`TestFileAppend#testFailedAppendBlockRejection` JUnit and the same three
append operations. The case-local probe only registers the three existing
`MiniDFSCluster` DataNodes by index and marks the point after the test's
original `stopDataNode(0)` call. At `blockReceivedAndDeleted`, it maps the
sender's `DatanodeRegistration` UUID to `dn0`, `dn1`, or `dn2`. A fault selector
now includes `nn0<-dnX`, the block ID, the I/O marker and ordinal, and the
exception. A trial counts as physically identified only when the observed
source role and post-stop phase also match. The original operations and
assertions are unchanged.

The actor-aware healthy seed passed in 18.525 seconds and reached the same
nonfatal `/test` block guard three times. Its first EOFException trial hit
`dn2`'s block-received RPC send, then reached the target guard again and
passed the JUnit in 29.771 seconds. The actor-aware campaign runs in tmux
`hdfs40_actor`; its checkpoint, per-trial ledger, exact compressed coverage
exports, raw JaCoCo data, traces, and JUnit logs are under
`independent-coverage-io/actor-v2/`. It has 80 actor-aware attempts at most
with eight faults per sequence. The 13 semantic pilot attempts are recorded
separately and do not consume this budget. It extends to 128 actor-aware
attempts and ten faults
only if the last eight valid attempts add a released production method or
branch, or a stable I/O family. Every trial uses the same original test,
and a target exception is a candidate only when it follows an exact fault
sequence and the same file/block guard.

At 80 actor-aware attempts, 75 complete sequences were injected and 74
reached the same `/test` block guard after the last fault. Five sequences
were only partly injected; one fully injected sequence lost the target.
Sixteen JUnit failures without the target exception were excluded from bug
classification, including that lost-target run. The 13 pilot trials are
separate. The last eight effective actor runs included two new JaCoCo
branch units in `BlockManager.processReportedBlock` at actor trial 76, so
the bounded 128-attempt/10-fault extension is justified. The exact window,
branch IDs, audit hash, and exclusion counts are in
`actor-v2/campaign/extension-decision-080.json`.

At the clean checkpoint after actor trial 46, trial 42 and the original
source showed that injecting at the client `append:/test` RPC send aborts the
uncaught `fs.append` before the NameNode can enter this guard. We removed
122 untested queue sequences containing that send point (410 to 288), kept
all 46 completed rows, and retained client response-wait and DataNode report
faults. The before/after compressed checkpoints, exact queue hashes, and
removed IDs are in `actor-v2/campaign/client-send-prune.json`. Trial 42
remains `lost_target` and is not a bug candidate.

At the clean checkpoint after actor trial 52, the budget was corrected to
count only actor-aware runs: 80 attempts/8 faults, conditionally extending
to 128 attempts/10 faults. The 13 earlier semantic pilot attempts remain
separate. All completed trials and queued selectors were preserved; the
before/after checkpoint hashes are in
`actor-v2/campaign/actor-budget-migration.json`.

At the clean checkpoint after actor trial 70, the checklist result's
top-level `fault_trials`, `fully_applied_trials`, `target_after_fault`, and
`elapsed_seconds` were changed to count only the actor-aware phase. The 13
semantic pilot trials and their time remain nested under
`semantic_single_fault_pilot`; `total_elapsed_seconds_all_phases` adds both
phases. The exact before/after result hashes and counters are recorded in
`actor-v2/campaign/actor-only-result-counters.json`.

A separate read-only review by the HDFS-39 case owner independently
regenerated actor trials 20 and 42 coverage exports from their raw JaCoCo
files and matched the archived SHA-256 values. In trial 20, dn2 and dn1
faults occurred at trace seq 80 and 102, then the `/test` guard ran at seq
121. In trial 42, a client append send fault occurred at seq 121 and no
target guard followed. Target guard rows do not themselves store a phase or
NameNode actor field; the test has one NameNode, and the trace order places
these guards after the test's post-dn0-stop marker. `BRANCH_UNIT` feedback
counts covered JaCoCo branch units per source line; it does not identify an
individual branch edge. Method and JaCoCo probe IDs are recorded separately.

## Final actor-aware result

The bounded campaign stopped at 128 actor-aware attempts, with at most seven
faults actually requested in one sequence. Of those, 123 sequences were
fully applied with the exact physical DataNode and post-stop phase; 122
reached the same `/test` block 1073741825 guard after the last applied fault.
Five sequences were partly applied, and one fully applied sequence lost that
target. Twenty-two original JUnit runs failed without the target exception;
21 of these still reached the guard after the last fault. They are retained
as non-target outcomes, not new-bug candidates. No faulted run produced the
selected `IOException` after the target guard. The 13 earlier semantic pilot
attempts remain separate and do not count toward any of these totals.

Relative to the actor-aware healthy seed, the union of faulted runs gained
275 released production methods, 627 JaCoCo branch units, and 1,442 JaCoCo
probes. Trials 124–126 added further coverage, but the predeclared 128-run
cap ended the search. Actor-aware runtime was 3,821.452 seconds including
the 18.525-second seed; the separate pilot took 556.375 seconds. The
per-trial durations and results are in `actor-v2/campaign/trial-ledger.csv`.

`actor-v2/campaign/audit_final.json` independently checked all 128 raw
traces, selectors, JUnit logs, JaCoCo files, compressed coverage exports,
checkpoint and ledger, and found zero integrity errors. Its SHA-256 is
`af7056c1dc9acd2801b6c3a3a42fcf5435ab5612822ef2fd1448b5f8d17d0d01`.
The result is `quality_complete` for this original JUnit and bounded fault
budget, with no new bug found at HDFS-40. It does not exhaust all append
workloads or possible fault sequences.
