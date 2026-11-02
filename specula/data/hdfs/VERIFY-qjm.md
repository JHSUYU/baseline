# Independent verification of Specula's QJM findings (hdfs-adhoc-07, -08, -09, -10)

Reviewer: an independent agent, 2026-11-02. Every step below was checked against the source in
/bulk/specula-adhoc/src/hadoop (base 734dd8a67cd), not taken from the run's write-ups.
Paths: `J` = `hadoop-hdfs/.../qjournal/server/Journal.java`, `IPC` = `qjournal/client/IPCLoggerChannel.java`,
`QJM` = `qjournal/client/QuorumJournalManager.java`, `ALS` = `qjournal/client/AsyncLoggerSet.java`,
`FJM` = `server/namenode/FileJournalManager.java`.

Upstream check: `git log 734dd8a67cd..origin/trunk` on qjournal/, FileJournalManager, JournalSet, FSEditLog,
FSImage, FSNamesystem, EditLogTailer and hdfs/util lists only HDFS-17980, HADOOP-19951, the HADOOP-19668/19670
revert and HDFS-17924. None of them touches the code paths below, so nothing here is fixed on trunk.

Candidates: every REPRODUCED model-checking (MC-*) finding whose violated invariant is TargetSafe, plus the CR-*
findings whose reproduction throws the target exception at the target line (09/CR-3 and 09/CR-5 do; frame
`Journal.checkRequest(Journal.java:504)` in `repro/test_bugCR-3_rollback_late_rpc.base.log` and
`repro/test_bugCR-5_purge_stale_inprogress.output.txt`). Not candidates: 09/MC-2 (ENV_LIMITED), 08/CR-6
(ENV_LIMITED, never fires the target), and the FALSE POSITIVE CR-* findings.

## Summary

