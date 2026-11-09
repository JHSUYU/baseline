# MC-2: investigation record (Phase 1 evidence, Phase 2 outcome, novelty)

Finding: "Rollback keeps the cached promise, so a JN that stayed up fences the next writer".
Source: MC. Counterexample `spec/output/MC_hunt_rollback_cache_bfs_w1.out` (61 states).

Target (`target.yaml`):
- check: `Journal.checkRequest(RequestInfo)`, Journal.java:487, throws `java.io.IOException`
- guard: `reqInfo.getEpoch() < lastPromisedEpoch.get()`
- pinned tree: base_commit 734dd8a67cd
- workload: `TestQuorumJournalManager#testSingleWriter`

All line numbers are from the pristine blobs (`git show HEAD:<path>`). The worktree also carries
the harness trace instrumentation. The reproduction runs set it aside (pristine sources) and
restored it byte-for-byte afterwards.

The previous turn's notes were kept in `repro-work/prev-attempt-*`. Every fact below was
re-verified in this turn.

## Step 1: code audit (facts)

| Site | Fact |
|---|---|
| Journal.java:484-494 | `checkRequest`: `if (reqInfo.getEpoch() < lastPromisedEpoch.get()) throw new IOException("IPC's epoch .. is less than the last promised epoch ..")`. The throw statement spans 487-489 and reads the in-memory `PersistentLongFile`. |
| Journal.java:568-572 | `startLogSegment` → `checkFormatted(); checkRequest(reqInfo)`. `journal`/`heartbeat` reach it through `checkWriteRequest` (:514-515). |
| Journal.java:339-352 | `newEpoch` rejects with `epoch <= getLastPromisedEpoch()`: "Proposed epoch .. <= last promise ..". This is a different line, not the target. |
| Journal.java:159-178 | Constructor: `refreshCachedData()` (:166) builds unloaded `PersistentLongFile`s; then `JournalMetrics.create(this)` (:172). |
| Journal.java:197-213 | `refreshCachedData()` rebuilds `lastPromisedEpoch`, `lastWriterEpoch`, `committedTxnId` from `current/`. Javadoc: reload "after any formatting operation, since the cached data is no longer relevant". |
| Journal.java:251-260 | `format()` calls `refreshCachedData()` (:259), added by HDFS-3884. |
| Journal.java:1132-1172 | `doUpgrade()` creates new `PersistentLongFile`s on the new `current/` and copies the values from `previous/` (:1157-1168). |
| Journal.java:1183-1187 | `canRollBack()` only calls `fjm.canRollBack`. |
| Journal.java:1189-1196 | `doRollback()`: closes `committedTxnId`; `fjm.doRollback()` (previous/ → current/, NNUpgradeUtil.doRollBack); `storage.refreshStorage()` (VERSION only, HADOOP-17142). **No `refreshCachedData()`.** The cached `lastPromisedEpoch`/`lastWriterEpoch` keep their post-upgrade values. |
| PersistentLongFile.java:53-59 | `get()` reads the file only while `!loaded` and returns the cached `value` afterwards. `set()` (:61-67) writes the file and the cache. |
| JournalNode.java:98-125 | `getOrCreateJournal` returns the live `Journal` from `journalsById`. A new one is created only on the first RPC after a JN start; `start()` (:223-258) creates none eagerly. |
| JournalNode.java:479-491 | `canRollBack`/`doRollback` run on that live `Journal` (`StartupOption.ROLLBACK`). |
| JournalMetrics.java:93-97, 117-124 | Each `Journal` registers a metrics source whose gauge `getLastPromisedEpoch()` calls `journal.getLastPromisedEpoch()`. |
| MetricsSystemImpl.java:232-233; MetricsSourceAdapter.java:87, 100-101, 155-171, 216-222 | Registration with the system monitoring calls `MBeans.register`. JMX calls `getMBeanInfo()` → `updateJmxCache()` with `lastRecsCleared = true` → all gauges are read. Creating a `Journal` therefore loads its promise from disk. JournalNodeSyncer never reads the promise. |
| QuorumJournalManager.java:227-249 | `createNewUniqueEpoch`: `waitForWriteQuorum(getJournalState())` → `myEpoch = max(responders' lastPromisedEpoch) + 1` → `newEpoch` quorum → `loggers.setEpoch(myEpoch)` on **all** loggers (:247). |
| AsyncLoggerSet.java:124-148; QuorumCall.java:165-176, 299-301 | The quorum wait returns at the first majority of successes. `getResults()` copies the map, so a later reply is ignored. |
| QuorumJournalManager.java:429-440 | `startLogSegment` goes to all loggers and waits for a write quorum. |
| IPCLoggerChannel.java:357-370, 474-486 | A failed `journal()` marks the JN out of sync: "Will try to write to this JN again after the next log roll". Only a *successful* `startLogSegment` clears that. |
| QuorumJournalManager.java:668-769 | `doPreUpgrade`/`doUpgrade`/`canRollBack`/`doRollback` wait for **all** JNs. |
| JournalSet.java:395-408; FSEditLog.java:735-748 | A failed flush to the required shared journal makes the NN `terminate(1, ..)`. |

