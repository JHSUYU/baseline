# MC-1: A failed epoch attempt's orphan promise fences the next established writer

- **Source**: MC
- **Novelty**: NEW
- **Status**: REPRODUCED
- **Severity**: Medium
- **Location**: hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/client/QuorumJournalManager.java:242
- **Target fired**: `org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)`, the `throw new IOException(...)` statement at `Journal.java:487-489` (guard at `:486`), exception type `java.io.IOException`
- **Reproduction test**: `repro/test_bugMC-1_orphan_promise.sh` (driver) + `repro/test_bugMC-1_orphan_promise.java` (JUnit variant of `TestQuorumJournalManager#testSingleWriter`). Escalation level **1**: faults and timing come from the codebase's own test utilities; no state injection, no source patch.
- **Evidence logs**: `repro/MC-1-logs/run2-final.console.log`, `repro/MC-1-logs/run2-final/run{1,2,3}/`, and the first run in `repro/MC-1-logs/run2-attempt1*`.

## Description

`QuorumJournalManager.createNewUniqueEpoch` picks `myEpoch = 1 + max(lastPromisedEpoch)` over whichever
majority answers `getJournalState` first (`QJM:232-242`, `QuorumCall.waitFor` returns at a majority of
successes). It then accepts any majority of `newEpoch` successes and calls `loggers.setEpoch(myEpoch)`
on **every** logger (`QJM:243-247`, `AsyncLoggerSet.java:61-68`). That includes a JN that never answered,
or that rejected `newEpoch` with "Proposed epoch X <= last promise Y" (`Journal.java:347-349`).

A JN's promise is persisted as soon as it accepts `newEpoch` (`Journal.java:352`), even when the
proposer then fails to reach a quorum and dies. Two such failed attempts can leave a minority JN (JN0)
with an *orphan* promise that is higher than the majority's. If the next writer does not hear JN0's
`getJournalState` in time, it establishes an epoch below JN0's promise. From then on, every RequestInfo
RPC it sends to JN0 (`startLogSegment`, `journal`, `heartbeat`, `prepareRecovery`, `acceptRecovery`,
`finalizeLogSegment`) fails the target check `reqInfo.getEpoch() < lastPromisedEpoch.get()` at
`Journal.java:486-489`.

The check exists to fence *older* writers. Here it fences the newest and only live writer, for its
whole term:

- the persisted promise survives a JN0 restart;
- IPCLoggerChannel's "rejoin at the next log roll" fails at every roll;
- JournalNodeSyncer never touches epochs.

The writer runs on 2 of 3 JNs with no fault margin. One more JN failure makes the NameNode's
`JournalSet` terminate the NameNode (`JournalSet.java:394-408`), although a 3-JN quorum is meant to
tolerate that failure.

## Trigger scenario

Matches the counterexamples' step order. Epochs are the CE's plus one because the copied workload
setup first establishes epoch 1 for the workload's writer, which then stops; writers never overlap.

1. **Attempt A** (a NameNode becoming active): `getJournalState` returns {1,1,1}, so it proposes 2.
   JN0 handles `newEpoch(2)` and persists promise 2. The `newEpoch` requests to JN1 and JN2 are never
   delivered: lost (loss-only CE, `QuorumException`, then `FSEditLog.recoverUnclosedStreams(true)`
   calls `terminate(1)`), or the NameNode stops first (primary and stop-only CE: `WriterStop`).
   Promises are now JN0=2, JN1=1, JN2=1.
2. **Attempt B**: the same; `getJournalState` sees {2,1,1} and proposes 3. Promises are now
   JN0=3, JN1=1, JN2=1.
3. **Writer C** (the next NameNode): JN0's `getJournalState` request is lost (primary CE), or its reply
   arrives after JN1's and JN2's (loss-only and stop-only CE). So `myEpoch = 1 + max(1,1) = 2`.
   `newEpoch(2)` succeeds on JN1 and JN2. On JN0 it is lost (primary and loss-only) or rejected with
   "Proposed epoch 2 <= last promise 3" (stop-only). `setEpoch(2)` is applied to JN0's channel anyway.
4. C's first RPC to JN0 (`startLogSegment(1)` in the workload) fails at `Journal.checkRequest`:
   "IPC's epoch 2 is less than the last promised epoch 3". The same happens for every later RPC.

## Developer intent