| case/ID | verdict | reason class | confidence |
| --- | --- | --- | --- |
| 07/MC-1 | **KEEP** | real data loss: a purge hides a restarted JN's live segment | medium-high |
| 09/CR-5 | DROP | duplicate of 07/MC-1 (same root cause) | high |
| 08/MC-1 | **KEEP** | an orphan promise fences the newest writer on one JN for its whole term | medium |
| 08/MC-2 | **KEEP** | `doRollback` keeps a stale cached `lastPromisedEpoch` | medium |
| 10/MC-1 | DROP | by design (HDFS-3726); symptom known (HDFS-17563); low severity | high |
| 10/MC-2 | DROP | by design (HDFS-3726); low severity (variant of 10/MC-1) | high |
| 10/MC-3 | DROP | low severity (a real minor defect at J:588-603; the L518 effect heals at the next roll) | medium |
| 10/MC-4 | DROP | by design (no ordering of IPC calls after a client timeout); low severity | high |
| 10/MC-5 | DROP | by design (a disk fault excludes the JN until the next roll); low severity | high |
| 07/MC-4 | DROP | low severity (false-alarm assertion; the syncer and purge heal it) | medium |
| 09/MC-1 | DROP | known: HDFS-5058 (same mechanism, Won't Fix) | medium |
| 09/MC-3 | DROP | trigger not realistic (a dead NameNode's RPC arrives after a rolling rollback); bounded impact | medium |
| 09/CR-3 | DROP | trigger not realistic (an RPC delayed across a whole offline rollback); bounded impact | medium |

---

## hdfs-adhoc-07 — `Journal.acceptRecovery`, "Cannot replace segment" (J:923-932, explicit `throw new AssertionError`)

### 07/MC-1 — KEEP (critical; confidence medium-high). Representative of 09/CR-5.

**Root cause.** `FJM.purgeLogsOlderThan` (FJM:199-213) renames to `.stale` every in-progress log that starts at or
above `minTxIdToKeep` and is not `currentInProgress` (`isStaleInProgressLog`, FJM:215-223; added by HDFS-8178,
commit e3c01e174c8, 2019). On a JournalNode, `currentInProgress` is in-memory state set only by
`FJM.startLogSegment` (FJM:124). After a JN restart it is null until the writer's next `startLogSegment`, so the JN's
copy of the **live** segment, including transactions it already acknowledged, counts as "stale". An HA purge
almost always meets `firstTxId >= minTxIdToKeep`, because `minTxIdToKeep` trails the current segment by about 1M
txns or more (NNStorageRetentionManager). FSEditLog.purgeLogsOlderThan (FSEditLog:1526-1530) only asserts
`minTxIdToKeep <= curSegmentTxId`.

**Code path (07 counterexample):**
1. Writer w1 sends batch txn 2 to j0, j1 and j2. j0 writes it, acks, and crashes. j1 acks, so the batch reaches a
   quorum and txn 2 is acknowledged. j2 never receives it, because w1 stops.
2. A checkpoint purge runs on j0's channel. `IPC.purgeLogsOlderThan` (IPC:499-503) builds the RequestInfo at run time
   (`createReqInfo`, IPC:287-291) with `committedTxId=1`, since the quorum is not yet seen. The IPC connect retries
   (default 10 x 1 s) deliver it after j0 restarts. On j0: `J.purgeLogsOlderThan` (J:688-696) →
   `JNStorage.purgeDataOlderThan` (JNStorage:174-179) → FJM:199-213 marks `edits_inprogress_1` (holding txn 2) as
   `.stale`.
3. The new writer w2 recovers. `QJM.recoverUnclosedSegment` (QJM:311-411) takes the first majority of `prepareRecovery`
   replies: j0 has no segment (`getLogFile(1)` misses the renamed file) and j2 has [1,1]; j1 answers late. The
   comparator picks [1,1]. The committed-txid sanity check (QJM:378-390) looks only at responders, and both report
   committed=1, so it passes.
4. `acceptRecovery([1,1])` reaches j1 too. j1's `committedTxnId=2` lies in its [1,2] but not in [1,1], so it throws
   the **target AssertionError at J:926** (frame J:932; seen in `confirmation/MC-1/logs/test-da-run1-output.txt` and
   the -ea runs). j0 and j2 accept and finalize [1,1], so the accept/finalize quorum succeeds.
5. With assertions disabled, the default for daemons, `QuorumCall.checkAssertionErrors` (QuorumCall:243-251) ignores
   j1's AssertionError. Segment 1 is finalized as [1,1] on a majority, and **acknowledged txn 2 is permanently lost**:
   the test reads back only txid 1.

**Reproduction realism.** It starts from the workload's MiniJournalCluster/QJM setup. The faults are one JN
crash/restart, one purge, a second writer, and per-channel task delays through the `@VisibleForTesting` executor hook
(a slow link). Nothing writes the guard's operands or JN files. A negative control (the purge reaches j0 before the
crash) keeps txn 2. The `PURGE_ISSUED_AFTER_CRASH` variant shows the bug without holding j0's channel.

**Is it a bug?** Yes. A JN discards (hides) transactions it acknowledged, which breaks the quorum-durability
guarantee QJM relies on. HDFS-8178 meant to move aside leftovers of *aborted* segments, not the current segment of a
JN that restarted. No test in src/test covers a purge after a JN restart inside an open segment.

**Severity.** Critical when it occurs: silent loss of quorum-acknowledged namespace edits, with default config.
09/CR-5 shows a second path with the same cause. When a majority's copies are hidden, recovery finds no segment and
runs no prepare-time check, the next writer reuses the txids, and every JN rejects it at J:504. Likelihood is low:
it needs a JN restart inside the segment, a purge before the next roll, and a failover whose recovery quorum
misses the remaining holders. All of these faults are routine (JN restart, hourly checkpoint, failover, slow JN).
No JIRA found, and the code is unchanged on trunk.

### 09/CR-5 — DROP (duplicate of 07/MC-1). Confidence high.
It has the same root cause (FJM:215-223 with a null `currentInProgress` after a JN restart). It differs only in the
symptom: the new writer starts below the committed txid and is rejected at J:504 (frame seen in the repro output).
Count it once, under 07/MC-1.

### 07/MC-4 — DROP (low severity). Confidence medium.
**Path:** `IPC.acceptRecovery` (IPC:541-546) builds its RequestInfo when the queued task runs (IPC:287-291). On a slow
j1, w2's queued `prepareRecovery`/`acceptRecovery([1,1])` run after w2 committed txn 2 of segment 2, so they carry
`committedTxId=2` (`ALS.setCommittedTxId`, ALS:75-79). `J.checkRequest` stores it (J:510). j1's old [1,2] holds the
fenced writer's uncommitted txn 2, so J:923-924 compares txids of different segments and throws at J:926 (a false
alarm). The faults are realistic: delays only.
**Severity:** j1 skips the truncation of segment 1 and keeps an unfinalized `edits_inprogress_1`, so
`finalizeLogSegment(1,1)` there fails (JournalOutOfSync). The writer and readers continue on the majority. The
manifest error affects only `inProgressOk=true` reads starting at txid ≤ 2. JournalNodeSyncer (on by default)
downloads the finalized segment 1, and a later purge removes the leftover. No data loss and no crash; this is
reduced redundancy for one old segment. It is a real imprecision in `createReqInfo` binding, but not severe.

