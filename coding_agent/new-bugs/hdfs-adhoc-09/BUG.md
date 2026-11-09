# hdfs-adhoc-09: JournalNodeSyncer auto-format lets a wiped JN vote in recovery quorums before it has re-synced, so a new writer can recover without committed edits and reuse their txids (lost acknowledged edits, divergent JN logs).

Severity (reviewer): **data-loss**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:504`, `Journal.checkRequest(RequestInfo)`, throws `java.lang.IllegalArgumentException` when `if (reqInfo.hasCommittedTxId()) { Preconditions.checkArgument(reqInfo.getCommittedTxId() >= committedTxnId.get(), ...); }   (fails when the condition is false)`
- Starting test: `org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** With dfs.journalnode.enable.sync and enable.sync.format on: writer 1 commits txns 4-10 on {B, C} while A lags. Writer 1 crashes, C's journal disk is wiped and C restarts, its JournalNodeSyncer auto-formats it, and B is restarting while writer 2 recovers with {A, C}.

**Why (root cause in the source):** JournalNodeSyncer.formatWithSyncer (JournalNodeSyncer.java:253ff) calls Journal.format(force) and the amnesic C immediately counts toward newEpoch and recovery quorums, with nothing gating it on having caught up. Writer 2 therefore recovers from {A, C}, sees only txns 1-3, and reuses txids 4..10 for different edits. Committed edits 4-10 are silently lost on the new active NN, and B's log diverges. Without auto-format C would answer 'not formatted' and writer 2 would block, which is the safe outcome. The check at Journal.java:503-508 fires on B because the new writer's committedTxId (6) is below B's durable committedTxnId (9), so it is detecting genuinely lost commits, not fencing a stale request. The trigger is a disk loss on one JN plus a concurrent JN restart, real operational events for which this feature exists, though it goes beyond plain crash-recovery and needs the non-default sync.format option.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** QJM's safety depends on every acceptor that acknowledged an edit keeping it durably, so that any later write quorum intersects every earlier commit quorum. The JournalNodeSyncer's auto-format (formatWithSyncer -> Journal.format(nsInfo, true)) breaks this. A JN that lost its disk is re-formatted with fresh state (no edits, committedTxnId reset, lastPromisedEpoch=0) and counts toward quorums again straight away, even though it no longer holds the edits it acknowledged and has caught up on nothing. Only one JN is unavailable at any moment (A was just slow, C was 'repaired', B was restarting), which is within the 1-of-3 fault tolerance operators expect, yet the new active writer recovers from {A, C} and reuses txids 4..10 for different edits. This is a coordination failure: a correct protocol would never let a new writer's committed txid fall below one already committed. Consequences in a real deployment: (a) edits 4-10, already acknowledged to clients as durable (mkdirs, creates, block allocations, and so on), are silently lost on the new active NameNode, and txids 4..10 now mean different edits on different JNs (B still holds writer 1's 4-10); (b) JN B rejects every later request from the new writer with this IllegalArgumentException until its committed txid is overtaken or an operator intervenes, so the cluster runs with one fewer usable JN; (c) the divergent edit logs can later make standby, bootstrap or JN-sync paths read inconsistent segments. The ad hoc check at Journal.java:504 is the only place that notices the lost commits.

**Execution (agent):** The setup is the same as TestQuorumJournalManager: 3 JournalNodes A, B, C, with QJM writers standing in for NameNodes. The JN syncer and its auto-format feature are on (dfs.journalnode.enable.sync=true, dfs.journalnode.enable.sync.format=true). (1) Writer 1 (epoch 1) writes segment 1-3 and finalizes it on all JNs. (2) JN A becomes slow: writer 1's edit batches to A are queued but never delivered (a Mockito spy on A's sendEdits returns a future that never completes). (3) Writer 1 starts segment 4 and writes txns 4-6, 7-9 and 10. Each batch is acked by the quorum {B, C}, so it is committed, and the following batch carries the committed txid, so B and C persist committedTxnId=9. A has nothing past txid 3 and knows committed=3. (4) Writer 1 (the active NN) crashes. (5) JN C loses its disk: it is stopped, its journal directory is wiped, and it restarts empty. When the journal is instantiated on C, C's JournalNodeSyncer finds it unformatted and calls Journal.format(nsInfo, force=true) with the storage info of another JN. C is now 'formatted' again: committedTxnId=INVALID, lastPromisedEpoch=0, no segments. (6) JN B restarts while writer 2 takes over, so writer 2's quorum is {A, C}. (7) Writer 2 runs recoverUnfinalizedSegments with {A, C} and gets epoch 2. newEpoch reports A's last segment as 1 (A's empty edits_inprogress_4 is moved aside) and nothing on C. Recovery finalizes 1-3, and the QJM sanity check passes because A's committed is 3 and C's is INVALID. selectInputStreams over {A, C} returns txns 1-3 only. (8) Writer 2 continues at txid 4: it writes and commits 4-5 and 6 on {A, C}. (9) B comes back with committedTxnId=9 and an in-progress segment holding writer 1's txns 4-10. (10) Writer 2 rolls: finalize 4-6 (B is skipped as out of sync on the client side), then startLogSegment(7), which is sent to every JN. On B, Journal.startLogSegment calls checkRequest: the epoch 2 promise is accepted and the IPC serial is fine, but reqInfo.committedTxId=6 < committedTxnId=9. Preconditions.checkArgument throws IllegalArgumentException 'Client trying to move committed txid backward from 9 to 6 ; journal id: test-journal' at Journal.java:504. The test surfaces B's per-JN future result, a RemoteException carrying the server stack trace.

**Stack frame (agent):** at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:504)

## Reproduction

- Test: `org.apache.hadoop.hdfs.qjournal.client.TestQJMCommittedTxIdAfterJNReformat#testCommittedTxIdMovesBackwardAfterJNReformat`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.qjournal.client.TestQJMCommittedTxIdAfterJNReformat#testCommittedTxIdMovesBackwardAfterJNReformat' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/TestQJMCommittedTxIdAfterJNReformat.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.ipc.RemoteException(java.lang.IllegalArgumentException): Client trying to move committed txid backward from 9 to 6 ; journal id: test-journal`, frame `at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:504)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h22m | 1 | 5,227,152 | 98 | 101,428 | 170,625 | 4,955,001 | $4.38 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
