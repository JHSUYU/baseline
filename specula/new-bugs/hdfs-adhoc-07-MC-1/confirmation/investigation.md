# MC-1 — Phase 1 investigation (evidence only)

Target (from `/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-07/target.yaml`): `Journal.acceptRecovery(RequestInfo, SegmentStateProto, URL)`,
`Journal.java:926`, `throw new AssertionError(...)`, guard
`txnRange(currentSegment).contains(committedTxnId.get()) && !txnRange(segment).contains(committedTxnId.get())`.
Pinned tree: base commit `734dd8a67cd`. Workload: `TestQuorumJournalManager#testRecoverAfterIncompleteRecovery`.
Property: `TargetSafe == ~targetFired`.

Finding source: model checking, real counterexample `spec/output/hunt/gated/purge_guided_b_bfs.out`
(69 states, TargetSafe violated; JSON copy `purge_guided_b_cex.json`). My decoded step list is in
`notes/cediff.txt` (produced by `notes/cediff.py`, diff of consecutive CE states).

## Step 1 — code audit (all citations are the pristine base commit)

### The stale-marking purge
* `FileJournalManager.purgeLogsOlderThan` (FJM.java:199-214) lists all edit files and, for each in-progress file
  with `firstTxId >= minTxIdToKeep`, calls `purger.markStale(log)` if `isStaleInProgressLog` holds.
* `isStaleInProgressLog` (FJM.java:216-224): `log.isInProgress() && !log.getFile().equals(currentInProgress) &&
  log.getFirstTxId() >= minTxIdToKeep && EDITS_INPROGRESS_REGEX matches`.
* `currentInProgress` is an in-memory field (FJM.java:79, initial `null`), set only by `FJM.startLogSegment`
  (FJM.java:124) and cleared by `finalizeLogSegment` (FJM.java:158-160).
* `markStale` → `EditLogFile.moveAsideStaleInprogressFile()` → rename to `edits_inprogress_<txid>.stale`
  (NNStorageRetentionManager.java:240-242, FJM.java:631-633). A `.stale` file is no longer matched by
  `getLogFiles` / `getLogFile` (FJM `matchEditLogs(..., forPurging=false)` only matches the strict regexes).
* JN path: `JournalNodeRpcServer.purgeLogsOlderThan` → `Journal.purgeLogsOlderThan` (Journal.java:690-696:
  `checkFormatted(); checkRequest(reqInfo); storage.purgeDataOlderThan(min)`) → `JNStorage.purgeDataOlderThan`
  (JNStorage.java:174-175) → `fjm.purgeLogsOlderThan(min)` on the same FJM instance the Journal writes with.
* After a JN restart, `JournalNode.getOrCreateJournal` (JournalNode.java:98-125) builds a new `Journal`
  (Journal.java:159-178) whose `JNStorage` builds a new FJM (JNStorage.java:74) → `currentInProgress == null`
  until that JN receives the next `startLogSegment`. The writer's open segment on that JN is therefore *not*
  protected by `isStaleInProgressLog` any more.
* Developer intent in the javadoc (FJM.java:189-190): "Edits in progress files that are after minTxIdToKeep, but
  before the current edits in progress files are marked as stale for clarity." The test
  `TestNNStorageRetentionManager#testExtraInprogressFilesAreRemovedOrMarkedStale` (lines 255-282) sets
  `fjm.currentInProgress = findLastInProgressEdit(root)` (line 423) and expects the newest in-progress file to be
  kept — i.e. the code assumes the FJM always knows its current segment.

### Who sends a purge, and with which `minTxIdToKeep`
* NN: `ImageServlet` (ImageServlet.java:682, checkpoint upload) and `FSImage.saveNamespace` (FSImage.java:1275)
  → `NNStorageRetentionManager.purgeOldStorage` (NNSRM.java:113-172) → `FSEditLog.purgeLogsOlderThan`
  (FSEditLog.java:1519-1542, requires `minTxIdToKeep <= curSegmentTxId`) → `QuorumJournalManager.purgeLogsOlderThan`
  (QJM.java:466-471, asynchronous, no quorum wait) → `AsyncLoggerSet` → every `IPCLoggerChannel.purgeLogsOlderThan`
  (IPCLoggerChannel.java:499-504).
* Because `minTxIdToKeep <= curSegmentTxId`, the writer's open segment always satisfies
  `firstTxId >= minTxIdToKeep`; the only thing that keeps it from being stale-marked on a JN is `currentInProgress`.
