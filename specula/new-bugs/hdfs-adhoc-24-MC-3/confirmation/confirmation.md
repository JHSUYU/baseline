# MC-3 — confirmation verdict

- **Source**: MC
- **Novelty**: NEW
- **Location**: hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java:900
- **Status**: REPRODUCED (Level 0; 3/3 runs; negative control clean)
- **Severity**: High
- **Reproduction test**: `repro/test_bugMC-3_ru_marker_rollback.sh` (runner) + `repro/test_bugMC-3_SpeculaAdhocMC3Test.java` (workload variant `org.apache.hadoop.hdfs.SpeculaAdhocMC3Test`, same module/package as `TestDFSUpgrade#testUpgrade`)

## Description
When a finalized rolling-upgrade (RU) status reaches a DataNode, `BlockPoolSliceStorage.clearRollingUpgradeMarkers` (L889-909) calls `doFinalize` (L900 → L651-689) on every volume that still carries a `RollingUpgradeInProgress` marker, deleting that volume's block-pool `previous/` without checking that the rolling upgrade created it. A marker survives when the DN is down across the RU finalize. A non-HA NameNode restarted with `-upgrade` before any checkpoint replays `OP_ROLLING_UPGRADE_START`/`FINALIZE` (FSEditLogLoader L892-918). The re-created finalized `rollingUpgradeInfo` does not block `-upgrade` (FSNamesystem L7727-7729, L7792-7796; FSImage L462), and it is sent in every heartbeat (FSNamesystem L4511-4512). So the DN deletes the **regular** upgrade's rollback snapshot right after creating it, while the NN upgrade is still un-finalized. The documented rollback then throws the target `java.io.IOException` ("Datanode state ... is newer than the namespace state") from `BlockPoolSliceStorage.doTransition`, the throw statement at L421-424; javac maps its constructor call/`athrow` to L424, which is the line the stack frame shows. The DN cannot load the block pool on any marked volume.

## Trigger scenario
Counterexample `spec/output/MC_hunt_ru_marker_bfs.out` (83 states) ↔ real operations (all public operator commands / restarts):
1. S2, S4-S25: non-HA cluster, 1 NN + 1 DN (2 volumes) running; data written.
2. S3: `hdfs dfsadmin -safemode enter; hdfs dfsadmin -rollingUpgrade prepare`.
3. S26: next heartbeat → `BPOfferService.signalRollingUpgrade` (L560-562) → `setRollingUpgradeMarkers` → marker on every volume (CE models only v1; the code marks all volumes in one call).
4. S27-S28: the RU is finalized (`hdfs dfsadmin -rollingUpgrade finalize`) while the DN is down / before it processes another heartbeat → markers stay on disk.
5. S29: regular upgrade: NN restarted with `-upgrade` (no checkpoint since the finalize) → START+FINALIZE replayed → finalized `rollingUpgradeInfo`; NN cTime c0→c1.
6. S30-S67: DN restarted → `doTransition` L414-417 (`cTime < nsInfo.cTime`) → `doUpgrade` → `previous/` (cTime c0) on every volume.
7. S69: first heartbeat carries the finalized RU status → `signalRollingUpgrade` L564-565 → `clearRollingUpgradeMarkers` → `doFinalize` L900 → `previous/` → `finalized.tmp` → deleted (NN `isUpgradeFinalized()` is still `false`).
8. S70-S72: documented rollback (HdfsUserGuide.md:322-328): stop DN, `hdfs namenode -rollback` (NN cTime back to c0), start DN with `-rollback`.
9. S73-S83: `doTransition` ROLLBACK without `previous/` → trash restore only (L382-388) → `readProperties` → LV equal, DN cTime c1 > NN cTime c0 → **throw at L421** (`TargetSafe` violated) on every marked volume → `DataStorage.recoverTransitionRead` "All specified directories have failed to load." → BP actor exits.

