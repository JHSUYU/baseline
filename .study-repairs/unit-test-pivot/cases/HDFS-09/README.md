# HDFS-09: committed transaction ID monotonicity

**Current 102-check status: quality complete, no confirmed new bug.** The
independent campaign completed **128/128** precisely applied fault sequences;
**113** retained the exact guard after the last fault, and **zero** triggered
its `IllegalArgumentException`. The deepest executed sequence had six faults
and retained the target. The original JUnit execution time summed to
**1,498.962 seconds** across one healthy seed and 128 fault trials. Relative
to that seed, production coverage gained 84 methods, 141 covered branch-count
IDs, 407 exact JaCoCo probes, and 426 lines. The final eight trials added no
new production coverage or stable I/O family.

The 48
trials below remain historical evidence in `legacy-graph-result.json`. Their
exact I/O selectors contain GraphChecker `REGION.*` occurrence identities from
prewoven classes. Running in discovery mode without a skeleton file did not
remove that woven identity dependency, so the trials do not count as an
independent runtime campaign.

## Independent replay (current)

The new `independent/` recorder runs the **unchanged upstream**
`TestQuorumJournalManager#testSingleWriter` through JUnitCore and its native
`@Before`, `@After`, and `@Rule` in a fresh three-JournalNode MiniJournalCluster
per trial. It reads original Hadoop 3.4.3 class files, then applies a
case-local ASM 9.6 classpath overlay at the exact line-504
`Preconditions.checkArgument(boolean,Object)` call, the committed-ID file
write in `BestEffortLongFile.set`, and `Client.getRpcResponse`. The probe
records the check predicate, actual guard throw or return, and observed I/O
identities. JaCoCo 0.8.15 supplies production method, line, branch-count,
and exact probe feedback. The [original and patched bytecode](independent/evidence/independent-overlay-checkRequest-javap.txt)
shows the target hook immediately before the original invocation and the
exception handler around that invocation. No GraphChecker prewoven class,
runtime JAR, region skeleton, static I/O map, causal graph, or closure is on
this execution path.

Production coverage excludes the test's runtime-generated
`$MockitoMock$...` classes. Those classes have random names on each JUnit
run and otherwise create false probe novelty. The independent recorder
filters them; [recompute_feedback.py](independent/recompute_feedback.py)
also corrected the saved early rounds from their original JaCoCo files
without rerunning completed fault sequences.

The independent healthy run passed in **9.902 seconds**, reached the exact
check **12 times**, and observed 48 I/O events: 36 IPC responses and 12
committed-ID file writes. A preliminary injected `IOException` at
`journalnode-0`'s second committed-ID write matched and applied, the original
JUnit passed, and eight subsequent target checks ran. The campaign starts
from this clean healthy seed at **80 trials and at most eight ordered faults**;
only current independent trials update `result.json`. If the last eight trials
still discover genuine production coverage or a stable I/O family, it extends
the same checkpoint to 128 trials and ten faults. The node0 campaign ran in
tmux session `hdfs09-independent`. Each completed trial atomically updated
`independent/evidence/campaign-state.json` and `result.json`.

The first 80 independent trials were all precisely injected; 70 retained the
target and none triggered its exception. Trial 73 added genuine production
coverage in `QJournalProtocolServerSideTranslatorPB`, still after filtering
dynamic test mocks. Accordingly, the same checkpoint is continuing through
the authorized **128-trial, ten-fault ceiling**, with no completed trial
repeated. The completed [per-round ledger](independent/trial-ledger.csv),
[summary](independent/evidence/campaign-summary.json), and [result](result.json)
record each runtime selector, application and target result, coverage gain,
JUnit result, and time. The campaign has ended; the tmux session is no longer
running.

Source review connects the two operands: after a successful write quorum,
`QuorumOutputStream.flushAndSync` advances the client logger's committed
transaction ID; later QJM RPCs carry that value in `RequestInfo`.
`Journal.checkRequest` compares it with the receiving JournalNode's
`BestEffortLongFile` value. The source describes the committed-ID file as a
recovery sanity check and visibility mark, rather than a durability condition.
A backward request would be intentionally rejected by this guard, so an
observed target throw would need replay and source review before a bug mark.

The sections below document the excluded historical campaign. Its counts,
coverage, and runtime are not included in the current independent result.

## Source and original cluster test

Hadoop 3.4.3 `Journal.checkRequest(RequestInfo)` calls `Preconditions.checkArgument` at `Journal.java:504` after `reqInfo.hasCommittedTxId()`. Its predicate is `reqInfo.getCommittedTxId() >= committedTxnId.get()`. The original class file places the `checkArgument(boolean,Object)` call at bytecode index 239; the runtime recorder identifies that exact invocation as `<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>#u78`. [Original bytecode](evidence/original-checkRequest-javap.txt) records both the call and source line.

The unchanged upstream `TestQuorumJournalManager#testSingleWriter` runs through JUnitCore in the [independent JUnit runner](independent/run_original.py). Its `@Before` creates a three JournalNode `MiniJournalCluster`, and `@After` and `@Rule` execute. `testSingleWriter` writes and finalizes segments 1–3 and 4–4. `QuorumOutputStream.flush` updates the committed ID after a successful write quorum, so later journal RPCs exercise the selected check. The Hadoop source is the clean 3.4.3 worktree on branch `research/hdfs09-committed-txid` under this case directory. No Docker was used.