* `FSEditLog.logSync` flushes outside the FSEditLog monitor (FSEditLog.java:733-737: `logStream.flush()` after the
  `synchronized (this)` block), so a checkpoint purge can be dispatched while a batch is waiting for its quorum.
* `IPCLoggerChannel.purgeLogsOlderThan` has no `throwIfOutOfSync()` (unlike `sendEdits`/`finalizeLogSegment`), and
  its `RequestInfo` — including `committedTxId` — is built by `createReqInfo()` (IPCLoggerChannel.java:287-291)
  *inside the executor task*, i.e. when the task starts, immediately before the RPC.
* The QJournal proxy is a plain `RPC.getProxy` (IPCLoggerChannel.java:218-236): a call whose connection attempt is
  refused is retried by the IPC client up to `ipc.client.connect.max.retries` (default 10,
  CommonConfigurationKeysPublic.java:416) every `ipc.client.connect.retry.interval` (default 1000 ms, line 425);
  log line `Retrying connect to server:` (Client.java:977/1013). `MiniJournalCluster.restartJournalNode` restarts
  the JN on the same RPC address (MiniJournalCluster.java:238-262). The workload test class sets
  `ipc.client.connect.max.retries = 0` (TestQuorumJournalManager.java:108-110) "just to speed up the tests".

### Commit bookkeeping
* `QuorumOutputStream.flushAndSync`: `sendEdits` → `waitForWriteQuorum` → `loggers.setCommittedTxId(last)`.
  `AsyncLoggerSet.waitForWriteQuorum` returns as soon as a majority succeeded.
* JN side `Journal.checkRequest` (Journal.java:484-512) stores `reqInfo.getCommittedTxId()` into the persisted
  `committedTxnId` (BestEffortLongFile `committed-txid`).

### Recovery and the target
* `QJM.recoverUnfinalizedSegments` (QJM.java:474-499) → `createNewUniqueEpoch` (getJournalState + newEpoch on a
  majority) → `recoverUnclosedSegment(maxLastSegmentTxId)` (QJM.java:311-408):
  prepare on a majority (`waitForWriteQuorum`), pick the best response (`SegmentRecoveryComparator`), the client
  sanity check (QJM.java:379-390) **only over the prepare responders**, then `acceptRecovery` to **every** logger
  and `finalizeLogSegment`, each needing only a majority.
* `Journal.prepareRecovery` (Journal.java:827-866) reports the local segment (or none) and `lastCommittedTxId`.
* `Journal.acceptRecovery` (Journal.java:871-986): `currentSegment = getSegmentInfo(segmentTxId)`; if its end differs
  from the proposal and it contains `committedTxnId` while the proposal does not → **Journal.java:926 throws
  `AssertionError("Cannot replace segment ... would discard already-committed txn ...")`** (statement spans 926-933).
  The JN IPC server logs Errors at WARN with the full stack and returns a `RemoteException(java.lang.AssertionError)`.

### Trigger scenario (the counterexample's shape, CE steps in brackets)
3 JNs j0, j1, j2; writers w1 (epoch 1) and w2 (epoch 2).
1. w1 becomes writer, starts segment 1 and commits txn 1 [1-26]; j2 lags (gets start/txn 1 late, with C=1) [32-35, 53].
2. w1 sends txn 2 [27]; a checkpoint purge(1) is dispatched while the batch is pending [28].
3. j0 acks txn 2 [33]; j1 writes txn 2 [36] but the writer has not yet seen the quorum.
4. j0 crashes [37]; w1's channel to j0 starts the purge task, binding `committedTxId = 1` [38]; the RPC sits in
   IPC connect retries.
5. w1 sees the quorum {j0,j1} → committed txn 2 (C=2) [39]; the purge to j1 carries C=2 → j1.committedTxnId=2 [40-41].
6. j0 restarts [42]; the retried purge (C=1) lands; `currentInProgress == null` → `edits_inprogress_1` (txns 1-2)
   renamed `.stale` [47]. w1 sends nothing more to j0.
7. w2 recovers with j1 slow: newEpoch quorum {j0 (no segment), j2 ([1,1])} → segment 1 [50-58];
   prepare quorum {j0: no segment, C=1; j2: [1,1], C=1} → decision [1,1]; client check passes [58-65].
