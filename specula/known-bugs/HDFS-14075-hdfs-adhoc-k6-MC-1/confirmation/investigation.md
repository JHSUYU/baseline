# MC-1 Investigation (evidence only)

Target (target.yaml): `FSEditLog.endCurrentLogSegment(boolean)`, `FSEditLog.java:1409`,
`Preconditions.checkState(isSegmentOpen(), "Bad state: %s", state)` -> `IllegalStateException`.
Pinned tree: base_commit `c37cda11`. The confirmation worktree had the Phase-2.5 harness
instrumentation applied. It was stashed (`git stash` "specula harness instrumentation ...",
diff also saved as `confirmation/MC-1/instrumentation.saved.patch`), so line numbers match the
pristine tree: `sed -n 1409p FSEditLog.java` = `Preconditions.checkState(isSegmentOpen(),`.

Persistent-findings lookup (`specula findings lookup --query endCurrentLogSegment --query
BETWEEN_LOG_SEGMENTS --query TargetSafe`) -> `[]` (no prior record).

## Step 1: Code audit

Cited code (pristine line numbers):
- `FSEditLog.rollEditLog` :1314-1323: `endCurrentLogSegment(true)`, then
  `startLogSegmentAndWriteHeaderTxn(nextTxId, ...)`. Nothing restores IN_SEGMENT if the second
  call throws.
- `FSEditLog.endCurrentLogSegment` :1406-1434: checkState at :1409. Writes END_LOG_SEGMENT,
  `logSyncAll()`, then `journalSet.finalizeLogSegment(...)` in try/catch(IOException) that is
  swallowed ("All journals have failed, it will be handled in logSync."). Then
  `state = BETWEEN_LOG_SEGMENTS` (:1433) runs unconditionally.
- `FSEditLog.startLogSegment(long,int)` :1356-1391: `storage.attemptRestoreRemovedStorage()`
  (:1380), then `journalSet.startLogSegment` (:1383). On IOException it rethrows "Unable to
  start log segment N: too few journals successfully started." **before** `state = IN_SEGMENT`
  (:1390).
- `JournalSet.mapJournalsAndReportErrors` :380-414: a non-required journal's Throwable is
  caught -> `disableAndReportErrorOnJournals` (abort + setDisabled) -> if
  `!areResourcesAvailable` throw IOException("... failed for too many journals"). Only
  *required* journals call `terminate(1)` (:401).
- `FileJournalManager.finalizeLogSegment`: `NativeIO.renameTo` failure -> IllegalStateException
  (caught as Throwable by mapJournalsAndReportErrors). `FileJournalManager.startLogSegment`: a
  failed `new EditLogFileOutputStream/create` -> IOException.
- `FSNamesystem.rollEditLog` :4728-4745: superuser check, `checkOperation(JOURNAL)`, write lock,
  `checkNameNodeSafeMode`. There is no edit-log-state check, so a second roll reaches :1409.
- `FSImage.saveNamespace` :1100-1123: `editLogWasOpen = isSegmentOpen()`. Its finally-block
  restart (`startLogSegmentAndWriteHeaderTxn`) has the same stranding shape.

Call chain: `NamenodeProtocols.rollEditLog` (NameNodeRpcServer; callers are the Standby's
EditLogTailer auto-roll, the SecondaryNameNode checkpointer, and `hdfs dfsadmin -rollEdits`) ->
`FSNamesystem.rollEditLog` -> `FSImage.rollEditLog` -> `FSEditLog.rollEditLog` ->
`endCurrentLogSegment` :1409. This path is reachable in normal operation. The workload calls
`nn.rollEditLog()` 30 times.

Trigger scenario (matches CE `spec/output/MC_hunt_s1_bfs.out` S1-S13):
1. A single edits dir, the default and also TestEditLogRace#getConf (non-required, local).
2. A client edit, then a roll begins. The end-of-segment sync succeeds.
3. The edits dir fails (disk error / remounted read-only). Finalize fails, the journal is
   disabled, and endCurrentLogSegment swallows the error and sets BETWEEN_LOG_SEGMENTS.
4. startLogSegment cannot create the new in-progress file. The roll throws IOException, the NN
   is not terminated, and it stays Active with state BETWEEN_LOG_SEGMENTS.
5. The next admitted roll (before any client edit) -> IllegalStateException at :1409.

Safeguards recorded:
- `logSync` terminate(1) on "Could not sync enough journals" (FSEditLog.java ~:687-696). A
  *client edit* after stranding goes through logSync with no active journal -> terminate. So
  the window to observe :1409 is "the next roll before the next client edit", as the finding
  states. This guard does not apply to the roll path, which never reaches logSync before :1409.
- `dfs.namenode.name.dir.restore` / `attemptRestoreRemovedStorage` is only invoked from
  startLogSegment (:1380) and saveNamespace, so the failing roll never gets there (CR-3).

## Step 2: Developer-knowledge (code-local)
- The comment at the swallowed finalize error, "All journals have failed, it will be handled in
  logSync.", shows the developers expect a later logSync to handle total journal failure. No
  equivalent handling exists for the roll path.
- The startLogSegment Javadoc says "Transitions from BETWEEN_LOG_SEGMENTS state to
  IN_LOG_SEGMENT state". No rollback is documented on failure.
- Test `TestEditLog#testFailedOpen` uses `FileUtil.setWritable(logDir,false)` and expects
  "too few journals successfully started". That is the same fault idiom, but only for
  openForWrite, not for a roll followed by a second roll. No existing test rolls again after a
  failed restart.
- History / tracker search is deferred until after the verdict (adhoc Shared Rule 2). See
  "Novelty search" below.

## Step 3: Known-status
MC-sourced with an actual counterexample. No pre-filter drop, so it proceeds to Phase 2.

## Novelty search (run AFTER the reproduction verdict was settled; sets Novelty only)
Queries (Apache JIRA REST `search`, project=HDFS):
1. `text ~ "\"Bad state: BETWEEN_LOG_SEGMENTS\""` -> HDFS-2910 (Open; same symptom, *shared/required*
   edits dir during roll), HDFS-8715 (dup), HDFS-7871 (roller log spam).
2. `text ~ "\"too few journals successfully started\""` -> **HDFS-14075** (Fixed, fixVersion 3.3.0).
3. `text ~ "rollEditLog" AND text ~ "BETWEEN_LOG_SEGMENTS"` -> HDFS-10943, HDFS-14437 (different:
   bufCurrent), HDFS-2910, HDFS-4233 (Fixed 0.23.6, "NN keeps serving even after no journals started
   while rolling edit"), HDFS-14075, HDFS-11292, HDFS-1799.
4. `text ~ "endCurrentLogSegment" AND text ~ "startLogSegment" AND text ~ "fail"` -> no further match.
GitHub commit search `repo:apache/hadoop HDFS-14075` -> `042c8ef593ce` (2018-12-02) "HDFS-14075.
Terminate the namenode when failed to start log segment." Upstream trunk FSEditLog.startLogSegment
now does `terminate(1, msg)` in the catch. The pinned base (pom 3.3.0-SNAPSHOT, c37cda11) still
rethrows IOException, i.e. predates the fix.
HDFS-14075 describes the same mechanism (a rollEditLog RPC's startLogSegment fails with "too few
journals successfully started", and the NN keeps running in the stranded state) at the same site.
Novelty = KNOWN (HDFS-14075; fixed upstream in 3.3.0).