A request that moves the committed ID backward should raise `IllegalArgumentException`. That is the intended guard response to an invalid request, so a target exception after injection would require request sequence and JournalNode state replay before a bug mark. A stale epoch or serial exception elsewhere in `checkRequest` is a different guard outcome.

## Exact runtime target and I/O observations

The healthy original JUnit passed. Its trace contains 12 `#u78` invocations, each with `CALL_ARGUMENT` index 0 = `true` and a matching `CALL_SITE_RETURN`. The selected repeatable invocation is on `jn2#epoch0` under the original test's request, called by `Journal.finalizeLogSegment` with `(startTxId,endTxId)=(4,4)`. This selects the last segment's JournalNode check independently of trace sequence numbers. The healthy trace observes 108 IPC response fault-marker variants across 36 physical responses. A separate healthy run of the same JUnit with a direct file probe observes four `BestEffortLongFile.set` committed-ID writes on each JournalNode.

The IPC runtime events and exact exception injection use the copied, checksum-pinned GraphChecker HDFS JAR plus case-local woven class and IPC overlays. This case uses the JAR only as a low-level call/I/O recorder and fault executor. It does **no** static analysis, graph aggregation, closure planning, or graph-based result gating. The direct committed-ID file probe is [Hdfs09FileDoor.java](file-door/src/Hdfs09FileDoor.java) inserted only at `BestEffortLongFile.set`'s `IOUtils.writeFully` call; its builder verifies one patch site. A synthetic trace marker at the applied write places each file fault before the selected `#u78` call. The runners now use the JAR's ordinary `discovery` trace mode without a region-skeleton property. A fresh healthy discovery run passed and reproduced the exact target call and all 108 IPC selector identities.

## Bounded coverage and I/O campaign

The historical IPC and committed-ID write campaigns first ran 16 single-fault trials. Their sequence expansion added one later, actually observed IPC response or committed-ID write selector to a successful parent sequence at a time. It used method/branch coverage, newly observed I/O identities, RPC phase, and JournalNode diversity as feedback. IPC selectors include the marker, call site, occurrence address, hit ordinal, and source identity; file selectors include the JournalNode and write ordinal. The expansion reached the authorized 48-trial budget and maximum depth four. The last eight trials added no production coverage or I/O family, so the conditional 96-trial extension was unnecessary. The obsolete graph-runtime runner and controller source was removed after the separate graph-free campaign completed; historical traces and ledgers remain.

| Phase | Attempted trials | Exact fault events matched/applied | Selected `#u78` after faults | Original JUnit passed |
| --- | ---: | ---: | ---: | ---: |
| IPC response single faults (`IOException`, `EOFException`, `SocketTimeoutException`) | 12 | 12/12 | 12 | 12 |
| Committed-ID write single faults (`IOException`, `FileNotFoundException`) | 4 | 4/4 | 4 | 4 |
| Two- to four-fault sequences | 32 | 92/92 | 28 | 28 |
| **Total** | **48** | **108/108** | **44** | **44** |

All 48 injections matched and applied in their requested order. In four sequences the original JUnit raised a quorum failure before the pinned `jn2` guard call; those are retained as attempted trials and excluded from the 44 valid target evaluations. Each valid selected call had a true predicate and returned. No selected call threw `IllegalArgumentException`, and no new bug was confirmed (`bug_mark: none`). A backward committed-ID request would be expected to throw at this guard; epoch and fencing guard exceptions at other source sites are excluded from this target oracle. The healthy `testSingleWriter` did not produce an expected guard exception.

Production coverage grew from 137 IDs (65 method entries, 72 branch outcomes) in the healthy seeds to 156 IDs (74 method entries, 82 branch outcomes): **19 new production IDs**. The first 16 trials found 18; the sequence expansion found one more. The raw recorder count grew from 152 to 175 IDs. Production accounting excludes the synthetic IPC door branches and direct file-probe markers. The single-fault IPC and file phase gains use their own healthy seeds and overlap, so they are not additive.

The consolidated [historical trial ledger](trial-ledger.csv) records every exact selector or sequence, requested and applied fault counts, per-trial JUnit and wall seconds, target outcome after injection, and production method/branch coverage. [expansion/checkpoint.json](expansion/checkpoint.json) and the two single-fault checkpoints retain its progress. Expansion ran in the named `hdfs09-expansion` tmux session. These historical counts are excluded from the current [result](result.json).

## Reproduction and scope

For the current baseline, [independent/run_original.py](independent/run_original.py) executes the unchanged JUnit with the case-local ASM I/O probe; [independent/campaign.py](independent/campaign.py) resumes only uncompleted graph-free trials. The historical graph-runtime code has been removed. Its selector files, traces, bytecode proof, checkpoint, and ledger remain for provenance and are excluded from current totals.

The assessed workload is the original single-writer JUnit and the observed IPC response and committed-ID write points. It does not intentionally send a backward committed ID. The file write probe covers `BestEffortLongFile.set` writes, not every file read or epoch-file operation.
