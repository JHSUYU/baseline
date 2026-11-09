# hdfs-adhoc-07: A lagging JN's acceptRecovery is wrongly rejected because the global committedTxnId, already advanced into the next segment, is compared against the recovered segment's range, leaving that JN permanently unsynchronized for the segment.

Severity (reviewer): **operation-failure**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:926`, `Journal.acceptRecovery(RequestInfo, SegmentStateProto, URL)`, throws `java.lang.AssertionError` when `txnRange(currentSegment).contains(committedTxnId.get()) && !txnRange(segment).contains(committedTxnId.get())`
- Starting test: `org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testRecoverAfterIncompleteRecovery`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Writer 1 crashes leaving JN2 with an uncommitted txn 5 in in-progress segment 1. Writer 2 recovers segment 1 to 1-4 with JN0+JN1 while JN2's prepareRecovery RPC is delayed (latch in a delegating proxy, i.e. a slow JN). Writer 2 then starts segment 5 and commits txn 5, and only after that do JN2's queued prepareRecovery/acceptRecovery(1-4) run, stamped with committedTxId=5.

**Why (root cause in the source):** IPCLoggerChannel.createReqInfo() (IPCLoggerChannel.java:287) runs when the queued call executes on the single-thread executor, so the delayed acceptRecovery for segment 1 carries the writer's current committedTxId, 5, which is a txid of segment 5. Journal.checkRequest (Journal.java:503-510) stores it in the journal-wide committedTxnId. Journal.acceptRecovery (Journal.java:924-926) then reads it as a committed txn of segment 1: JN2's stale [1,5] contains 5 and the correctly recovered [1,4] does not, so it throws AssertionError. Recovery to 1-4 was correct (txn 5 was never committed in segment 1), so this is a false positive of the paranoid check, not a fenced stale request. JN2 never syncs or finalizes segment 1 (the finalizeLogSegment(1,4) queued behind it fails too), and it keeps a stale in-progress edits_1-5 whose txn 5 conflicts with the committed txn 5. The trigger is a slow minority JN plus the real per-logger executor queueing, which QJM is meant to tolerate.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check treats the JN's single, journal-wide committedTxnId as a txid of the segment being recovered. But committedTxnId is just the writer's latest committed txid at the moment the RPC runs, and here it belongs to the next segment (txid 5 in segment 5), not to segment 1. Recovery itself was correct: txn 5 of the old segment 1 was never committed, and truncating segment 1 to 1-4 is exactly what Paxos-style recovery should do, so the check rejects a correct coordination. QJM is designed to tolerate a lagging minority JN; it is the common case and its calls are queued asynchronously per logger. Yet any lagging JN whose stale in-progress tail overlaps txids the new writer has already committed in the next segment will fail acceptRecovery with an AssertionError. Consequences: the JN is never synchronized to the recovered segment. It keeps a stale, unfinalizable in-progress edits_1-5, so the queued finalizeLogSegment(1,4) is rejected as well, and it ends up with an overlapping in-progress segment 5 next to it. It has also persisted committedTxnId=5. That JN drops out of the effective quorum for that history, which lowers the cluster's fault tolerance (one more JN failure would block the NameNode), and every later recovery or sync attempt for that segment on it fails the same way until an operator repairs it by hand.

**Execution (agent):** 3 JournalNodes JN0, JN1, JN2. (1) Writer W1 (epoch 1) starts segment 1 and writes txns 1-3 to all JNs. Txn 4 reaches only JN1 and JN2, so it is committed. Txn 5 reaches only JN2: the flush fails its quorum and W1 crashes. JN2 now has in-progress edits 1-5 and committedTxnId=4. (2) A new writer W2 (epoch 2, e.g. the NameNode taking over after failover) runs recoverUnfinalizedSegments. newEpoch succeeds on all three JNs. JN2 is slow (GC pause, slow disk or network), so its prepareRecovery RPC is delayed; the test models this with a latch in a delegating mock of JN2's RPC proxy. Each IPCLoggerChannel uses a single-thread executor, so W2's later calls to JN2 (acceptRecovery, finalize, startLogSegment, journal) queue up behind the delayed one. (3) The prepare quorum is JN0 (1-3) and JN1 (1-4), so W2 picks 1-4. That is correct, since txn 5 was never committed. acceptRecovery(1-4) and finalizeLogSegment(1,4) succeed on JN0 and JN1. (4) W2 calls startLogSegment(5) and writes the START_LOG_SEGMENT txn 5, which is synced alone. It is acked by JN0 and JN1, and W2's IPCLoggerChannels set committedTxId=5. (5) JN2 becomes responsive. Its queued prepareRecovery and then acceptRecovery(segment 1-4) execute. IPCLoggerChannel.createReqInfo() runs when the call executes, not when it was queued, so these requests carry committedTxId=5. Journal.checkRequest sets JN2's committedTxnId to 5. Inside acceptRecovery, JN2's current segment 1 is [1,5], which contains 5, and the new segment [1,4] does not. The check throws java.lang.AssertionError('Cannot replace segment 1-5 with new segment 1-4: would discard already-committed txn 5') from Journal.acceptRecovery (the throw statement starts at line 926; the JVM frame shows Journal.java:932 because the constructor call is tagged with the last line of the multi-line message). The error comes back to the client as a RemoteException, which the test captures and rethrows with the server-side stack trace.

**Stack frame (agent):** at org.apache.hadoop.hdfs.qjournal.server.Journal.acceptRecovery(Journal.java:932)

## Reproduction

- Test: `org.apache.hadoop.hdfs.qjournal.client.TestQJMSlowJournalAcceptRecovery#testSlowJNAcceptRecoveryAfterNewSegmentCommitted`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.qjournal.client.TestQJMSlowJournalAcceptRecovery#testSlowJNAcceptRecoveryAfterNewSegmentCommitted' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/TestQJMSlowJournalAcceptRecovery.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.lang.AssertionError:`, frame `at org.apache.hadoop.hdfs.qjournal.server.Journal.acceptRecovery(Journal.java:932)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h09m | 1 | 956,233 | 34 | 45,252 | 75,679 | 835,268 | $1.68 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
