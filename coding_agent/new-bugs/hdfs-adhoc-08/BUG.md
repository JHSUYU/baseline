# hdfs-adhoc-08: The writer can establish an epoch below a leftover promise held by a slow JN, and QJM never re-proposes, so that healthy JN is excluded for the writer's lifetime and the NN can no longer survive one more JN failure.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:487`, `Journal.checkRequest(RequestInfo)`, throws `java.io.IOException` when `reqInfo.getEpoch() < lastPromisedEpoch.get()`
- Starting test: `org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Two failed writer takeover attempts whose newEpoch RPCs to JN0/JN1 are lost leave JN2 with promise 3 while JN0/JN1 stay at 1. The next writer gets getJournalState answers only from JN0/JN1 (JN2 is slow), so it picks epoch 2 and wins a quorum. JN2 then rejects every request from that writer, and stopping JN0 makes writes fail even though JN1 and JN2 are up.

**Why (root cause in the source):** QuorumJournalManager.createNewUniqueEpoch (QuorumJournalManager.java, waitForWriteQuorum over getJournalState) takes max(lastPromisedEpoch) over only the first majority to answer, and it ignores the minority's 'Proposed epoch 2 <= last promise 3' rejection of newEpoch without re-proposing. From then on Journal.checkRequest (Journal.java:486-489) rejects every IPC from the only live writer, for that writer's whole lifetime. The check is enforcing its invariant correctly, but no newer writer exists: the higher promise is left over from aborted attempts, and the client-side epoch selection lets the legitimate writer run with a JN it can never use. The faults (lost RPCs, a slow JN) are allowed. The effect is lost fault tolerance (2 of 3 usable JNs) until the next epoch change. A further single JN failure then aborts the active NN with a JN majority alive. This heals at the next failover, and reaching it needs an unusual fault pattern.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The check fences writers whose epoch is older than one the JN promised to a newer writer. Here no newer writer exists. JN2's higher promise is left over from failed (aborted) newEpoch attempts, and the real, only active writer W2 got a lower epoch just because JN2 was slow and createNewUniqueEpoch computes max(lastPromisedEpoch) over only the first majority that answers getJournalState. The epoch-assignment coordination is supposed to produce an epoch above every outstanding promise, so that the new writer fences everything older and is accepted by every live JN. Instead it produces an epoch that a healthy JN rejects for the writer's whole lifetime, since the writer never re-proposes an epoch while it is active. In a real deployment (NN failover attempts that time out on newEpoch, a JN that answers slowly because of GC or disk stalls) one JN out of three ends up excluded for good without anyone noticing: the active NN runs with zero tolerance for JN faults, and losing any one more JN makes the active NameNode abort (edit log sync fails, 'flush failed for required journal'), even though a majority of JNs is up. Also, JN2's edits for the new segments are missing, so it lags until the next epoch change.

**Execution (agent):** MiniJournalCluster with 3 JNs (JN0, JN1, JN2), QJMs with Mockito-spied IPCLoggerChannels. (1) Writer W1 formats, gets epoch 1 on all JNs, writes and finalizes segment 1-3, then goes away (NN crash or failover). (2) Attempt A1 to become writer (e.g. the next NN): getJournalState from all JNs -> max promise 1 -> proposes epoch 2; newEpoch(2) to JN0 and JN1 is lost or times out (injected failed futures), only JN2 receives it and promises 2. A1 has no quorum and fails. (3) Retry A2: getJournalState to JN0 is lost, JN1 (1) and JN2 (2) answer -> epoch 3; newEpoch(3) again reaches only JN2 (JN2 promise = 3), A2 fails. Now JN0=1, JN1=1, JN2=3, all JNs are up and nobody writes. (4) Writer W2, the only writer in the system, starts. JN2 is only slow to answer getJournalState (its reply is delayed until after recovery). QuorumJournalManager.createNewUniqueEpoch -> AsyncLoggerSet.waitForWriteQuorum returns as soon as a majority (JN0, JN1) has answered, so W2 picks epoch max(1,1)+1 = 2, below JN2's promise 3. newEpoch(2) succeeds on JN0 and JN1 (a quorum) and is rejected by JN2 ('Proposed epoch 2 <= last promise 3'). W2 is now the established writer with epoch 2. (5) Every later W2 request to JN2 (prepareRecovery, startLogSegment(4), journal ...) fails in Journal.checkRequest with java.io.IOException 'IPC's epoch 2 is less than the last promised epoch 3' (the check at Journal.java:487). W2 keeps writing only to JN0 and JN1. (6) JN0 is stopped. JN1 and JN2, a majority, are alive, but W2's next flush fails with a QuorumException, because JN2 keeps rejecting epoch 2. The test asserts that the write should succeed and fails there; the JN-side stack traces with Journal.checkRequest appear in the test output.

**Stack frame (agent):** at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)  [this is the 'throw new IOException("IPC's epoch " ... )' statement that starts at line 487 and spans 487-489; javac attributes the IOException constructor call to line 489 (javap LineNumberTable: line 487 -> pc 15, line 489 -> pc 27, invokespecial IOException.<init> at pc 39). The exception message is "IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal" and it is thrown from Journal.prepareRecovery, startLogSegment and journal calls of the new writer]

## Reproduction

- Test: `org.apache.hadoop.hdfs.qjournal.client.TestQJMEpochFromPartialQuorum#testSlowJNWithHigherPromiseRejectsOnlyWriter`
- Command: `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest='org.apache.hadoop.hdfs.qjournal.client.TestQJMEpochFromPartialQuorum#testSlowJNWithHigherPromiseRejectsOnlyWriter' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/TestQJMEpochFromPartialQuorum.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `java.io.IOException: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal`, frame `at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 508,256 | 26 | 21,680 | 49,423 | 437,127 | $0.92 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