---

## hdfs-adhoc-08 — `Journal.checkRequest`, `reqInfo.getEpoch() < lastPromisedEpoch.get()` (J:486-489)

### 08/MC-1 — KEEP (high: loss of JN redundancy that does not heal for the writer's whole term). Confidence medium.

**Root cause.** `QJM.createNewUniqueEpoch` (QJM:226-249) sets `myEpoch = 1 + max(lastPromisedEpoch)` over only the first
majority of `getJournalState` replies (`waitForWriteQuorum` returns at a majority of successes, ALS:118-127 →
QuorumCall:165-177). After a majority of `newEpoch` successes it establishes the epoch on all loggers (ALS:61-68). A
JN persists a promise before the proposer knows the outcome (J:347-352). Nothing ever re-proposes a higher epoch,
even when `newEpoch` on that JN fails with "Proposed epoch E <= last promise P" (J:347-349).

**Path:**
1. Attempt A: `getJournalState` sees promise 1 on all JNs and proposes 2. Only JN0 executes `newEpoch(2)`
   (J:352). It is lost on JN1 and JN2 (they go down, or the NN stops), so the attempt fails with QuorumException.
2. Attempt B: the majority includes JN0 (promise 2), so it proposes 3. Again only JN0 accepts. JN0 promise = 3, JN1 =
   JN2 = 1.
3. Writer C: JN0's `getJournalState` reply is late (JN0 briefly down or slow), so maxPromised over {JN1,JN2} = 1
   and myEpoch = 2. `newEpoch(2)` succeeds on JN1 and JN2, fails on JN0 (2 <= 3), and the quorum is met. The epoch is
   set on all three loggers.
4. Every RPC from C to JN0 (startLogSegment, journal, heartbeat, prepare/accept, finalize) hits `2 < 3` and throws
   the **target IOException at J:487-489**. The frame is seen in the repro logs `repro/MC-1-logs`.
5. JN0's promise is persistent, so a JN0 restart does not help. Each roll's `startLogSegment` fails the same way, so
   the HDFS-3726 rejoin never happens. C runs on 2 of 3 JNs for its whole term. One more JN failure gives
   QuorumException, and the NN terminates through JournalSet/FSEditLog. The repro shows this; controls without
   the orphan promise survive the same failure.

**Reproduction realism.** It uses SpyQJournalUtil spies, `futureThrows` and SettableFuture (lost or late replies),
and also a variant with real JN outages only (`testPrimaryCounterexampleRealOutages`). No operand is written; the
promises are only read.

**Bug or design?** The fence itself is correct Paxos behaviour. The defect is liveness: the established writer is
legitimate and newest, yet one acceptor rejects it permanently, and QJM has no path to learn or exceed that promise.
"IPC's epoch X is less than the last promised epoch Y" against a live active NN is reported in the field (Cloudera
community threads), but no Apache JIRA was found.
**Severity/realism.** It needs two consecutive failed epoch attempts that reach only one JN, plus a late reply. That
is uncommon but made only of crash and lost-RPC faults, with default configuration. Impact: zero fault tolerance for
the rest of the active NN's term (possibly weeks), and one more JN fault crashes the NN. It is not self-healing
until the next failover happens to include JN0 in the `getJournalState` majority.

### 08/MC-2 — KEEP (high: same impact as 08/MC-1, after a documented operator procedure). Confidence medium.

**Root cause.** `Journal.doRollback` (J:1189-1196) renames `previous/` back to `current/` and calls only
`storage.refreshStorage()`. HADOOP-17142 fixed only the VERSION properties. It never calls `refreshCachedData()`
(J:202-213). `PersistentLongFile.get` (PersistentLongFile:53-59) caches `lastPromisedEpoch`/`lastWriterEpoch` once
loaded, and `JournalNode.doRollback` (JournalNode:487-491) acts on the live cached `Journal` (`getOrCreateJournal`,
JournalNode:98-109). Compare `doUpgrade` (J:1131-1171), which rebuilds these objects, and `format` (J:259), which
refreshes them.