### Call chain from public entry points
- **HA upgrade**: NN `-upgrade` → `FSImage.doUpgrade` → `editLog.doPreUpgradeOfSharedLog()`
  (FSImage.java:490 → FSEditLog.java:1694-1700) → `QJM.doPreUpgrade`. Then
  `editLog.doUpgradeOfSharedLog()` (FSImage.java:499 → FSEditLog.java:1702-1708) →
  `QJM.doUpgrade(storage)` → `Journal.doUpgrade`.
- **Writer**: NN becomes active → `recoverUnfinalizedSegments` → `createNewUniqueEpoch`. Then
  `openForWrite` → `QJM.startLogSegment` → JN `Journal.startLogSegment` → `checkRequest`.
- **Rollback**: `hdfs namenode -rollback` → `FSImage.doRollback`. First
  `editLog.canRollBackSharedLog` (FSImage.java:542 → FSEditLog.java:1718-1727) →
  `QJM.canRollBack`. Then `editLog.doRollback()` (FSImage.java:565 → FSEditLog.java:1729-1735) →
  `QJM.doRollback` → `JournalNode.doRollback` → live `Journal.doRollback`.

### Reachability
These are documented operations (HDFSHighAvailabilityWithQJM.md):
- :708-712: "it is **critical** that all the JNs be running when performing the upgrade,
  rollback, or finalization operations".
- :727: NNs may be restarted "before finalizing or rolling back the upgrade".
- :733: "To perform a rollback of an upgrade, both NNs should first be shut down."

So JNs stay up across the rollback by procedure, and several writers can be active between
upgrade and rollback.

### Trigger scenario (the CE)
- W1 holds epoch 1 and upgrades: previous/ promise = 1.
- W2 and W3 establish 2 and 3 on j0 and j1. Their requests to j2 are still in flight when each
  writer stops.
- The rollback runs with all JNs up: disk = 1,1,1, but the caches stay 3 (j0), 3 (j1), 1 (j2).
- j0 restarts.
- W4's getJournalState majority is {j0: 1, j2: 1}, because j1's reply arrives after the choice.
  W4 takes epoch 2.
- j1 rejects `newEpoch(2)`. `setEpoch(2)` is still applied to every logger.
- `startLogSegment` on j1 hits the target: 2 < cached 3.

Precondition: the stale JN's cache is at least `E_up + 2`.

### Safeguards and masks recorded (judged in Phase 2)
- **Quorum tolerance.** W4 continues on j0 and j2.
- **Client re-sync at the next log roll** (IPCLoggerChannel.java:364-369). It needs a successful
  `startLogSegment`, and that call also passes `checkRequest`.
- **JN self-healing.** None: a JN re-reads its disk only on restart or `format`. A newer writer
  only fixes it if j1's reply is among its getJournalState majority.
- **TV-1.** The metrics gauge loads a restarted JN's promise when its `Journal` is created by
  the first RPC. If that RPC is the rollback's `canRollBack`, the JN is stale too.

