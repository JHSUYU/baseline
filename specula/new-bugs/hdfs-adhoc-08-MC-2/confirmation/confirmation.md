# MC-2: Rollback keeps the cached promise, so a JN that stayed up fences the next writer

- **Source**: MC
- **Novelty**: NEW
- **Location**: hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/qjournal/server/Journal.java:1189
- **Status**: REPRODUCED
- **Severity**: Medium
- **Target check**: Journal.java:487 (`Journal.checkRequest`, `java.io.IOException`)
- **Reproduction test**:
  - `repro/test_bugMC-2_rollback_cached_promise.java`, run by `repro/test_bugMC-2_rollback_cached_promise.sh`.
  - Log: `repro/MC-2.log`; raw outputs in `confirmation/MC-2/repro-work/turn2/`.
  - Levels: Level 0 natural race, 56/60 iterations; Level 1 CE steps, 4/4.

## Description
**Root cause.**
- `Journal.doRollback()` (Journal.java:1189-1196) closes `committedTxnId`, renames `previous/`
  back to `current/`, and re-reads VERSION (`storage.refreshStorage()`, HADOOP-17142).
- It never calls `refreshCachedData()` (Journal.java:202-213). `format()` does (:259), and its
  Javadoc says cached data must be reloaded once it "is no longer relevant".
- `JournalNode.doRollback` (JournalNode.java:487-491) runs on the live `Journal` object.
- So a JournalNode that stays up across `hdfs namenode -rollback` keeps its post-upgrade
  `lastPromisedEpoch` in the `PersistentLongFile` cache (PersistentLongFile.java:53-59), while
  its disk holds the pre-upgrade value. `lastWriterEpoch` is left stale the same way.

**Consequence.**
- The next writer can take its epoch from JNs that report the rolled-back value:
  `max(majority) + 1` (QuorumJournalManager.java:232-242).
- The stale JN then rejects every request of that legitimate writer at the target throw,
  `Journal.checkRequest` (Journal.java:486-489). This includes `startLogSegment` after every log
  roll.
- The only writer is left on 2 of 3 JNs. One more JN outage, which a 3-JN quorum is meant to
  tolerate, makes its flush fail with `QuorumException`. The NN then terminates
  (JournalSet.java:395-408, FSEditLog.java:735-748).

## Trigger scenario
All steps are documented operations. HDFSHighAvailabilityWithQJM.md requires all JNs running for
upgrade and rollback (:708-712), allows NN restarts before rollback (:727), and runs the rollback
with both NNs down (:733).

**CE steps** (`MC_hunt_rollback_cache_bfs_w1.out`) as realized by the test:
1. **CE 2-16.** W1, the workload's writer (`TestQuorumJournalManager#setup`: format,
   `recoverUnfinalizedSegments`), holds epoch 1 on j0, j1, j2.
2. **CE 17.** HA upgrade by W1: `doPreUpgrade` + `doUpgrade`, the shared-log calls of
   `FSImage.doUpgrade` (FSImage.java:490, :499). `previous/` promise = 1,1,1.
3. **CE 18.** W1 stops.
4. **CE 19-42.** Two later active NNs, W2 and W3, establish epochs 2 and 3 on j0 and j1. Their
   getJournalState/newEpoch to j2 are still in flight when each stops.
   - Disk promise = 3,3,1; caches = 3,3,1.
5. **CE 44.** `namenode -rollback` with every JN running: `canRollBack` + `doRollback`, the calls
   of `FSImage.doRollback` (FSImage.java:542, :565).
   - Disk = 1,1,1; previous/ removed.
   - **Caches stay 3,3,1.**
6. **CE 43.** j0 restarts. Its new `Journal` reads disk = 1.
7. **CE 45-59.** W4 becomes active.
   - getJournalState is answered by j0 (1) and j2 (1) before j1's reply (3) arrives, so W4 picks
     epoch 2.
   - j1 rejects `newEpoch(2)` ("Proposed epoch 2 <= last promise 3").
   - The quorum j0, j2 succeeds; `setEpoch(2)` goes to every logger.
8. **CE 60-61.** `startLogSegment` → j1 throws
   `IOException: IPC's epoch 2 is less than the last promised epoch 3` at Journal.java:487.

