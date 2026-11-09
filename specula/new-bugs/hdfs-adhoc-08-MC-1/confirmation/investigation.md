# MC-1 investigation (Phase 1: evidence only)

Finding: *A failed epoch attempt's orphan promise fences the next established writer.*
Source: model checking. Invariant `TargetSafe` (target hdfs-adhoc-08: `Journal.checkRequest`,
`Journal.java:487`, throws `java.io.IOException`, guard `reqInfo.getEpoch() < lastPromisedEpoch.get()`).
Counterexamples: `spec/output/MC_hunt_orphan_promise_bfs_w1.out` (primary),
`spec/output/MC_s1_lossonly_bfs_w1.out` (loss only), `spec/output/MC_hunt_rollback_cache_bfs_w8.out`
(stop only).

Tree: worktree at base_commit `734dd8a67cd6df56b59ff75aa43de57834a0d248`. The worktree was handed
over with the harness instrumentation applied (6 modified files + 4 untracked `Specula*` files).
It was backed up to `instrumentation-backup-run2/` and reverted. Every line cited below, and every
build and run, is from the **pristine** tree.

## Step 1: Code audit

### Cited code (pristine line numbers)

| Site | What it does |
|---|---|
| `QuorumJournalManager.java:227-249` `createNewUniqueEpoch()` | L232-234: `loggers.waitForWriteQuorum(loggers.getJournalState(), ...)`. L236-239: `maxPromised` = max over the **successful responses only**. L242: `myEpoch = maxPromised + 1`. L243-245: `waitForWriteQuorum(loggers.newEpoch(nsInfo, myEpoch), ...)`. L247: `loggers.setEpoch(myEpoch)`. |
| `AsyncLoggerSet.java:61-68` `setEpoch(long)` | Sets `myEpoch` and calls `l.setEpoch(e)` on **every** logger, including one that rejected or never received `newEpoch`. |
| `AsyncLoggerSet.java:119-148` `waitForWriteQuorum` | `q.waitFor(loggers.size(), majority, majority, ...)`, then returns `q.getResults()`: the successes only. |
| `QuorumCall.java:165-177` `waitFor` | Returns as soon as `countSuccesses() >= minSuccesses` (majority). A minority's reply or failure is not awaited. |
| `IPCLoggerChannel.java:184-186` `setEpoch`, `:287-291` `createReqInfo()` | Every later RPC of this writer to that JN carries `epoch` = the writer's epoch. |
| `IPCLoggerChannel.java:473-487` `startLogSegment` | RPC `startLogSegment(createReqInfo(), ...)`; resets `outOfSync` only on success. |
| `IPCLoggerChannel.java:342-375` `sendEdits` | On a failed `journal()` sets `outOfSync = true`; log text: "Will try to write to this JN again after the next log roll." |
| `Journal.java:339-365` `newEpoch` | L347-350: rejects `epoch <= getLastPromisedEpoch()` with "Proposed epoch X <= last promise Y". L352: `updateLastPromisedEpoch(epoch)` persists the promise **before** the writer knows whether a quorum accepted. |
| `Journal.java:484-509` `checkRequest` | L486: guard `reqInfo.getEpoch() < lastPromisedEpoch.get()`; L487-489: `throw new IOException("IPC's epoch ... is less than the last promised epoch ...")` (the target). L490-494: a higher epoch raises the promise. |
| `Journal.java:511-519` `checkWriteRequest` | Calls `checkRequest` first (journal RPC). `startLogSegment` (`:568-572`), `finalizeLogSegment` (`:629-632`), `prepareRecovery` (`:827-830`), `acceptRecovery` (`:871-875`), `purgeLogsOlderThan`, `heartbeat` also call `checkRequest`. |
| `JournalSet.java:387-408` `mapJournalsAndReportErrors` | Any failure on a **required** journal: `abortAllJournals()`; `terminate(1, msg)`. |
| `FSEditLog.java:288-307` `initJournals`, `FSNamesystem.java:1706-1711` | The shared (QJM) edits dir is always required. |
| `FSEditLog.java:1664-1683` `recoverUnclosedStreams(true)`, `FSNamesystem.java:1423` | A failed `recoverUnfinalizedSegments` during `startActiveServices` terminates the NameNode. |