## Step 2: developer knowledge (no history about the target before the verdict, Shared Rule 2)
- Journal.java:1190-1194, in `doRollback`, refreshes two things for a JN that stays up:
  - "Do not hold file lock on committedTxnId ... It will be reopened lazily on next access."
  - "HADOOP-17142: refresh properties after rollback performed."

  Nothing is said about the epoch caches.
- `refreshCachedData` Javadoc (Journal.java:197-201): cached data must be reloaded when "no
  longer relevant".
- `TestDFSUpgradeWithHA#testRollbackWithJournalNodes` (TestDFSUpgradeWithHA.java:624-703):
  - :678: "Shut down the NNs, but deliberately leave the JNs up and running."
  - :683: `NameNode.doRollback(conf,false)`.
  - :685-688: asserts "committedTxnId has been reset correctly after rollback".

  It never starts a writer after the rollback and never checks `lastPromisedEpoch`.
- No comment, doc, or test says a JN may keep a promise above its own rolled-back disk.

## Step 3: known-status pre-filter
MC with an actual counterexample → no code-review × known drop; proceed to Phase 2.

## Phase 2 outcome (settled before any history or tracker search)
- Test: `repro/test_bugMC-2_rollback_cached_promise.java`, runner `.sh`, log `repro/MC-2.log`.
- Raw outputs: `repro-work/turn2/{run1-ce-control,run2-l0-order,run3-l0-trace,final-A,final-B,final-C-fix}`.
- Tree: pristine 734dd8a67cd for every bug run.