**Path:** after an HA upgrade, later writers raise the promises to E_up+2 or more. `namenode -rollback` runs with the
JNs up, which the HA upgrade procedure requires. The disk now holds the pre-upgrade promise, but a JN that stays up
(j1) keeps the high cached value. JNs restarted after the rollback (for example, while restarting JNs on the old
binaries) report the low disk value. The next writer's `getJournalState` majority comes from those JNs (QJM:232-242),
so it picks an epoch below j1's cached promise. j1 then rejects every RPC at **J:487-489** (frame J:489 in
`repro/test_bugMC-2...`). In the no-spy Level-0 natural race this happened in 56 of 60 runs.
**Reproduction realism.** It uses only public QJM upgrade/rollback calls, writer start/stop and `restartJournalNode`.
Spies only order replies. Whitebox is used for reads only.
**Bug?** Yes: the in-memory epoch state diverges from disk after rollback. The javadoc at J:197-201 requires a
reload "after any formatting operation, since the cached data is no longer relevant". A rollback replaces `current/`
in the same way, and HADOOP-17142 already fixed the analogous stale VERSION properties.
**Severity.** As in 08/MC-1: a JN is excluded for the writer's tenure and one more JN failure terminates the NN. It
heals when j1 is restarted, which reloads the disk value. The trigger is rare (an HA upgrade rollback plus a partial
JN restart). No JIRA found; unchanged on trunk.

---

## hdfs-adhoc-09 — `Journal.checkRequest`, `checkArgument(reqInfo.getCommittedTxId() >= committedTxnId.get())` (J:503-508)

