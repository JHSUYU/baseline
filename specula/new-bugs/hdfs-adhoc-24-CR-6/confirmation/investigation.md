# CR-6 investigation record

Finding: a block-pool (BP) slice that still has `previous/` but misses the DataNode (DN) `-rollback` start keeps the
upgraded cTime and throws at `BlockPoolSliceStorage.java:421` (Scenario 2, sub-mechanism 2b).
Source: code review (no counterexample assigned). Target: hdfs-adhoc-24, `BlockPoolSliceStorage.doTransition` L421,
`java.io.IOException`. Tree: `734dd8a67cd` (worktree `confirmation/CR-6/worktree`, pristine; only the reproduction test
is added, untracked). Paths below are relative to
`hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/`.

## Step 1: code audit

### Sites
- `datanode/BlockPoolSliceStorage.java:375-379`: `doRollback` runs only if `startOpt == ROLLBACK && previous exists`.
- `:388`: `readProperties(sd)` writes the shared fields `this.layoutVersion` and `this.cTime` from the volume's VERSION.
- `:404-418`: the regular-start return (`cTime == nsInfo.cTime`) and the upgrade return (`cTime < nsInfo.cTime`).
- `:419-424`: `// must shutdown`, followed by `throw new IOException("Datanode state: LV = ...")`, which is the target. The statement spans
  L421-L424. javap of the pristine build (`logs/javap_L421_throw.txt`) shows `new java/io/IOException` at pc 339 = line 421.
  The constructor call `invokespecial` at pc 364 lies in the `line 424: 352` range, so the JVM frame of this throw reads
  `BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)`. The message prefix `"Datanode state: LV = "` occurs only
  at L421 in the main sources. The workload's own L421 throw ("DataNode upgrade with newer fsscTime in current") shows
  the same `:424` frame.
- `:603-645`: `doRollback`. It renames current to removed.tmp (L637), then previous to current (L640), then deletes removed.tmp (L643).
- `common/Storage.java:771-780`, `:813-817`: removed.tmp with previous and without current is RECOVER_ROLLBACK, which runs
  `rename(removed.tmp, current)`. That **undoes** the interrupted rollback. Whether the rollback is retried then depends only on the startup
  option of the next process.
- `datanode/DataNode.java:3424-3455`: the startup option is per process (`-rollback` or REGULAR).
- `datanode/DataStorage.java:403-448` (`loadDataStorage`): a volume that fails its check at start is skipped. It needs
  `dfs.datanode.failed.volumes.tolerated` ≥ 1, which `StorageLocationChecker` and `FsDatasetImpl:320-343` enforce.
  `:450-501` (`loadBlockPoolSliceStorage`) loads volumes **sequentially**, and at L473-476 the L421 IOException is only logged
  (`"Failed to add storage directory {} for block pool {}"`). `:564-568` throws "All specified directories have failed to
  load." only if every volume failed.
- `datanode/DataStorage.java:324-346` (`prepareVolume`, hot swap): the BP load uses HOTSWAP, never ROLLBACK.
- Consumers after a startup L421 that is only logged:
  - `fsdataset/impl/FsDatasetImpl.java:361-363` adds every DN-level storage dir as a volume, including one whose BP load
    failed. `FsVolumeImpl.addBlockPool` (`:1118-1131`) then creates a `BlockPoolSlice` over that volume's (upgraded) `current/`.
  - `datanode/DataNode.java:2073-2074` (`createBPRegistration`) uses the shared `storage.getBPStorage(bpid)`. Its cTime is the
    last value read at L388. The registration ID is `NS-<nsid>-<cid>-<cTime>` (`common/Storage.java:1417-1420`).
    `namenode/NameNodeRpcServer.java:1777-1785` (`verifyRequest`) rejects a mismatch with `UnregisteredNodeException`, and
    `BPServiceActor.java:793-796` then shuts the block-pool service down.
  - `namenode/NameNodeRpcServer.java:1682-1686` returns a `FinalizeCommand` for every block report once
    `isUpgradeFinalized()` holds. `FSImage.java:568` sets that flag at the end of NN `doRollback`. `DataStorage.java:1016-1028`
    (`finalizeUpgrade`) then calls `BlockPoolSliceStorage.doFinalize` (`:651-689`, deletes BP `previous/`) for **every**
    DN-level dir, including a volume whose BP load failed at L421.