**Order of CE 43/44.** The CE restarts j0 before the rollback. The real code cannot fence anyone
in that order, and the test shows why (`testCeLiteralOrder`, 0/4):
- The restarted j0's `Journal` is created by the rollback's own `canRollBack` RPC.
- Creating it loads the promise through metrics registration:
  `JournalMetrics.create` (Journal.java:172) → JMX `getMBeanInfo`/`updateJmxCache` with
  `lastRecsCleared = true` (MetricsSourceAdapter.java:87, 155-171) → gauge
  `getLastPromisedEpoch` (JournalMetrics.java:117-124).
- Measured: `j0 cache: loaded=true value=3` between `canRollBack` and `doRollback`. So j0 is
  stale too, and W4 picks epoch 4.

In the CE, JNRestart(j0) writes only `cache[j0]`/`faults.restart`, and Rollback writes only
`disk`/`prev`/`faults.rollback`. Order 44 then 43 therefore reaches exactly CE state 44, and the
remaining CE steps are unchanged.

This also answers TV-1: a JN restarted *before* the rollback is stale as well. A JN gives a fresh
answer only if it restarted after the rollback, or never saw the post-upgrade epochs.

## Developer intent
- **Other state is already refreshed.** For a JN that stays up, the developers refresh other
  state after a rollback:
  - `committedTxnId` is closed and reopened lazily (Journal.java:1190-1192).
  - VERSION is re-read (Journal.java:1194-1195, HADOOP-17142/HDFS-15485).

  The epoch caches are not mentioned.