### Call chain (entry points to the target)

NameNode becomes active: `FSNamesystem.startActiveServices` (`:1423`), then
`FSEditLog.recoverUnclosedStreams(true)` (`:1664`), then `JournalSet.recoverUnfinalizedSegments` (`:634`),
then `QuorumJournalManager.recoverUnfinalizedSegments` (`:474`), then `createNewUniqueEpoch` (`:227`).
After that, every edit-log operation (`FSEditLog.startLogSegment`/`logSync`/`endCurrentLogSegment`)
goes through `JournalSet` to `QuorumJournalManager.startLogSegment` (`:430`) and
`QuorumOutputStream.flushAndSync` (`:89-113`), and from there to `AsyncLoggerSet` and
`IPCLoggerChannel.startLogSegment`/`sendEdits`. On the JN side the call is
`JournalNodeRpcServer`, then `Journal.startLogSegment`/`journal`, then `checkRequest`, which throws at
`:487-489`. All of these are normal operations of an HA NameNode with QJM shared edits; the workload
test drives the same QJM API.

### Reachability and trigger scenario

1. Writer attempts A and B (NameNodes trying to become active). Each reads a majority's promises,
   proposes `e`, and JN0 accepts `newEpoch(e)` and persists it (`J:352`). The `newEpoch` to JN1/JN2
   is not delivered: it is lost, or the NameNode stops first. The attempt fails: a `QuorumException`
   that `FSEditLog.recoverUnclosedStreams(true)` turns into `terminate(1)`, or a crash. JN0 is left
   holding an orphan promise (2, then 3) that no live writer owns.
2. Writer C (the next NameNode) runs `createNewUniqueEpoch`. JN0's `getJournalState` reply fails or
   merely arrives after JN1's and JN2's (`QuorumCall.waitFor` returns at 2 successes), so
   `maxPromised` = max(JN1, JN2) and `myEpoch` = max(JN1, JN2) + 1, which is lower than JN0's
   orphan promise.
3. `newEpoch(myEpoch)` succeeds on JN1 and JN2. JN0 rejects it (`J:347-349`) or never receives it.
   QJM accepts the majority, and `loggers.setEpoch(myEpoch)` (`QJM:247` / `ALS:61-68`) also sets it
   on JN0's channel.
4. C's first RequestInfo RPC to JN0 (`startLogSegment`, or `prepareRecovery` when a segment
   exists) carries `myEpoch` < JN0's promise, and `Journal.checkRequest` throws at `:487-489`. Every
   later RPC does the same: `journal`, the next roll's `startLogSegment`, `finalize`, and
   `heartbeat`. JN0's promise is persisted (`PersistentLongFile`) and survives a JN0 restart.

### Safeguards encountered (recorded, not dismissed)

- `IPCLoggerChannel` `outOfSync` and rejoin at the next roll (`ILC:358-372`, `:476-485`). This is meant
  to bring a lagging JN back, but the roll's `startLogSegment` also fails `checkRequest`, so it cannot
  re-admit JN0.
- `QuorumCall`/`waitForWriteQuorum` majority rule: the writer keeps working on JN1 and JN2. The fault
  is masked only while both stay up.
- No code path re-runs `newEpoch` or raises the writer's epoch after a "Proposed epoch X <= last
  promise Y" rejection. `createNewUniqueEpoch` is called only from `recoverUnfinalizedSegments`, once
  per writer (`Preconditions.checkState(!isActiveWriter)`, `QJM:475`).
- The next failover heals it: a writer whose `getJournalState` majority includes JN0 picks an epoch
  above JN0's promise. That happens only after this writer's term ends.

## Step 2: Developer knowledge (pinned tree only, for now)

Shared Rule 2 of the ad hoc skill allows tracker and history searches only after the reproduction
verdict is settled. Those queries are recorded in "Novelty search" below. Evidence from the pinned
tree:

- `Journal.java:485` comment on the guard: `// Invariant 25 from ZAB paper`. `Journal.java:335-337`
  javadoc of `newEpoch`: "@throws IOException if the node has already made a promise to **another
  writer** with a higher epoch number". The check is meant to fence a *different, older* writer.
- `QuorumJournalManager.java:221-226` javadoc of `createNewUniqueEpoch`: "Fence any previous writers,
  and obtain a unique epoch number for write-access to the journal nodes."
- `IPCLoggerChannel.java:363-366`: "Remote journal {} failed to write txns {}-{}. Will try to write
  to this JN again after the next log roll." `TestIPCLoggerChannel.java:181-183`
  (`testStopSendingEditsWhenOutOfSync`): "// After a roll, sending new edits should not fail."
  followed by `assertFalse(ch.isOutOfSync())`. The developers intend a lagging JN to rejoin at the next
  roll.
- `TestEpochsAreUnique.java:78-104` (`testSingleThreaded`) injects `getJournalState` (10%) and
  `newEpoch` (40%) faults and asserts only that each **successfully created** epoch is greater than
  the previous successful one ("it should still always increase, perhaps skipping some"). It never
  checks that the new writer can use every live JN. Our scenario keeps that property (established
  epochs 1, then 2).
- `TestQuorumJournalManager` has no test that combines failed epoch attempts with a later writer
  that misses one JN's `getJournalState` reply.

## Step 3: Known-status / pre-filter

MC-sourced with actual counterexamples, so the code-review × known drop does not apply; the finding
proceeds to Phase 2. Novelty is decided after the verdict (see "Novelty search").

## Phase 2 pointers

- Reproduction: `repro/test_bugMC-1_orphan_promise.sh` (driver) and
  `repro/test_bugMC-1_orphan_promise.java` (JUnit variant of `TestQuorumJournalManager#testSingleWriter`).
- Logs: `repro/MC-1-logs/run2-*`.

## Additional safeguard examined after reproduction

- **JournalNodeSyncer** (HDFS-4025; `DFS_JOURNALNODE_ENABLE_SYNC_DEFAULT = true`, interval 2 min,
  `DFSConfigKeys.java:1503-1506`). `JournalNodeSyncer.java` never reads or writes an epoch or promise
  (no "epoch" occurrence in the class), so it cannot lift JN0's fence. It backfills only finalized
  segments, and `Journal.moveTmpSegmentToCurrent` accepts them only if `endTxId <= committedTxnId`
  (`Journal.java:1204-1207`). JN0's `committedTxnId` is advanced in normal operation only inside `checkRequest` *after* the
  epoch check (`Journal.java:503-511`, set at `:510`; the other setters, `:1168` and `:1201`, belong to the
  upgrade/discard paths), which throws first for this writer, so the backfill of this
  writer's segments is also blocked. This mechanism does not mask the consequence.

## Novelty search (run only after the reproduction verdict was settled: REPRODUCED, 2026-10-29)

Queries:

1. Web search (standard): `HDFS JIRA "is less than the last promised epoch" JournalNode newEpoch minority writer fenced`
   and `HDFS QuorumJournalManager createNewUniqueEpoch failed newEpoch JournalNode promised higher epoch rejects new writer JIRA`.
   Results: Cloudera community posts about ordinary stale-writer fencing, and HDFS-3906 (newEpoch timeout).