8. acceptRecovery([1,1]) at j1 (current [1,2], committedTxnId 2) → AssertionError at Journal.java:926 [66-68].
9. (Beyond the CE) accept/finalize succeed on j0 and j2 (a majority), so w2 finalizes segment 1 as [1,1]:
   txn 2, acknowledged to w1, is lost.

Safeguards met on the path (recorded, not judged): the QJM client check (QJM.java:379-390) — defeated because the
only JN that knows C=2 (j1) is not in the prepare quorum and j0's committed-txid is 1 (stale RequestInfo); the
target assertion itself (fires only on j1, a minority); `IPCLoggerChannel` out-of-sync logic (does not apply to
purge); the writer's next batch would have taught j0 C=2 (needs w1 to stop first).

Reachability: every step uses public/normal paths (QJM API, JN RPCs, a JN process crash/restart, a checkpoint
purge, writer failover). Timing requirements: j0 must crash between acking the last batch and receiving the purge;
the purge must be dispatched before the quorum completes (j1 slower than j0); j0 must restart within the IPC
connect-retry window (~10 s with defaults); w1 must not send another batch to j0 before failover; j2 must have
missed the last batch; j1 must be slower than j0/j2 during w2's prepare.

## Step 2 — developer-knowledge (in-tree evidence only at this point)
Per the adhoc-coordination Shared Rule 2, tracker / git-history searches about the target are deferred until
after the reproduction verdict and may set only the Novelty field. In-tree evidence:
* FJM.java:189-190 javadoc (stale-marking must spare "the current edits in progress files").
* Journal.java:921-923 ("Paranoid sanity check: if the new log is shorter than the log we currently have, we should
  not end up discarding any transactions which are already Committed.")
* QJM.java:377-378 ("Sanity check: none of the loggers should be aware of a higher txid than the txid we intend to
  truncate to"); QJM.java:467-468 ("purges asynchronously -- ... it's always OK to fail").
* Tests: `TestQuorumJournalManager#testPurgeLogs` purges only finalized segments, no restart;
  `TestNNStorageRetentionManager#testExtraInprogressFilesAreRemovedOrMarkedStale` presets `currentInProgress`.
  No test covers a purge reaching a restarted JN while its segment is still open.

## Step 3 — known-status
MC-sourced with an actual counterexample → no pre-filter drop; proceeds to Phase 2.
Novelty search: see "Novelty search (after verdict)" below.

## Phase 2 outcome (settled 2026-10-29 ~05:25 UTC, before any tracker/history search)
Reproduction `repro/test_bugMC-1_purge_restart.{java,sh}` (Level 1: public QJM API + MiniJournalCluster JN
stop/restart + per-channel timing gates on the @VisibleForTesting `IPCLoggerChannel#createSingleThreadExecutor`
hook; pristine base-commit sources, no source patch, no state injection). Every run so far: the real JN throws
`java.lang.AssertionError: Cannot replace segment startTxId: 1 endTxId: 2 ... would discard already-committed txn 2`
from `Journal.acceptRecovery(Journal.java:932)`; javap shows pc 324 `invokespecial AssertionError.<init>` / pc 327
`athrow` of the statement whose `new AssertionError` (pc 295) is line 926. With assertions off (production JVM
default) the new writer finalizes [1,1] on {j0,j2} and a reader gets txids [1]: acknowledged txn 2 is lost. With -ea
only the test-only `QuorumCall.checkAssertionErrors` (QuorumCall.java:232-257) aborts the writer. Negative control
(purge reaches j0 before its crash): no stale-mark, recovery picks [1,2], txn 2 survives.
Verdict: REPRODUCED. (The novelty search below may set only the Novelty field.)

## Novelty search (after verdict; may set only the Novelty field) — 2026-10-29
Git history (pinned repo, read-only):
* `git log -S isStaleInProgressLog -- .../FileJournalManager.java` → `fcb7884bfc0 2019-08-29 HDFS-8178. QJM doesn't move aside
  stale inprogress edits files.` (the change that introduced the stale-marking branch).
* `git log -8 -- FileJournalManager.java Journal.java JNStorage.java` → newest is `f609460bda0 2023-11-20 HADOOP-18957`
  (charsets); nothing touching the purge/stale or acceptRecovery logic since HDFS-8178. Base commit 734dd8a67cd is
  2026-05-13 trunk.
Apache JIRA (REST `search`, project HDFS):
* `text ~ "markStale"` → HDFS-4754 (DataNode stale API, unrelated), HDFS-8178.
* `text ~ "currentInProgress"` → BKJM issues (2012), HDFS-3530, HDFS-8178, HDFS-10957, HDFS-2018 — none about a restart.
* `text ~ "\"would discard already-committed\""` → 0.  `text ~ "\"Cannot replace segment\""` → 0.
* `text ~ "stale" AND text ~ "inprogress" AND text ~ "JournalNode"` → HDFS-8178, HDFS-16645, HDFS-10902, HDFS-9126.
* `text ~ "HDFS-8178"` → HDFS-8303, HDFS-8178.  `text ~ "isStaleInProgressLog"` → 0.
* `text ~ "stale" AND text ~ "purge" AND created >= 2019-08-30` → HDFS-16864, HDFS-16261 (DataNode, unrelated).
* `text ~ "edits_inprogress" AND text ~ "stale" AND created >= 2019-08-30` → HDFS-16557, HDFS-16645, HDFS-16513.
* `summary ~ "JournalNode restart" OR summary ~ "JN restart"` (created >= 2019) → 0.
* `(JournalNode OR QJM) AND (purge OR stale) AND created >= 2025-01-01` → HDFS-17710 (JN edit cache, unrelated).
* `committed AND lost AND JournalNode AND created >= 2023-01-01` → 0.
GitHub apache/hadoop PRs (search API): `markStale` 0; `currentInProgress` 0; `"stale" "in-progress" journal` →
#4518 (HDFS-16645), #4971 (HDFS-16793), #4219 (HDFS-16557), all closed unmerged; `purgeLogsOlderThan` → #4082
HDFS-16507 (merged 2022-03-31); `"edits_inprogress" stale` 0; `FileJournalManager updated:>=2025-01-01` 0;
`JournalNode purge updated:>=2025-01-01` 0; `acceptRecovery updated:>=2024-01-01` → #4565 (lambda refactor).
Assessment of the closest hits:
* HDFS-8178 (fixed 3.3.0/3.2.1/3.1.3) introduced the code. Its review raised a general worry (A. Myers, 2015: purging
  may be "over aggressive ... if somehow we ended up with two in-progress segments, both of which were required");
  nobody reports that a JN restart clears `currentInProgress` so the writer's open segment is stale-marked. This is
  developer awareness of a risk, not a report of this defect.
* HDFS-16645 (open): leftover in-progress segment after an abnormal JN shutdown makes `getEditLogManifest` throw
  "Invalid log manifest". Different mechanism and symptom (no purge, no loss of a committed txn).
* HDFS-16507 (fixed): NN-side precondition `minTxIdToKeep <= curSegmentTxId` in `FSEditLog.purgeLogsOlderThan` so
  the open segment is not *deleted* by range. Present in this tree (FSEditLog.java:1526-1530); it is why the open
  segment always falls into the stale-marking branch instead. Different site.
* HDFS-10902 (open): QJM reading stale/failed txns from one JN; HDFS-17710 (open): JN cache serving unpersisted
  edits. Different mechanisms.
Novelty: NEW (no report of this mechanism at this site found).

## Environment / provenance
* Worktree `confirmation/MC-1/worktree` (base 734dd8a67cd). It arrived with the harness instrumentation copied in;
  I moved that aside (`notes/instrumentation-snapshot/tracked.diff` + `untracked/`) and restored the tracked files, so
  the reproduction runs on pristine base-commit sources (the runner prints `git status`: no tracked changes). Only
  the test `TestBugMC1PurgeRestart.java` is added (untracked) under the hadoop-hdfs test tree.
* Build: the harness's known-good recipe (`harness/run.sh`): `mvn -B -o test-compile -pl hadoop-hdfs-project/hadoop-hdfs`
  with `/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-07/env.sh` (JDK 17, offline repo `deps`). Upstream modules
  (hadoop-common, hadoop-hdfs-client 3.6.0-SNAPSHOT) come from `deps`, installed 2026-10-26 by the target's
  `build.prepare` before any instrumentation (the instrumentation touches only hadoop-hdfs). Nothing was installed
  into the shared `deps` repository.
* Runs: 2 (exploratory) + 10 (2-test version, 5 per JVM mode) + 6 (final 3-test version, 3 per mode); every bug run
  reproduced, every control kept txn 2. Logs: `logs/` (final), `logs/attempts-2tests/`, `notes/run*.console.txt`.
