# HDFS-09: committed transaction ID monotonicity

## Source and original cluster test

Hadoop 3.4.3 `Journal.checkRequest(RequestInfo)` calls `Preconditions.checkArgument` at `Journal.java:504` after `reqInfo.hasCommittedTxId()`. Its predicate is `reqInfo.getCommittedTxId() >= committedTxnId.get()`. The original class file places the `checkArgument(boolean,Object)` call at bytecode index 239; the runtime recorder identifies that exact invocation as `<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>#u78`. [Original bytecode](evidence/original-checkRequest-javap.txt) records both the call and source line.

The unchanged upstream `TestQuorumJournalManager#testSingleWriter` runs through JUnitCore in [OriginalHdfs09Test.java](OriginalHdfs09Test.java). Its `@Before` creates a three JournalNode `MiniJournalCluster`, and `@After` and `@Rule` execute. `testSingleWriter` writes and finalizes segments 1–3 and 4–4. `QuorumOutputStream.flush` updates the committed ID after a successful write quorum, so later journal RPCs exercise the selected check. The Hadoop source is the clean 3.4.3 worktree on branch `research/hdfs09-committed-txid` under this case directory. No Docker was used.

A request that moves the committed ID backward should raise `IllegalArgumentException`. That is the intended guard response to an invalid request, so a target exception after injection would require request sequence and JournalNode state replay before a bug mark. A stale epoch or serial exception elsewhere in `checkRequest` is a different guard outcome.

## Exact runtime target and I/O observations

The healthy original JUnit passed. Its trace contains 12 `#u78` invocations, each with `CALL_ARGUMENT` index 0 = `true` and a matching `CALL_SITE_RETURN`. The selected repeatable invocation is on `jn2#epoch0` under the original test's request, called by `Journal.finalizeLogSegment` with `(startTxId,endTxId)=(4,4)`. This selects the last segment's JournalNode check independently of trace sequence numbers. The healthy trace observes 108 IPC response fault-marker variants across 36 physical responses. A separate healthy run of the same JUnit with a direct file probe observes four `BestEffortLongFile.set` committed-ID writes on each JournalNode.

The IPC runtime events and exact exception injection use the copied, checksum-pinned GraphChecker HDFS JAR plus case-local woven class and IPC overlays. This case uses the JAR only as a low-level call/I/O recorder and fault executor. It does **no** static analysis, graph aggregation, closure planning, or graph-based result gating. The direct committed-ID file probe is [Hdfs09FileDoor.java](file-door/src/Hdfs09FileDoor.java) inserted only at `BestEffortLongFile.set`'s `IOUtils.writeFully` call; its builder verifies one patch site. A synthetic trace marker at the applied write places each file fault before the selected `#u78` call. The runners now use the JAR's ordinary `discovery` trace mode without a region-skeleton property. A fresh healthy discovery run passed and reproduced the exact target call and all 108 IPC selector identities.

## Bounded coverage and I/O campaign

The [IPC campaign](campaign.py) and [committed-ID write campaign](file_campaign.py) first ran 16 single-fault trials. The [sequence expansion](expand_campaign.py) added one later, actually observed IPC response or committed-ID write selector to a successful parent sequence at a time. It used method/branch coverage, newly observed I/O identities, RPC phase, and JournalNode diversity as feedback. IPC selectors include the marker, call site, occurrence address, hit ordinal, and source identity; file selectors include the JournalNode and write ordinal. The expansion reached the authorized 48-trial budget and maximum depth four. The last eight trials added no production coverage or I/O family, so the conditional 96-trial extension was unnecessary.

| Phase | Attempted trials | Exact fault events matched/applied | Selected `#u78` after faults | Original JUnit passed |
| --- | ---: | ---: | ---: | ---: |
| IPC response single faults (`IOException`, `EOFException`, `SocketTimeoutException`) | 12 | 12/12 | 12 | 12 |
| Committed-ID write single faults (`IOException`, `FileNotFoundException`) | 4 | 4/4 | 4 | 4 |
| Two- to four-fault sequences | 32 | 92/92 | 28 | 28 |
| **Total** | **48** | **108/108** | **44** | **44** |

All 48 injections matched and applied in their requested order. In four sequences the original JUnit raised a quorum failure before the pinned `jn2` guard call; those are retained as attempted trials and excluded from the 44 valid target evaluations. Each valid selected call had a true predicate and returned. No selected call threw `IllegalArgumentException`, and no new bug was confirmed (`bug_mark: none`). A backward committed-ID request would be expected to throw at this guard; epoch and fencing guard exceptions at other source sites are excluded from this target oracle. The healthy `testSingleWriter` did not produce an expected guard exception.

Production coverage grew from 137 IDs (65 method entries, 72 branch outcomes) in the healthy seeds to 156 IDs (74 method entries, 82 branch outcomes): **19 new production IDs**. The first 16 trials found 18; the sequence expansion found one more. The raw recorder count grew from 152 to 175 IDs. Production accounting excludes the synthetic IPC door branches and direct file-probe markers. The single-fault IPC and file phase gains use their own healthy seeds and overlap, so they are not additive.

The consolidated [trial ledger](trial-ledger.csv) records every exact selector or sequence, requested and applied fault counts, per-trial JUnit and wall seconds, target outcome after injection, and production method/branch coverage. [result.json](result.json) adds the full elapsed time of **1,759.898 seconds**, including setup and all trials. [finish_campaign.py](finish_campaign.py) audited its production coverage and trial counts after the checkpointed run. [expansion/checkpoint.json](expansion/checkpoint.json) and the two single-fault checkpoints record resumable progress. Expansion ran in the named `hdfs09-expansion` tmux session and atomically published each completed trial to `result.json` for the node0 checklist.

## Reproduction and scope

[bootstrap-runtime.sh](bootstrap-runtime.sh) rebuilds the case-local IPC overlay and healthy JUnit from the retained runtime probes. [run_original.py](run_original.py) executes the original test with an exact IPC trial JSON; [run_file.py](run_file.py) executes it with the committed-ID file probe. Both use ordinary discovery tracing without a region-skeleton input. The campaigns resume from their checkpoints. The source worktree, JUnit wrapper, selector files, full traces, patched-bytecode proof, checkpoints, ledger, and result all live under `cases/HDFS-09`.

The assessed workload is the original single-writer JUnit and the observed IPC response and committed-ID write points. It does not intentionally send a backward committed ID. The file write probe covers `BestEffortLongFile.set` writes, not every file read or epoch-file operation.