- **The analogous format bug was fixed.** HDFS-3884 ("Journal format() should reset cached
  values", 2012) introduced `refreshCachedData()` for `format`.
- **The existing test misses it.** `TestDFSUpgradeWithHA#testRollbackWithJournalNodes`
  (TestDFSUpgradeWithHA.java:624-703) "deliberately leave[s] the JNs up and running" (:678). It
  only asserts that `committedTxnId` was reset (:685-688). It never starts a writer after the
  rollback.
- **Conclusion.** No comment, doc, or test accepts a JN whose in-memory promise exceeds its own
  rolled-back disk. Fencing the only legitimate writer this way is not designed fencing.

## Reproduction result
Pristine tree 734dd8a67cd. The harness instrumentation was set aside for every run and restored
byte-for-byte afterwards. Commands (log `repro/MC-2.log`):
- A: `bash repro/test_bugMC-2_rollback_cached_promise.sh --l0-iters 20` (fresh build, whole class,
  `MC2_EXPECT=bug`): `Tests run: 5, Failures: 0, Errors: 0`.
- B: `... --no-build --repeat 2 --only 'testCeStepsRestartAfterRollback+testTwoRestartsAfterRollback+testCeLiteralOrder+testControlReplyInTime'`:
  2 × `Tests run: 4, Failures: 0, Errors: 0`.
- C: `... --fix-control --l0-iters 10` (`MC2_EXPECT=fixed`): `Tests run: 5, Failures: 0, Errors: 0`.

**Level 1, CE steps** (deterministic; the spy loggers of `SpyQJournalUtil` hold W2/W3's requests
to j2 and deliver j1's getJournalState reply late). Run A excerpt:
```
MC2: CE 17 Upgrade(1) done; previous/ promise on disk = 1,1,1
MC2: W2 established epoch 2 (its requests to j2 still in flight); WriterStop(2)
MC2: W3 established epoch 3 (its requests to j2 still in flight); WriterStop(3)
MC2: after W3: current/ promise on disk = 3,3,1; caches j0[loaded=true value=3] j1[loaded=true value=3] j2[loaded=true value=1]
MC2: CE 44 Rollback done; current/ promise on disk = 1,1,1, previous/ exists = false,false,false; caches j0[loaded=true value=3] j1[loaded=true value=3] j2[loaded=true value=1]
MC2: CE 43 JNRestart(j0) (after the rollback); j0: no Journal object
MC2: W4 getJournalState lastPromisedEpoch reported by j0,j1,j2 = 1,3,1 (j1's reply arrived after the choice); on-disk current/ promise = 2,1,2
MC2: W4 established epoch 2; j1 newEpoch -> RemoteException(java.io.IOException): Proposed epoch 2 <= last promise 3 ; journal id: test-journal
MC2: W4 startLogSegment(1) returned (quorum reached); j1 -> RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
MC2: W4 wrote txns 1-3 (quorum); j1 journal() -> RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
MC2: after a log roll, W4 startLogSegment(4); j1 -> RemoteException(java.io.IOException): IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
MC2: j1 on-disk promise = 1, j1 cache: loaded=true value=3
MC2: with j2 down, W4 write of txn 4 -> FAILED: org.apache.hadoop.hdfs.qjournal.client.QuorumException: Got too many exceptions to achieve quorum size 2/3. 1 successful responses:
MC2: JN-side stack trace of the IOException j1 returned to W4's startLogSegment (IPC server log):
java.io.IOException: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
	at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)
	at org.apache.hadoop.hdfs.qjournal.server.Journal.startLogSegment(Journal.java:572)
	at org.apache.hadoop.hdfs.qjournal.server.JournalNodeRpcServer.startLogSegment(JournalNodeRpcServer.java:226)
MC2: MC2-RESULT scenario=CE_STEPS_RESTART_AFTER_ROLLBACK w4Epoch=2 reported(j0,j1,j2)=1,3,1 targetFiredOnJ1=true frame=org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) j1FencedAfterRoll=true writeWithJ2Down=FAILED
```
- **Line that proves it.** The `startLogSegment` line: j1 returns the target `IOException` to the
  only live writer.
- **Frame line vs target line.** The `at ...Journal.checkRequest(Journal.java:489)` frame is the
  target throw. javap of the compiled pristine class shows the statement spans 487-489:
  ```
        15: new           #275                // class java/io/IOException
        39: invokespecial #280                // Method java/io/IOException."<init>":(Ljava/lang/String;)V
        42: athrow
      LineNumberTable:  line 486: 0 / line 487: 15 / line 489: 27 / line 490: 43
  ```
- **Expected behavior.** j1 should report its on-disk promise 1 and accept epoch 2, as the fix
  control shows. Instead it holds a cached 3, rejects the writer, and the writer loses the
  one-failure tolerance.

**Level 0, natural race.** Production QJMs, one IPC thread per JN, no spies or failpoints.
- W2 and W3 reach all JNs. j0 and j2 restart after the rollback. A standby tails the log, then
  becomes active as W4.
- Result: 20/20, 18/20, and 18/20 iterations fired (56/60).
- W4's own client RPC trace (TRACE logging, as `TestQuorumJournalManager` enables it) shows the
  same message order as CE states 49-54:
```
MC2: L0 iteration 8: W4's epoch RPCs as its IPC client saw them:
    2026-10-29 02:58:31,625 2850: Call -> j0: getJournalState {}
    2026-10-29 02:58:31,625 2852: Call -> j2: getJournalState {}
    2026-10-29 02:58:31,625 2851: Call -> j1: getJournalState {}
    2026-10-29 02:58:31,626 2850: Response <- j0: getJournalState {lastPromisedEpoch: 1}
    2026-10-29 02:58:31,626 2852: Response <- j2: getJournalState {lastPromisedEpoch: 1}
    2026-10-29 02:58:31,626 2851: Response <- j1: getJournalState {lastPromisedEpoch: 3}
    2026-10-29 02:58:31,627 2852: Call -> j2: newEpoch { ...
MC2: L0 iteration 8: JN-side trace:
java.io.IOException: IPC's epoch 2 is less than the last promised epoch 3 ; journal id: test-journal
	at org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489)
MC2: MC2-L0-RESULT iterations=20 w4Epoch2=18 targetFired=18
```

**Controls** (runs A and B):
```
MC2: between canRollBack and doRollback: j0 cache: loaded=true value=3; on-disk current/ promise = 3,3,1
MC2: MC2-RESULT scenario=CE_ORDER w4Epoch=4 reported(j0,j1,j2)=3,3,1 targetFiredOnJ1=false frame=- j1FencedAfterRoll=false writeWithJ2Down=OK
MC2: MC2-RESULT scenario=CONTROL_REPLY_IN_TIME w4Epoch=4 reported(j0,j1,j2)=1,3,1 targetFiredOnJ1=false frame=- j1FencedAfterRoll=false writeWithJ2Down=OK
MC2: MC2-RESULT scenario=TWO_RESTARTS_AFTER_ROLLBACK w4Epoch=2 reported(j0,j1,j2)=1,3,1 targetFiredOnJ1=true frame=org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:489) j1FencedAfterRoll=true writeWithJ2Down=FAILED
```
Tallies over all bug runs: CE steps 4/4 fired; two-restart variant 4/4; literal CE order 0/4;
control 0/4.

**Fix control** (run C): `refreshCachedData()` added at the end of `doRollback`. The target
message occurs 0 times in the JN logs.
```
MC2: MC2-RESULT scenario=CE_STEPS_RESTART_AFTER_ROLLBACK w4Epoch=2 reported(j0,j1,j2)=1,1,1 targetFiredOnJ1=false frame=- j1FencedAfterRoll=false writeWithJ2Down=OK
MC2: MC2-RESULT scenario=TWO_RESTARTS_AFTER_ROLLBACK w4Epoch=2 reported(j0,j1,j2)=1,1,1 targetFiredOnJ1=false frame=- j1FencedAfterRoll=false writeWithJ2Down=OK
MC2: MC2-L0-RESULT iterations=10 w4Epoch2=10 targetFired=0
```

### Confirmation checklist
1. **Level 0 or Level 1 alone?** Yes.
   - Level 0, a pure black-box variant: public QJM APIs, JN restarts, and natural timing. It fired
     56/60.
   - Level 1, the CE steps: message order controlled by the workload's own `SpyQJournalUtil`
     spies. It fired 4/4.
   - No Level 2 state injection and no source patch in any bug run.
2. **Level 2/3 justification.** Not applicable; neither was used. The only Journal-state reads
   are read-only `Whitebox` diagnostics.
3. **Consumer that sees the wrong outcome.**
   - The active writer's `QuorumJournalManager.startLogSegment` (QuorumJournalManager.java:430-437)
     receives j1's target `IOException` on every segment.
   - `IPCLoggerChannel` (:362-370) marks j1 out of sync and retries only at the next roll, where
     `startLogSegment` is rejected again.
   - `QuorumOutputStream`/`AsyncLoggerSet.waitForWriteQuorum` (:124-148) then fails once one more
     JN is down. The NN would terminate (JournalSet.java:408, FSEditLog.java:748). This was
     observed: `writeWithJ2Down=FAILED`; the control shows `OK`.
4. **Permanent, or resolved/masked downstream?** Permanent for the writer's tenure.
   - j1 re-reads its disk only on restart. A later writer fixes it only if j1's reply is in that
     writer's getJournalState majority.
   - The client's re-sync at log roll does not resolve it; shown by
     `j1FencedAfterRoll=true`.
   - The 2/3 quorum hides only the first-order write failure. It does not hide the consequence:
     the cluster's single-fault tolerance is gone, as the j2-outage step demonstrates.
   - Not MASKED.

## Recommendation
- **Fix.** In `Journal.doRollback()` (Journal.java:1189-1196), call `refreshCachedData()` after
  `storage.refreshStorage()`, inside the same synchronized method. This rebuilds
  `lastPromisedEpoch`, `lastWriterEpoch` and `committedTxnId` from the restored `current/`. The
  fix control validates exactly this change.
  - Also reset the in-progress edits cache (`this.cache = createCache()`), as `format()` does at
    :258. That part was not exercised here.
- **Regression test.** Extend `TestDFSUpgradeWithHA#testRollbackWithJournalNodes`, or adopt the
  QJM-level `testCeStepsRestartAfterRollback`. After a rollback with the JNs left running, assert
  that each JN's `getJournalState().getLastPromisedEpoch()` equals its rolled-back on-disk value.
  Also assert that a new writer can start a segment on all three JNs.
- **Operator workaround** until fixed: restart every JournalNode after `namenode -rollback`,
  before starting the NameNodes.
- **Model note** (no repair request; the bug reproduces). The spec's JNRestart leaves the cache
  unloaded until the next epoch RPC. The code loads it when the `Journal` is created by the first
  RPC after a restart, which is the rollback's `canRollBack` when the restart comes first. So the
  CE's literal order 43→44 is not realizable; the commuted order 44→43 is.
