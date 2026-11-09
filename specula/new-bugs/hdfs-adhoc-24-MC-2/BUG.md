# hdfs-adhoc-24 MC-2 (tier A): disk formatted during an unfinalized upgrade gets the new cTime and no previous/; rollback cannot complete

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-24`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as 26/MC-3.

## Explanation (verified)

- **case/finding:** hdfs-adhoc-24/MC-2
- **defect (root cause):** `BlockPoolSliceStorage.format` (L283-292) stamps a new disk with the upgraded NameNode cTime and creates no `previous/`; `-rollback` skips a directory without `previous/` (L375-385)
- **consequence:** after an unfinalized upgrade, a disk added or replaced in the meantime makes `doTransition` throw at the target (L421) on every `-rollback` start: **the documented rollback cannot complete on that DataNode**
- **trigger:** replacing or adding a disk during an upgrade window, then rolling back; default configuration

**Specula's finding MC-2:** Disk formatted during an unfinalized HDFS upgrade keeps the upgraded cTime and no previous/; the documented rollback then throws at BlockPoolSliceStorage:421

- **Cause:** BlockPoolSliceStorage.format (L283-292, reached from loadStorageDirectory L167-171) stamps a block-pool slice created on an empty disk with the NameNode's current cTime, which is the upgraded cTime while an upgrade is unfinalized, and creates no previous/. On the DataNode -rollback start doTransition rolls back only slices that have previous/ (L375-387), readProperties (L388) loads the upgraded cTime, and the throw at L421-424 fires. The failed slice's cTime also stays in the shared BlockPoolSliceStorage fields that DataNode.createBPRegistration (DataNode.java:2074) sends to the NameNode.
- **Trigger:** NameNode -upgrade, not finalized; a DataNode starts with an empty data directory (a new or replaced disk), which is formatted with the upgraded cTime; then the documented rollback: hdfs namenode -rollback, NameNode regular start, DataNode -rollback (start-dfs.sh -rollback).
- **Consequence:** The empty-disk slice throws java.io.IOException 'Datanode state ... is newer than the namespace state' at BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424) on the -rollback start and on every later start; DataStorage.loadBlockPoolSliceStorage drops the slice. When it is the last slice loaded, the DataNode registers with the upgraded cTime, the NameNode rejects it (verifyRequest: Registration IDs mismatched), the block-pool actor exits, the NameNode stays in safe mode and pre-upgrade files are unreadable although their replicas are intact on the rolled-back disk.
- **Premises:** An operator may add or replace an empty data disk on a DataNode while a NameNode -upgrade is unfinalized; the HDFS user guide expects days of operation before finalize and documents adding/replacing data volumes. Rollback is performed as documented: hdfs namenode -rollback (NameNode.doRollback), then a NameNode regular start and DataNode -rollback (start-dfs.sh -rollback). No code path deletes, re-formats or rolls back a block-pool slice that has no previous/; doRollback returns when previous/ is absent (BlockPoolSliceStorage.java:606-609) and nothing resets the shared BPSS cTime after a failed slice. The NameNode-rejection consequence needs the failed slice to be the last block-pool slice loaded (dfs.datanode.data.dir order, e.g. a new disk appended to the list); otherwise only that slice fails, at every start. Reproduced at escalation level 0 (MiniDFSCluster, JDK 17, pinned 734dd8a67cd, no source patch, no hand-written VERSION file).

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_rollback_gap.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-24` (all phases) | 6h09m | 552.9M | $297.19 |
| of which: confirming this finding | | 19.9M | $9.22 |

Time is active time; quota sleeps are excluded.