### Call chains (reachable through public entry points)
- Startup: `BPServiceActor.connectToNNAndHandshake` → `BPOfferService.verifyAndSetNamespaceInfo` →
  `DataNode.initBlockPool` → `initStorage` (startOpt from `getStartupOption`) → `DataStorage.recoverTransitionRead` →
  `addStorageLocations` → `loadBlockPoolSliceStorage` → `BlockPoolSliceStorage.recoverTransitionRead` →
  `loadBpStorageDirectories` → `loadStorageDirectory` (`analyzeStorage` / `doRecover`) → `doTransition` → L421.
- Hot swap: `dfsadmin -reconfig datanode … start` → `ReconfigurableBase.ReconfigurationThread` →
  `DataNode.reconfigurePropertyImpl` → `refreshVolumes` → `FsDatasetImpl.addVolume` → `DataStorage.prepareVolume` →
  `loadBpStorageDirectories(HOTSWAP)` → `doTransition` → L421.

### Trigger scenario (fault model: modeling brief §1 "In": DN crash/restart at any persistent-step boundary; a volume going offline and back; hot swap; documented NN -rollback paired with DN -rollback)
1. Cluster at cTime C0. Upgrade: NN `-upgrade` (C1 = now), DN regular start, so every BP slice becomes current(C1) plus previous(C0).
2. Documented rollback: NN `-rollback` (C0), then DN started with `-rollback`.
3. (2b-offline) One disk is offline during that start, so it is skipped and keeps current(C1) plus previous(C0). Later it is back and
   is (a) hot-swapped in, or (b) loaded by a regular DN restart.
   (2b-crash) The DN crashes after L637 on volume k. RECOVER_ROLLBACK restores current(C1). A default restart (for example a supervisor)
   loads volumes k..n with C1.
4. L388 reads C1. C1 > NN C0 with the same LV, so L421 throws.

### Safeguards recorded (Phase 2 tested whether each fires)
- L421 itself, the designed refusal of a newer slice. It is caught and only logged at `DataStorage.java:473-476`, so it does not stop the
  volume from being served (`FsDatasetImpl.java:361-363`).
- The NN registration-ID check (`NameNodeRpcServer.java:1777-1785`) catches the stale cTime only if the stale volume was
  read last. The result is that the whole BP service of the DN shuts down.
- NN safe mode with "bytes in future" (`BlockManagerSafeMode.java:339-348`, `:387-390`) refuses a plain `-safemode leave`
  after post-upgrade blocks are reported. Its status text tells the operator: "If you encountered this during a rollback,
  it is safe to exit with -safemode forceExit." It does not stop the `FinalizeCommand`.

## Step 2: developer knowledge (code, comments, docs, tests; history and tracker deferred to after the verdict, per adhoc Shared Rule 2)
- Comment at L419-420: `// layoutVersion == LAYOUT_VERSION && this.cTime > nsInfo.cTime // must shutdown`. The designers
  intend this state to stop the DN.
- `TestDFSUpgrade#testUpgrade` step "DataNode upgrade with newer fsscTime in current" (`test/.../TestDFSUpgrade.java:304-321`)
  hand-writes cTime=Long.MAX_VALUE and expects the block pool to fail (`startBlockPoolShouldFail`). The check is meant to
  refuse a newer slice for the whole block pool.
- `TestDFSStorageStateRecovery` case 12 (`test/.../TestDFSStorageStateRecovery.java:80-100 (case 12 at :98)`, `:409-438`) builds the BP state left by a
  crash inside `doRollback` (removed.tmp and previous, no current), starts the DN **REGULAR**, and expects it to "recover and
  startup". The developers' own model of the restart after an interrupted rollback is a regular start, with success
  expected. Their fixture has the NN's cTime, so it never meets L421.
- `TestDFSRollback#testRollback` and `HdfsUserGuide.md:326-328` document the procedure: `hdfs namenode -rollback`, then
  `start-dfs.sh -rollback` (`src/main/bin/start-dfs.sh:71`). Nothing documents how a DN volume that missed that start is
  rolled back later.
- `BlockManagerSafeMode.java:347-348` advises forceExit "during a rollback". The developers anticipate DNs that report
  post-upgrade blocks after a rollback.

## Step 3: known-status / precedent (queries run after the reproduction verdict was settled; Novelty only)
Apache JIRA (REST, project HDFS):
1. `text ~ "\"newer than the namespace state\""` returned HDFS-14311 (Fixed, a multi-threaded layoutVersion race when loading BP storage).
   That is a different mechanism (concurrent loaders), not a missed rollback.
2. `text ~ "datanode rollback" AND (crash OR "removed.tmp" OR volume OR "hot swap")` returned 11 issues (HDFS-6727, 17488, 6800, 7645,
   8791, 5526, 550, 5138, 7820, 1365, 4015). None reports this mechanism.