## Developer intent
- `BlockPoolSliceStorage.java:73-81` (verbatim): "When the rolling upgrade is not in progress: 1. If the marker file is present, then a rolling upgrade just completed. If a 'previous' directory exists, it can be deleted now. 2. If the marker file is absent, then a regular upgrade may be in progress. Do not delete the 'previous' directory." The marker exists precisely so that a regular upgrade's `previous/` is **not** deleted. The code infers "an RU just completed" from the marker's mere presence, and that inference is wrong for a stale marker. (The same javadoc still says "The NN does not inform the DN when a rolling upgrade is finalized", which is outdated: `BPOfferService.signalRollingUpgrade` now acts on `isFinalized()`.)
- `BlockPoolSliceStorage.java:419-420`: "layoutVersion == LAYOUT_VERSION && this.cTime > nsInfo.cTime / must shutdown". L421 is a fatal-inconsistency guard, not a normal path.
- `HdfsUserGuide.md:304-328`: a regular upgrade keeps one backup until `-finalizeUpgrade`, and rollback = `hdfs namenode -rollback` + `start-dfs.sh -rollback`. "until the cluster is finalized, deleting the files that existed before the upgrade does not free up real disk space on the DataNodes."
- `FSEditLogLoader.java:906-908` acknowledges that RU ops are replayed across NN restarts.
- Tests: `TestDataNodeRollingUpgrade#testDatanodeRUwithRegularUpgrade` covers RU → regular upgrade only with the DN **up** through the RU finalize. No test covers a DN that missed the finalize, or a rollback afterwards.
- Post-verdict tracker search (it set Novelty only): HDFS-6981, the origin of the marker, states the same intent: "'previous' is cleaned up only if the marker file is present. Else a regular upgrade is in progress and 'previous' is left alone." In HDFS-7645, the finalized status was assumed to be non-null "only till NN is restarted". The replay above contradicts that when no checkpoint follows the finalize. No issue, PR, or commit reports this mechanism (17 queries, logged in `confirmation/MC-3/investigation.md`).

## Reproduction result
**PASS, bug triggered at Level 0, 3/3 runs.**

Command: `REPEAT=3 /users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/repro/test_bugMC-3_ru_marker_rollback.sh`. This copies the variant into the pinned worktree (`734dd8a67cd`, tracked files unmodified) and runs `mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs -Dtest=SpeculaAdhocMC3Test -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`, then `mvn -B -o surefire:test …` twice more.

Three test methods, identical except around the RU finalize:
- `testStaleRuMarkerBreaksRegularUpgradeRollback` (DN_DOWN_FIRST, **Level 0**): DN stopped, then RU finalized.
- `testCounterexampleOrderFinalizeThenDnStop` (CE_ORDER, Level 1, ordering only): exact S27→S28 order, with heartbeats paused through the codebase's `DataNodeTestUtils.setHeartbeatsDisabledForTests`.
- `testControlDnUpAcrossRuFinalize` (CONTROL): the DN stays up through the finalize, so a heartbeat clears its markers first.

The test only **reads** VERSION files, markers, and directories. It never writes the guard operands and never edits the target method.