### 09/MC-1 — DROP (known: HDFS-5058). Confidence medium.
**Path (verified):** `JournalSet.selectInputStreams` (JournalSet:266-284) logs "Unable to determine input streams …
Skipping" (L280) and swallows an IOException even from the shared QJM. So `EditLogTailer.catchupDuringFailover`
(EditLogTailer:297-328) and the safety check in `FSEditLog.openForWrite` (FSEditLog:333-345) both see no streams. The
new active then opens at `lastWritten+1`, which can be mid-segment with in-progress tailing. `Journal.startLogSegment`
rejects only a file starting at the same txid (J:588-604), so it accepts a+1 inside the finalized s..e. The next RPC
carries committedTxId a+1 < e and every JN throws at J:504 (frame seen in `repro/MC-1.log`). The new active
terminates, and the later recovery hits the QJM:384-389 AssertionError. The severity is high, and the read-failure
injection via logger spies is realistic.
**Why DROP:** this is the mechanism of **HDFS-5058** ("QJM should validate startLogSegment() more strictly", Todd
Lipcon, 2013, resolved Won't Fix in 2018): selectInputStreams warns and returns nothing, then the QJM wrongly accepts
`startLogSegment` mid-segment. The JN-side check proposed there was never committed. The failover/read-fault trigger
is new; the defect is not. It could be filed as a new trigger against HDFS-5058.

### 09/MC-3 — DROP (trigger not realistic; bounded impact). Confidence medium.
**Path (verified):** `Journal.discardSegments` (J:1198-1202) takes no RequestInfo and sets
`committedTxnId = startTxId-1` unconditionally. A JN that missed the rolling-rollback NN's `newEpoch` is still at the
old epoch. A late RPC from the pre-rollback NN passes J:486-494 there, then either fails J:504 itself or re-raises
`committedTxnId` (J:510), so that the new writer is rejected at J:504.
**Why DROP:** the rolling rollback requires every NN to be shut down first, so the trigger needs an RPC from a
**stopped** NameNode to arrive after the JN heals, after `discardSegments` (which needs all JNs), and before any
newer-epoch RPC. That is an orphaned-TCP-retransmit coincidence. The impact is one JN out of sync until the writer's
committed txid passes the stale value. No data loss.

### 09/CR-3 — DROP (trigger not realistic; bounded impact). Confidence medium.
**Path (verified):** `doRollback` (J:1189-1196) rewinds `committedTxnId` (the file is reopened lazily from the
restored dir), but rollback RPCs carry no epoch. A delayed `finalizeLogSegment` from the post-upgrade writer
(epoch ≥ promise) passes `checkRequest` and sets `committedTxnId=107` at J:510. The post-rollback writer's RPCs then
fail at J:504 (frame seen in `test_bugCR-3_rollback_late_rpc.base.log`).
**Why DROP:** the offline-rollback procedure has all NNs stopped. The trigger needs one RPC from a writer that exited
cleanly to stay in flight across the operator's shutdown, `-rollback` and restart. The impact is one JN excluded
until the writer passes the stale txid (or a failed recovery attempt while that JN is in the prepare quorum; a
retry can avoid it). This is a fencing gap worth noting, but not a severe, realistic bug.

---

## hdfs-adhoc-10 — `Journal.checkWriteRequest`, `reqInfo.getEpoch() != lastWriterEpoch.get()` (J:517-520)

All five findings share one mechanism, which is verified. `lastWriterEpoch` is advanced only in
`Journal.startLogSegment` (J:606-612). `IPC.startLogSegment` (IPC:474-487) does not set `outOfSync` when the start
fails, so the next `journal()` is still sent (IPC:358). On a JN that never ran the epoch's first start, that call
throws at **J:518** (frame :520 in every repro log). `sendEdits` then sets `outOfSync=true` (IPC:368) and skips the JN
until the next roll's `startLogSegment` clears it (IPC:479). The log text "Will try to write to this JN again after
the next log roll" is the HDFS-3726 design (commit cae8116a146). In later segments the same miss fails at J:405-406
("no segment open") instead, with identical handling. The quorum write succeeds, there is no data loss, and the JN
rejoins at the next roll (about 2 min by default with a standby). The bare symptom is open as **HDFS-17563** ("IPC's
epoch is not the current writer epoch", Minor, no root cause given).

- **10/MC-1 — DROP** (by design / known symptom HDFS-17563 / low severity). Trigger: one lost `startLogSegment`.
  Confidence high.
- **10/MC-2 — DROP** (by design, low severity). Trigger: a JN restart between `newEpoch` and the first start. The JN
  would sit out the segment anyway (curSegment null). Confidence high.
- **10/MC-4 — DROP** (by design, low severity). Trigger: a start held longer than the 120 s RPC timeout, overtaken by
  `journal`. IPC gives no cross-call ordering after a client timeout, and the JN is excluded until the next roll.
  Confidence high.
- **10/MC-5 — DROP** (by design, low severity). Trigger: a disk error persisting `lastWriterEpoch` (J:611), injected
  with `FileUtil.setWritable(false)`. A faulty JN is excluded until the next roll, which is the correct reaction. The
  message is misleading. Confidence high.
- **10/MC-3 — DROP** (low severity). Confidence medium. It adds a real but minor defect: J:588-603 rejects a
  **header-only** in-progress file (0 txns: `getLastTxId()` is INVALID_TXID, not `getFirstTxId()`) with
  IllegalStateException "seems to contain valid transactions" (J:600-602), although the comment (J:584-586) says a
  writer crash at segment start is expected. Only the newEpoch/constructor scan (J:221-238) and `getSegmentInfo` move
  such files aside, so a JN that missed `newEpoch` keeps it, fails the start before J:611, and then trips J:518. The
  repro uses spies plus real crash/restart, and the header-only file comes from a real writer crash
  (`testLevel1CrashAfterStartOnAllJNs`, after the existing `testCrashAtBeginningOfSegment`). Impact: the JN misses one
  segment and keeps an empty leftover file. It rejoins at the next roll, and the syncer/purge clean up. The "one
  more JN failure kills the NN" consequence holds for any single excluded JN during one segment. It is worth a small
  upstream fix (treat 0-txn like 1-txn), but it is not severe.

---

## KEEP list (root causes)

1. **07/MC-1** (with 09/CR-5 as a duplicate): `FileJournalManager.isStaleInProgressLog` (HDFS-8178) uses the in-memory
   `currentInProgress`, which is null after a JN restart, so a checkpoint purge renames the JN's live, acknowledged
   in-progress segment to `.stale`. QJM recovery can then truncate or skip quorum-acknowledged edits (data loss).
2. **08/MC-1**: `QJM.createNewUniqueEpoch` chooses its epoch from only a majority's promises and never re-proposes, so
   an orphan promise left on one JN by failed epoch attempts fences the newest legitimate writer on that JN for its
   whole term. The cluster has no JN fault tolerance until the next failover.
3. **08/MC-2**: `Journal.doRollback` does not call `refreshCachedData()`, so a JN that stays up through
   `namenode -rollback` keeps its post-upgrade cached `lastPromisedEpoch` and fences the next writer for its tenure.