3. `text ~ "\"Registration IDs mismatched\"" OR "\"from previous rollback\"" OR RECOVER_ROLLBACK OR "\"Datanode state: LV\""`
   returned 17 issues (HDFS-15569, 6034, 14311, 8552, 8127, 6832, 3248, 11886, 11270, 2699, 5840, 550, 5138, 955, 16349, 2301, 5223). None matches.
   HDFS-8127 (NN failover during HA upgrade makes DNs finalize) is a precedent at the same consumer (`FinalizeCommand`)
   with a different trigger.
4. `summary ~ rollback AND summary ~ (datanode|DN|volume|"block pool"|storage)` returned HDFS-11889, 6339, 6137, 6005. None matches.
5. `text ~ rollback AND ("failed volume"|"volume failure"|"disk failure"|failed.volumes.tolerated|FinalizeCommand|DNA_FINALIZE)`
   returned HDFS-10301, 7645, 7575, 6800. None matches.
6. `text ~ rollback AND created >= 2025-01-01` returned HDFS-17963, 17932, 17839. None matches.
GitHub (apache/hadoop PRs, sorted by updated, open and closed):
7. `is:pr rollback BlockPoolSliceStorage` returned 0 items.
8. `is:pr rollback datanode` returned 9 closed PRs, the newest HDFS-17987 (closed 2026-10-17, TestDataNodeLifeline). None matches.
9. `is:pr BlockPoolSliceStorage OR DataStorage OR doRecover` returned 9 PRs (HDFS-17987, 17496 ×3, 17240, 15937, 15643, 15416 ×2). None matches.
Web:
10. WebSearch for `HDFS DataNode rollback volume "newer than the namespace state" crash removed.tmp OR "hot swap" OR "failed volume"`
    found no report.
Local history (pinned tree):
11. `git log -- BlockPoolSliceStorage.java`, `--grep=rollback` (datanode, Storage): HDFS-6005, HDFS-5966, HDFS-3970.
    These are other defects.
12. `--grep 'removed.tmp|RECOVER_ROLLBACK|interrupted rollback|crash.*rollback'`, `--grep 'registration id'`, `--grep hot.?swap`
    returned nothing. `--grep finaliz` returned HDFS-8676 (rolling-upgrade finalization timing, a different defect). The pickaxe
    `-S "is newer than the namespace state"` did not finish within the time budget (shared repository auto-packing).

Result: no issue, PR, advisory or commit reports this mechanism at this site, so **Novelty: NEW**. The pre-filter does not apply
(the finding is not already reported).

## Phase 2: reproduction (details in the verdict body)
Test `repro/test_bugCR-6_rollback_missed_volume.java` (installed as `SpeculaAdhocCR6Test` in `org.apache.hadoop.hdfs`, the
workload's package) and driver `repro/test_bugCR-6_rollback_missed_volume.sh`. Final run:
`repro/test_bugCR-6_rollback_missed_volume.run.log`, `.surefire.txt` (Tests run: 6, Failures: 0, Errors: 0), `.cr6.txt` and
`.output.txt`.
- Control (no fault): no L421; all restored files are readable.
- Level 0, offline volume, then hot swap: L421 via `DataStorage.prepareVolume:341`; the volume is not re-added; its restored files
  are missing (2).
- Level 0, offline volume listed last, then regular restart: L421, then registration ID mismatch (C1 against C0); the DN's BP service ends; all 4
  restored files are unreadable. A `-rollback` restart recovers them.
- Level 0, offline volume listed first, then regular restart: L421; the stale volume is served; the NN's FinalizeCommand deletes its
  `previous/`; the restored files' replicas exist on no disk. Reads give BlockMissingException and the NN counts 2 missing blocks. A `-rollback` restart
  hits L421 again and recovers nothing (permanent loss).
- Level 1, a real DN JVM `-rollback` paused by JDI at `doRollback:640` and SIGKILLed, then a default restart: RECOVER_ROLLBACK, then L421,
  then the registration mismatch and the BP service ends (crash on the 2nd volume), or "All specified directories have failed to load"
  (crash on the 1st). A `-rollback` restart recovers.
Harness notes: the first hot-swap attempt used the final `ReconfigurableBase.reconfigureProperty`. It holds
`synchronized(getConf())` while the add-volume worker needs the same monitor, so it stalled for 300 s (a test artifact).
The final test calls `reconfigurePropertyImpl`, which is what `ReconfigurationThread` (`dfsadmin -reconfig`) and
`TestDataNodeHotSwapVolumes` call. During one run the worktree's tracked files were rewritten with identical
content by an external process. `git status` showed no tracked change before and after the final run (provenance line in
`run.log`).