Output excerpt from `repro/MC-3.run.out`. Lines are verbatim; `$T` and `$BP` abbreviate the JUnit temp dir and the block-pool id.
```
=== run 1/3: mvn test exit=0 (log: /users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/repro/MC-3.mvn.run1.log)
--- target throw in the compiled class (javap -l): bytecode -> source line
  bci 339 -> line 421: new class java/io/IOException
  bci 364 -> line 424: invokespecial Method java/io/IOException."<init>":(Ljava/lang/String;)V
  bci 367 -> line 424: athrow
[MC-3][DN_DOWN_FIRST] cluster up: 1 NN (non-HA), 1 DN with 2 volumes; bpid=$BP NN cTime c0=1793282166253
[MC-3][DN_DOWN_FIRST] after RU prepare + heartbeat:
    vol1 $T/data/data1/current/$BP: marker=true previous/=false finalized.tmp=false current.cTime=1793282166253
    vol2 $T/data/data2/current/$BP: marker=true previous/=false finalized.tmp=false current.cTime=1793282166253
[MC-3][DN_DOWN_FIRST] DN stopped, then dfsadmin -rollingUpgrade finalize; NN rollingUpgradeInfo=Block Pool ID: $BP Start Time: Thu Oct 29 13:56:07 UTC 2026 (=1793282167907) Finalize Time: Thu Oct 29 13:56:08 UTC 2026 (=1793282168357)
[MC-3][DN_DOWN_FIRST] on disk while DN is down:
    vol1 $T/data/data1/current/$BP: marker=true previous/=false finalized.tmp=false current.cTime=1793282166253
    vol2 $T/data/data2/current/$BP: marker=true previous/=false finalized.tmp=false current.cTime=1793282166253
[MC-3][DN_DOWN_FIRST] NN restarted with -upgrade: cTime c1=1793282168956 isUpgradeFinalized=false rollingUpgradeInfo(replayed)=Block Pool ID: $BP Start Time: Thu Oct 29 13:56:07 UTC 2026 (=1793282167907) Finalize Time: Thu Oct 29 13:56:08 UTC 2026 (=1793282168357)
[MC-3][DN_DOWN_FIRST] DataNode storage log after the DN restart (in order):
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,450 [pool-170-thread-2] INFO  common.Storage (BlockPoolSliceStorage.java:doUpgrade(518)) - Upgrade of block pool $BP at $T/data/data1/current/$BP is complete
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,450 [pool-170-thread-1] INFO  common.Storage (BlockPoolSliceStorage.java:doUpgrade(518)) - Upgrade of block pool $BP at $T/data/data2/current/$BP is complete
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,515 [$BP heartbeating to localhost/127.0.0.1:36891] INFO  common.Storage (BlockPoolSliceStorage.java:clearRollingUpgradeMarkers(899)) - Deleting $T/data/data1/current/$BP/RollingUpgradeInProgress
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,515 [$BP heartbeating to localhost/127.0.0.1:36891] INFO  common.Storage (BlockPoolSliceStorage.java:doFinalize(663)) - Finalizing upgrade for storage directory $T/data/data1/current/$BP.
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,515 [$BP heartbeating to localhost/127.0.0.1:36891] INFO  common.Storage (BlockPoolSliceStorage.java:clearRollingUpgradeMarkers(899)) - Deleting $T/data/data2/current/$BP/RollingUpgradeInProgress
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:14,515 [$BP heartbeating to localhost/127.0.0.1:36891] INFO  common.Storage (BlockPoolSliceStorage.java:doFinalize(663)) - Finalizing upgrade for storage directory $T/data/data2/current/$BP.
[MC-3][DN_DOWN_FIRST] NN regular upgrade finalized? false; on disk:
    vol1 $T/data/data1/current/$BP: marker=false previous/=false finalized.tmp=false current.cTime=1793282168956
    vol2 $T/data/data2/current/$BP: marker=false previous/=false finalized.tmp=false current.cTime=1793282168956
[MC-3][DN_DOWN_FIRST] namenode -rollback done; NN cTime=1793282166253 (c0=1793282166253)
[MC-3][DN_DOWN_FIRST] datanode -rollback: target check failed. Captured log:
  | 2026-10-29 13:56:20,457 [Thread-838] WARN  common.Storage (BlockPoolSliceStorage.java:loadBpStorageDirectories(230)) - Failed to analyze storage directories for block pool $BP
  | java.io.IOException: Datanode state: LV = -57 CTime = 1793282168956 is newer than the namespace state: LV = -67 CTime = 1793282166253
  |     at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)
  |     at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.loadStorageDirectory(BlockPoolSliceStorage.java:181)
  |     at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.loadBpStorageDirectories(BlockPoolSliceStorage.java:226)
  |     at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.recoverTransitionRead(BlockPoolSliceStorage.java:257)
  |     at org.apache.hadoop.hdfs.server.datanode.DataStorage.loadBlockPoolSliceStorage(DataStorage.java:464)
  |     at org.apache.hadoop.hdfs.server.datanode.DataStorage.addStorageLocations(DataStorage.java:396)
  |     at org.apache.hadoop.hdfs.server.datanode.DataStorage.recoverTransitionRead(DataStorage.java:566)
  |     at org.apache.hadoop.hdfs.server.datanode.DataNode.initStorage(DataNode.java:2263)

[MC-3][DN_DOWN_FIRST] after datanode -rollback: live DNs at NN=0, DN fully started=true, BP service alive=false, 'Initialization failed' log lines=1, L421 hits=4, NN safemode=false
[MC-3][DN_DOWN_FIRST]   log| 2026-10-29 13:56:20,462 [Thread-838] ERROR datanode.DataNode (BPServiceActor.java:run(920)) - Initialization failed for Block pool <registering> (Datanode Uuid cd22edbd-d723-48f2-a1ea-2fdb07e71a0a) service to localhost/127.0.0.1:36891. Exiting.
[MC-3][DN_DOWN_FIRST] on disk:
    vol1 $T/data/data1/current/$BP: marker=false previous/=false finalized.tmp=false current.cTime=1793282168956
    vol2 $T/data/data2/current/$BP: marker=false previous/=false finalized.tmp=false current.cTime=1793282168956
[MC-3][DN_DOWN_FIRST] read /mc3/written-before-upgrade.dat written before the upgrade FAILED: org.apache.hadoop.hdfs.BlockMissingException: Could not obtain block: $BP:blk_1073741825_1001 file=/mc3/written-before-upgrade.dat No live nodes contain current block Block locations: Dead nodes:
[MC-3][DN_DOWN_FIRST] RESULT: BUG TRIGGERED -- TargetSafe violated, thrown at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)
...
[MC-3][CONTROL] NN regular upgrade finalized? false; on disk:
    vol1 $T/data/data1/current/$BP: marker=false previous/=true finalized.tmp=false current.cTime=1793282118377 previous.cTime=1793282112896
    vol2 $T/data/data2/current/$BP: marker=false previous/=true finalized.tmp=false current.cTime=1793282118377 previous.cTime=1793282112896
[MC-3][CONTROL] namenode -rollback done; NN cTime=1793282112896 (c0=1793282112896)
[MC-3][CONTROL] after datanode -rollback: live DNs at NN=1, DN fully started=true, BP service alive=true, 'Initialization failed' log lines=0, L421 hits=0, NN safemode=false
[MC-3][CONTROL] read /mc3/written-before-upgrade.dat written before the upgrade: OK, contents identical
[MC-3][CONTROL] RESULT: rollback succeeded, no L421
[MC-3][CE_ORDER] RESULT: BUG TRIGGERED -- TargetSafe violated, thrown at org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)
=== run 2/3: mvn surefire:test exit=0 (log: /users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/repro/MC-3.mvn.run2.log)
surefire: [INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0
=== run 3/3: mvn surefire:test exit=0 (log: /users/ZhenyuLi/Specula/runs/20261029-090048-2c84/hdfs-adhoc-24/.specula-output/repro/MC-3.mvn.run3.log)
surefire: [INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0
MC-3 REPRODUCED in 3/3 runs (control clean in every run)
```
The bug shows in these lines:
- `Upgrade of block pool … is complete` is followed by `clearRollingUpgradeMarkers(899) - Deleting …/RollingUpgradeInProgress` and `doFinalize(663) - Finalizing upgrade`, with `NN regular upgrade finalized? false` and `previous/=false` on both volumes. The snapshot was destroyed.
- `java.io.IOException: Datanode state: … is newer than the namespace state` at `BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)`. javap of the compiled worktree class shows `new java/io/IOException` at bci 339 → line 421 and `invokespecial <init>` / `athrow` (bci 364/367) → line 424, so this frame is the target throw statement that begins at L421.
- `Initialization failed for Block pool … Exiting.`, `live DNs at NN=0`, and `BlockMissingException` show the consumer-side harm.