- HDFS-3077 design discussion, Todd Lipcon, 2012-09-27: "if any request comes with a higher epoch than
  lastPromisedEpoch, then the JN accepts the request and also updates lastPromisedEpoch. This allows a
  JournalNode to join back into the quorum properly even if it was down when the writer became
  active." Here JN0 was unreachable when C became active, but its orphan promise is above C's epoch,
  so it can never rejoin.
- `Journal.java:335-337` javadoc of `newEpoch`: the JN refuses after "a promise to **another writer**
  with a higher epoch". `QJM:222-223`: "Fence any previous writers, and obtain a unique epoch number".
  Epoch 2 is used both by dead attempt A (at JN0) and by writer C.
- `IPCLoggerChannel.java:363-366` "Will try to write to this JN again after the next log roll" and
  `TestIPCLoggerChannel.java:181-183` "After a roll, sending new edits should not fail": a lagging JN
  is meant to rejoin at the next roll. With the orphan promise it never does.
- `TestEpochsAreUnique#testSingleThreaded` injects `getJournalState` and `newEpoch` faults but only
  asserts that successful epochs increase. It never checks that the new writer can use every live JN.
- No developer comment, test or issue accepts a newest writer being fenced by an orphan promise.

## Reproduction result

Command:

```
REPEAT=3 timeout 55m repro/test_bugMC-1_orphan_promise.sh \
  .specula-output/confirmation/MC-1/worktree  repro/MC-1-logs/run2-final
```

The driver stashes the harness instrumentation it was handed in the worktree, builds the
**pristine** tree at 734dd8a67cd offline (JDK 17.0.21, Maven 3.9.15), runs the test class 3 times,
and restores the instrumentation afterwards.

```
HEAD=734dd8a67cd6df56b59ff75aa43de57834a0d248
git status --porcelain -- hadoop-hdfs-project/hadoop-hdfs/src/main (must be empty):
run 1: Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 10.86 s -- in org.apache.hadoop.hdfs.qjournal.client.TestSpeculaMC1OrphanPromise
run 2: Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 10.59 s -- in org.apache.hadoop.hdfs.qjournal.client.TestSpeculaMC1OrphanPromise
run 3: Tests run: 7, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 11.11 s -- in org.apache.hadoop.hdfs.qjournal.client.TestSpeculaMC1OrphanPromise
```

Each reproduction method passes only if JN0 rejected the newest writer at the target with the exact
message and frame. Each control passes only if JN0 served every RPC and the NameNode survived.

Primary counterexample (`testPrimaryCounterexample`, `MC_hunt_orphan_promise_bfs_w1.out`):

```
[MC-1] attempt A: writer stopped after JN0 handled newEpoch; promises JN0=2 JN1=1 JN2=1
[MC-1] attempt B: writer stopped after JN0 handled newEpoch; promises JN0=3 JN1=1 JN2=1
[MC-1] newest writer established epoch 2 = 1 + max(JN1, JN2); promises JN0=3 JN1=2 JN2=2
[MC-1] newest writer -> JN0 startLogSegment(1): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1]   JN0 startLogSegment(1): TARGET FIRED: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal | frame: at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) <- at org.apache.hadoop.hdfs.qjournal.server.Journal.startLogSegment(Journal.java:572) <- at org.apache.hadoop.hdfs.qjournal.server.JournalNodeRpcServer.startLogSegment(JournalNodeRpcServer.java:226)
[MC-1] first target throw, JN0 server-side stack (RemoteException java.io.IOException):
    IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
    at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)
    at org.apache.hadoop.hdfs.qjournal.server.Journal.startLogSegment(Journal.java:572)
    at org.apache.hadoop.hdfs.qjournal.server.JournalNodeRpcServer.startLogSegment(JournalNodeRpcServer.java:226)
[MC-1]   JN0 journal(firstTxId=1): TARGET FIRED: ... | frame: at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) <- at org.apache.hadoop.hdfs.qjournal.server.Journal.checkWriteRequest(Journal.java:515) <- at org.apache.hadoop.hdfs.qjournal.server.Journal.journal(Journal.java:397)
[MC-1]   JN0 finalizeLogSegment(1-3): TARGET FIRED: ... | frame: at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) <- at org.apache.hadoop.hdfs.qjournal.server.Journal.heartbeat(Journal.java:476) <- at org.apache.hadoop.hdfs.qjournal.server.JournalNodeRpcServer.heartbeat(JournalNodeRpcServer.java:219)
[MC-1]   JN0 startLogSegment(4): TARGET FIRED: ... | frame: at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) <- at org.apache.hadoop.hdfs.qjournal.server.Journal.startLogSegment(Journal.java:572) <- ...
[MC-1] JN0 restarted; promises JN0=3 JN1=2 JN2=2
[MC-1] newest writer -> JN0 startLogSegment(5): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1] JN1 stopped (one JournalNode failure)
[MC-1] newest writer -> JN0 startLogSegment(6): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1] CONSEQUENCE: NameNode terminated (ExitUtil status 1): Error: starting log segment 6 failed for required journal (JournalAndStream(mgr=QJM to [127.0.0.1:33207, 127.0.0.1:45173, 127.0.0.1:45383], stream=null))
[MC-1] cause logged by JournalSet:
    ... ERROR namenode.FSEditLog (JournalSet.java:mapJournalsAndReportErrors(398)) - Error: starting log segment 6 failed for required journal (...)
    org.apache.hadoop.hdfs.qjournal.client.QuorumException: Got too many exceptions to achieve quorum size 2/3. 1 successful responses:
    127.0.0.1:45383: null [success]
    2 exceptions thrown:
    127.0.0.1:33207: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
    127.0.0.1:45173: Call From ... to localhost:45173 failed on connection exception: java.net.ConnectException: Connection refused; ...
[MC-1] RESULT primary CE: target fired 6 times for the newest writer (epoch 2, JN0 promise 3)
```