2. Apache JIRA REST (`issues.apache.org/jira/rest/api/2/search`):
   - `project = HDFS AND text ~ "\"last promised epoch\""` returned 8: HDFS-16690, HDFS-15011, HDFS-11254, HDFS-11225, HDFS-10659, HDFS-9126, HDFS-7952, HDFS-3190.
   - `project = HDFS AND text ~ "createNewUniqueEpoch"` returned 4: HDFS-17223, HDFS-16648, HDFS-3743, HDFS-3077.
   - `project = HDFS AND text ~ "\"promised epoch\""` returned the same 8 as the first query.
   - `project = HDFS AND text ~ "newEpoch" AND text ~ "minority"` returned 2: HDFS-13977, HDFS-3077.
   - `project = HDFS AND summary ~ "epoch" AND (summary ~ "QJM" OR summary ~ "journal" OR summary ~ "JournalNode")` returned HDFS-4828.
   - `project = HDFS AND text ~ "\"Proposed epoch\""` returned 0.
   - `project = HDFS AND text ~ "getJournalState" AND text ~ "epoch"` returned HDFS-16661, HDFS-9590.
   - `project = HDFS AND text ~ "newEpoch" AND (text ~ "orphan" OR text ~ "lower epoch" OR text ~ "smaller epoch" OR text ~ "stale promise")` returned HDFS-3950, HDFS-3077.
   - `project in (HDFS, HADOOP) AND summary ~ "QJM" AND created >= 2014-01-01` returned 12, none about epochs.
   - `project = HDFS AND text ~ "lastPromisedEpoch"` returned 8: HDFS-13544, HDFS-10902, HDFS-10659, HDFS-9590, HDFS-7952, HDFS-3950, HDFS-3743, HDFS-3077.
   - `project = HDFS AND summary ~ "epoch"` returned HDFS-17563, HDFS-15011, HDFS-11296, HDFS-4828, HDFS-3212, HDFS-3211.
3. GitHub (`api.github.com`): PR searches in `repo:apache/hadoop is:pr` (open, closed and merged) for
   `createNewUniqueEpoch` (0), `"promised epoch"` (#6925 HDFS-16690, closed 2024-07-23), `newEpoch QJM` (0),
   `lastPromisedEpoch` (0), and `JournalNode epoch` (#8637 HDFS-11039 docs, #6925). Latest upstream trunk
   commits touching `QuorumJournalManager.java` (2022-09-15 HDFS-16771), `AsyncLoggerSet.java`
   (2022-10-20 HDFS-16803) and `Journal.java` (2023-11-20 HADOOP-18957): none touches epoch selection or
   the fence. Base commit 734dd8a67cd (2026) already contains them.
4. Local history: `git log -- QuorumJournalManager.java` and `git blame`. `QJM:243-247` dates from
   8a8c9c18d37 (HDFS-3906, 2012-09-11) and `Journal.java:486-488` from 74d4573a23d (HDFS-3077,
   2012-07-20); `:489` only added the journal id to the message (6beb25ab7e4, HDFS-13544, 2018).

Candidates read in full and rejected (not the same mechanism):

- HDFS-15011 (Open): the *older* active NameNode is fenced after another NameNode took over (slow JN,
  failover). This is the check doing its designed job against a stale writer.
- HDFS-4828 (Open): wording of epoch errors for an old NameNode fenced after failover.
- HDFS-17563 (Open): `checkWriteRequest` "IPC's epoch 1 is not the current writer epoch 0", a different
  check (`Journal.java:515-519`).
- HDFS-3906 (Fixed): newEpoch timeout on a large segment.
- HDFS-7952 (rollback updates lastPromisedEpoch), HDFS-10659 and HDFS-16690 (JN reinstall/format),
  HDFS-17223 (JN maintenance list), HDFS-13977, HDFS-11254, HDFS-11225: other mechanisms.

Developer-intent evidence found during the search (HDFS-3077 design discussion):

- Todd Lipcon, 2012-09-27: "if any request comes with a higher epoch than lastPromisedEpoch, then the
  JN accepts the request and also updates lastPromisedEpoch. **This allows a JournalNode to join back
  into the quorum properly even if it was down when the writer became active.**" The orphan promise
  breaks exactly this design intent: JN0 was unreachable when writer C became active, but its promise
  is *above* C's epoch, so it can never rejoin during C's term.
- Todd Lipcon, 2012-04-03: "with message losses or failures, it's possible for _neither_ of the nodes
  to get a quorum in the case of a race. That's OK, since we expect that an external leader election
  framework will eventually assist ..." Failed attempts are anticipated, but the orphan promises they
  leave on a minority were not discussed.

Novelty: **NEW**. No issue, PR or commit reports a promise left by a failed newEpoch attempt on a
minority JN fencing the next established writer at `Journal.checkRequest`.
