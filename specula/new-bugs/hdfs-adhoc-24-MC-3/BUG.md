# hdfs-adhoc-24 MC-3 (tier B): stale rolling-upgrade marker makes doFinalize delete a regular upgrade's previous/

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-24`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-24/MC-3
- **defect:** `clearRollingUpgradeMarkers` (BPSS L889-909) trusts a stale rolling-upgrade marker plus a replayed finalized rolling-upgrade status, and `doFinalize` deletes a regular upgrade's `previous/`; the rollback then fails at L421
- **why tier B:** needs `-upgrade` before the next checkpoint after a DN missed a rolling-upgrade finalize (medium confidence)

**Specula's finding MC-3:** Stale DN rolling-upgrade marker plus replayed finalized RU status deletes a regular upgrade's previous/; DN rollback then throws at BlockPoolSliceStorage:421

- **Cause:** BlockPoolSliceStorage.clearRollingUpgradeMarkers calls doFinalize for every volume that still has a RollingUpgradeInProgress marker when a finalized RU status arrives, without checking that previous/ was created by that rolling upgrade; after a NameNode restart without checkpoint, OP_ROLLING_UPGRADE_START/FINALIZE are replayed, the finalized rollingUpgradeInfo does not block -upgrade and is sent in every heartbeat.
- **Trigger:** Non-HA NN: dfsadmin -rollingUpgrade prepare (DN creates markers); DN down while the RU is finalized; NN restarted with -upgrade before any checkpoint; DN restarted (regular upgrade creates previous/); its first heartbeat carries the replayed finalized RU status so doFinalize deletes previous/; documented rollback: namenode -rollback, datanode -rollback.
- **Consequence:** DataNode rollback throws java.io.IOException 'Datanode state ... is newer than the namespace state' from BlockPoolSliceStorage.doTransition (throw statement L421-424, frame :424) on every marked volume; DataStorage.recoverTransitionRead fails 'All specified directories have failed to load.', the block-pool actor exits, the NN has 0 live DataNodes and files written before the upgrade are unreadable (BlockMissingException); the regular upgrade's rollback snapshot is permanently deleted.
- **Premises:** No checkpoint between OP_ROLLING_UPGRADE_FINALIZE and the NameNode -upgrade restart (non-HA, no SecondaryNameNode checkpoint yet), so START/FINALIZE are replayed and the finalized rollingUpgradeInfo is re-created. A DataNode holds RollingUpgradeInProgress markers and does not process a heartbeat between the RU finalize and its shutdown (e.g. down during the finalize). That DataNode is restarted after the NameNode -upgrade restart; the operator later follows the documented rollback (namenode -rollback, datanode -rollback). Same software version suffices: NameNode -upgrade changes cTime (FSImage.doUpgrade), which drives the DataNode block-pool upgrade. Reproduced at Level 0 in MiniDFSCluster (3/3 runs); control with the DataNode up across the RU finalize rolls back cleanly.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_ru_marker.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-24` (all phases) | 6h09m | 552.9M | $297.19 |
| of which: confirming this finding | | 14.9M | $8.94 |

Time is active time; quota sleeps are excluded.