| Scenario | Level | Result |
|---|---|---|
| CE steps, JNRestart(j0) after Rollback | 1 (spy-held messages: SpyQJournalUtil) | target fired 4/4: W4 epoch 2 from j0=1,j2=1; j1 cache 3, disk 1 |
| Two JN restarts after rollback, nothing held | 1 | fired 4/4 |
| Level 0 natural race (production QJMs, no spies; two JN restarts after rollback; standby tail) | 0 | fired 20/20 (no RPC trace), 18/20, 18/20 (with the workload's TRACE logging) = 56/60. RPC trace: W4's getJournalState replies arrive j0=1, j2=1, then j1=3; the quorum returns at the first two. |
| CE literal order (JNRestart(j0) before Rollback) | 1 | not fired 0/4: j0's `Journal` created by `canRollBack` already shows `loaded=true value=3`; W4 picks 4 |
| Control: j1's reply in time | 1 | not fired 0/4: W4 picks 4; j2 outage tolerated |
| Fix control: `refreshCachedData()` at end of `doRollback` | n/a | all scenarios report 1,1,1; target never fires; Level 0 0/10 |

Details of the firing runs:
- **JN-side frame.** `java.io.IOException: IPC's epoch 2 is less than the last promised epoch 3`
  at `Journal.checkRequest(Journal.java:489)` ← `Journal.startLogSegment(Journal.java:572)` ←
  `JournalNodeRpcServer.startLogSegment(JournalNodeRpcServer.java:226)`.
- **Frame line vs target line.** javap of the compiled pristine class gives `line 487: 15`
  (`new IOException`) and `line 489: 27`; the `invokespecial <init>` is at 39 and `athrow` at 42.
  So the frame at :489 is the target statement 487-489.
- **j1 stays fenced.** It rejects `journal()` and the `startLogSegment` after the next roll.
- **Lost fault tolerance.** With j2 then stopped, W4's next flush fails:
  `QuorumException: Got too many exceptions to achieve quorum size 2/3` (an NN terminates:
  JournalSet.java:408, FSEditLog.java:748).

Commutation of CE states 43/44 (from the CE's own state diffs):
- JNRestart(j0) writes only `cache[j0]` and `faults.restart`.
- Rollback writes only `disk`, `prev`, and `faults.rollback`.
- Order 44 then 43 therefore reaches the identical CE state 44. The CE's later steps 45-61 apply
  unchanged.

Verdict settled from the evidence above: **REPRODUCED**.

## Step 3 (post-verdict): novelty search, all queries recorded (2026-10-29)
Run only after the verdict (adhoc-coordination Shared Rule 2). It sets Novelty only.

### Local history (pinned tree)
- `git log -L '/public synchronized void doRollback/,+8:Journal.java'` → 82de07c794f HADOOP-17142
  (2020; adds `storage.refreshStorage()`, VERSION only), eca1a4bfe95 HDFS-13695, e9c37de485f
  HDFS-7131, 80ac6aabcea HDFS-7042, edb6dc5f303 HDFS-5138.
- `git log -i --grep=rollback -- .../qjournal` → 82de07c794f HADOOP-17142, 470d4253b24 HDFS-5920.
- `git log -i -E --grep='lastPromisedEpoch|last promised|refreshCachedData|promised epoch|cached promise'`
  → no commits.
- `git log -S refreshCachedData -- Journal.java` → f6b7f067c34 HDFS-3884 "Journal format() should
  reset cached values" (2012). That is the same-shape fix for **format**, a different step.
- Newest commits on Journal.java: f609460bda0 (2023-11-20), already in the pinned tree.

### Apache JIRA REST `/rest/api/2/search`
- `project in (HDFS, HADOOP) AND text ~ "refreshCachedData"` → HDFS-14537 (format edits cache,
  fixed). Different.
- `... AND text ~ "rollback" AND (text ~ "lastPromisedEpoch" OR "last promised epoch" OR "promised epoch")`
  → HDFS-7952, HDFS-3743.
- `... AND text ~ "JournalNode" AND text ~ "doRollback"` → HDFS-5920, HDFS-5840, HDFS-5138
  (features), HDFS-10644 (test flake at the committedTxnId assert; open; no epoch).
- `... AND (text ~ "lastPromisedEpoch" OR text ~ "last-promised-epoch")` → 15 issues; none is
  this mechanism.
- `project = HDFS AND text ~ "rollback" AND text ~ "JournalNode" AND text ~ "epoch"` → HDFS-7952,
  HDFS-8298.
- `... AND text ~ "\"is less than the last promised epoch\""` → HDFS-15011, HDFS-7952,
  HDFS-11254, HDFS-11225, HDFS-9126.
- `project = HDFS AND text ~ "JournalNode" AND (rollback OR upgrade) AND updated >= -365d` →
  HDFS-17963 (edit-log compaction). Unrelated.
- Read in full:
  - **HDFS-7952** (Resolved/Duplicate of the docs fix HDFS-7934). Rolling-upgrade rollback where
    the restarted standby legitimately raises the on-disk promise and fences the active. It is
    not a stale cache.
  - **HDFS-15011** (open): the target message under failover churn and slow JNs; no rollback.
  - **HDFS-10644** (open): test flake; no epoch/cache.

### GitHub `api.github.com/search/issues`
- `repo:apache/hadoop is:pr doRollback Journal` → 0.
- `... refreshCachedData` → 0.
- `... lastPromisedEpoch` → 0.
- `... JournalNode rollback` → #2162 HDFS-15485 (merged 2020) and #2161 HADOOP-17142 (closed).
  Both are the VERSION-properties fix only.
- `... "last promised epoch"` → #6925 HDFS-16690 (auto-format new JNs). Different.
- `... JournalNode upgrade epoch` → #6925.
- `repo:apache/hadoop is:pr JournalNode updated:>=2026-07-01` → 7 PRs (Kerberos, docs, edits
  cache, auth). None relevant.
- `... Journal rollback updated:>=2025-01-01` → 0.
- `... qjournal epoch updated:>=2025-01-01` → #2966, #4565. Unrelated.
- Trunk commits touching Journal.java: newest f609460bda0 (in pinned tree).
- Trunk commits touching JournalNode.java: newest 54171ce074f (2026-08-21, jetty-util-ajax →
  jackson; not in pinned tree; unrelated).

**Novelty: NEW.** No issue, PR, or commit reports that `Journal.doRollback` leaves the
PersistentLongFile epoch caches of a JournalNode that stayed up at their post-upgrade values.