Expected (correct) behaviour, shown by CONTROL: `previous/=true` (previous.cTime = c0) survives the finalized-status heartbeat, the DN rollback restores cTime c0, the DN registers (`live DNs at NN=1`), the pre-upgrade file is read back identical, and there are no L421 hits.

Attempt 1 (logs `repro/MC-3.attempt1.*`) triggered the same throw. It was marked failed only because the first assertion expected the literal `:421` in the frame; the javap mapping above explains the `:424` frame.

Same-bug check (adhoc Phase 4), all met:
- Thrown type `java.io.IOException`, from `BlockPoolSliceStorage.doTransition`, at the L421 throw statement.
- The test is a variant of the workload in `hadoop-hdfs`.
- It uses only the counterexample's actions: RU prepare/finalize, DN stop/start, NN `-upgrade`, NN rollback, DN `-rollback`.
- Operand writes: none. Target-method edits: none.

## Recommendation
- **DN fix (root cause):** `clearRollingUpgradeMarkers` must not finalize a `previous/` that the rolling upgrade did not create. For example, record the block-pool cTime/LV in the marker when `setRollingUpgradeMarkers` creates it. Then call `doFinalize` only if the volume's current cTime still matches; otherwise just delete the stale marker. A regular upgrade always changes cTime (`FSImage.doUpgrade` L465 `storage.cTime = now()`).
- **Equivalent alternative:** delete any pre-existing marker in `doTransition`'s regular-upgrade branch (L414-417) before `previous/` is created. A regular upgrade cannot start while an RU is in progress (`FSImage.doUpgrade` → `checkRollingUpgrade`, L462), so a marker present at that point is necessarily stale.
- **NN defense in depth:** stop advertising a pre-upgrade *finalized* RU status after `-upgrade`. For example, clear the finalized `rollingUpgradeInfo` in `FSImage.doUpgrade` once `checkRollingUpgrade` passes. Also fix the stale javadoc at BPSS L73-81.
- **Regression test:** add `SpeculaAdhocMC3Test`'s DN_DOWN_FIRST scenario: the rollback must succeed and `previous/` must survive.
- **Operator mitigation until fixed (untested here):** before a regular `-upgrade`, make sure every DN processed a heartbeat after `-rollingUpgrade finalize`, or remove `<vol>/current/<bpid>/RollingUpgradeInProgress` on DNs that were down, or checkpoint after the finalize so the START/FINALIZE edits are not replayed.