The JN0 IPC server's own log (`org.apache.hadoop.ipc.Server`) shows the same throw:

```
INFO  ipc.Server (Server.java:logException(3360)) - IPC Server handler 2 on default port 46233, call Call#94 Retry#0 org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocol.startLogSegm...
java.io.IOException: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
	at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)
	at org.apache.hadoop.hdfs.qjournal.server.Journal.startLogSegment(Journal.java:572)
	at org.apache.hadoop.hdfs.qjournal.server.JournalNodeRpcServer.startLogSegment(JournalNodeRpcServer.java:226)
```

Frame 489 is the target throw at line 487. `javap -c -l` of the pristine `Journal.class` shows the
guard `lcmp; ifge 43` at line 486; the `throw` statement (`new IOException` at bci 15) starts at line
487; the message operand and `<init>`/`athrow` (bci 27-42) are attributed to line 489:

```
    LineNumberTable:
      line 486: 0
      line 487: 15
      line 489: 27
      line 490: 43
```

Stop-only counterexample (`testStopOnlyCounterexample`, `MC_hunt_rollback_cache_bfs_w8.out`: no message lost for writer C; JN0's reply is merely late):

```
[MC-1] newest writer -> JN0 newEpoch(2): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): Proposed epoch 2 <= last promise 3 ; journal id: test-journal
[MC-1] JN0's getJournalState reply arrived late: lastPromisedEpoch=3
[MC-1] newest writer established epoch 2; promises JN0=3 JN1=2 JN2=2
[MC-1] newest writer -> JN0 startLogSegment(1): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
```

Loss-only counterexample (`testLossOnlyCounterexample`, `MC_s1_lossonly_bfs_w1.out`):

```
[MC-1] attempt A: epoch attempt failed: Got too many exceptions to achieve quorum size 2/3. 1 successful responses:
[MC-1] attempt A: writer stopped; promises JN0=2 JN1=1 JN2=1
[MC-1] attempt B: writer stopped; promises JN0=3 JN1=1 JN2=1
[MC-1] newest writer established epoch 2; promises JN0=3 JN1=2 JN2=2
[MC-1] newest writer -> JN0 startLogSegment(1): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
```

Workload exactly as `testSingleWriter` runs it, then the failover (`testWorkloadThenFailover`): the
newest writer's recovery RPCs to JN0 already hit the target:

```
[MC-1] newest writer -> JN0 prepareRecovery(4): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1] newest writer -> JN0 acceptRecovery: FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1] RESULT workload-then-failover: target fired 6 times for the newest writer (epoch 2, JN0 promise 3)
```

Supplementary realization with real JournalNode outages only (`testPrimaryCounterexampleRealOutages`):
JN1 and JN2 are stopped between `getJournalState` and `newEpoch` (timed by a spy) and restarted; JN0
is down while C establishes its epoch and then restarted. No request is failed by a mock:

```
[MC-1] attempt B: JN1, JN2 back up; promises JN0=3 JN1=1 JN2=1
[MC-1] JN0 down while the newest writer establishes its epoch
[MC-1] JN0 back up; newest writer epoch 2; promises JN0=3 JN1=2 JN2=2
[MC-1] newest writer -> JN0 startLogSegment(1): FAILED org.apache.hadoop.ipc.RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
[MC-1] CONSEQUENCE: NameNode terminated (ExitUtil status 1): Error: starting log segment 5 failed for required journal (...)
```

Controls (same steps, one ingredient removed). JN0 serves every RPC, `TargetSafe` holds, and the same
single JN failure is tolerated:

```
[MC-1] CONTROL timely-reply: JN0 served every RPC of epoch 4; JN1 loss tolerated
[MC-1] CONTROL no-orphan: JN0 served every RPC of epoch 2; JN1 loss tolerated
```

Expected (correct) behavior: the newest established writer is accepted by every live JN, as in the
controls. JN0 should not throw the target for it, and losing one JN should leave a quorum.

### Bug-confirmation checklist

1. **Level 0 or Level 1 alone?** Yes, Level 1. The trigger uses the real QJM API
   (`recoverUnfinalizedSegments`, `startLogSegment`, `QuorumOutputStream.flush`, `finalizeLogSegment`)
   against real in-process JournalNodes (`MiniJournalCluster`). The CE's faults (request loss, writer
   stop, late reply) are realized only with the codebase's own test utilities: `SpyQJournalUtil` spies,
   `TestQuorumJournalManagerUnit.futureThrows`, `SettableFuture`, `MiniJournalCluster` stop/restart. No
   state injection, no source patch, the target method is untouched, and the guard's operands are
   only changed by the real `newEpoch`/`checkRequest` code (the test only reads `last-promised-epoch`).
2. Not applicable (no Level 2 or 3).
3. **Consumer that observes a wrong outcome**:
   - The writer, `QuorumJournalManager.startLogSegment` (`QJM:430-440`) and `QuorumOutputStream.flushAndSync`
     through `AsyncLoggerSet.waitForWriteQuorum` (`ALS:119-148`). Every RPC to JN0 is rejected for the
     whole term, and JN0 receives no segment of this writer.
   - The NameNode, `JournalSet.mapJournalsAndReportErrors` (`JournalSet.java:387-408`). With one more JN
     down it called `terminate(1)` live (`ExitUtil status 1`); the controls survive the same failure.
4. **Permanent?** Yes, for the writer's whole term. The promise is persisted: a JN0 restart left
   JN0=3 and the target fired again at `startLogSegment(5)`. IPCLoggerChannel's roll-rejoin fails at
   every roll (segments 1, 4, 5, 6). JournalNodeSyncer has no epoch logic, and its backfill is gated on
   `committedTxnId`, which this writer cannot advance on JN0. The quorum hides the problem only while
   JN1 and JN2 both stay up; the NameNode termination shows the harm is real. Only a later failover
   whose `getJournalState` majority includes JN0 clears it. Not MASKED.

## Recommendation

Fix in `QuorumJournalManager.createNewUniqueEpoch` (`QJM:232-247`) and `AsyncLoggerSet.setEpoch`
(`ALS:61-68`):

1. Do not adopt an epoch that a reachable JN has already out-promised. When `newEpoch(myEpoch)` gets a
   majority but a JN rejects it with "Proposed epoch X <= last promise Y", or a late `getJournalState`
   reply shows a promise ≥ myEpoch, retry `createNewUniqueEpoch` (bounded) with
   `max(all observed promises) + 1` before `setEpoch`. Carrying the promised epoch in the rejection
   (a field in the response or exception) makes this robust. This also restores uniqueness: no two
   writers propose the same epoch.
2. Optionally wait a short grace period for all `getJournalState` replies (not just a majority) before
   choosing `myEpoch`. This narrows the late-reply variant.
3. For a JN that was unreachable during establishment and later rejects with "IPC's epoch E is less
   than the last promised epoch P" (primary CE), have the writer re-establish a higher epoch at the next
   segment boundary (no segment in progress), so the JN rejoins as the HDFS-3077 design intends.
   Alternatively, surface it as a loud, actionable error and metric instead of a silent
   per-roll warning.
4. Add a regression test like `TestSpeculaMC1OrphanPromise`: two failed attempts that reach only JN0,
   then a writer that misses JN0's `getJournalState`. Assert that JN0 accepts the new writer and that
   the writer survives losing one more JN.
