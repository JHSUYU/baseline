# hdfs-adhoc-24 CR-6 (tier B): failed block-pool dir still finalized; a volume that missed -rollback loses previous/

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-24`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator). Same defect as 24/CR-2, 26/MC-2.

## Explanation (verified)

- **case/finding:** hdfs-adhoc-24/CR-6 (=CR-2)
- **defect:** a block-pool directory that fails to load is only logged (`DataStorage` L473-476), but `finalizeUpgrade` (L1019-1029) still finalizes it; a volume that missed the `-rollback` start fails the target (L421) and then loses its `previous/` for good
- **why tier B:** needs `dfs.datanode.failed.volumes.tolerated` ≥ 1 (common, not the default)

**Specula's finding CR-6:** Volume that misses the DataNode -rollback start (offline disk or crash after L637) keeps the upgraded cTime and throws at BlockPoolSliceStorage L421

- **Cause:** doRollback is the only way back to the rolled-back NN cTime and runs only when the load's per-process startOpt is ROLLBACK and previous/ exists (BlockPoolSliceStorage.java:375-379). A slice that misses that start (disk offline and skipped, DataStorage.java:403-448; or DN crash after rename(current, removed.tmp) at L637, which RECOVER_ROLLBACK undoes, Storage.java:813-816) is loaded later by hot swap (HOTSWAP) or a start without -rollback; L388 reads the upgraded cTime and L421 throws. At startup the IOException is only logged (DataStorage.java:473-476): the volume stays a DataStorage dir and FsDataset volume, and its cTime stays in the shared BlockPoolSliceStorage used for registration.
- **Trigger:** Non-rolling upgrade (NN -upgrade, DN start), then the documented rollback (NN -rollback, DN started with -rollback) while one data volume is offline (dfs.datanode.failed.volumes.tolerated >= 1) or while the DN crashes right after BlockPoolSliceStorage.java:637; the volume is later re-added by hot swap (dfsadmin -reconfig) or the DN is restarted with default options (e.g. by a supervisor).
- **Consequence:** IOException from BlockPoolSliceStorage.doTransition (statement at L421, JVM frame :424). Hot swap: the repaired volume cannot be re-added and the rolled-back files whose replicas sit on it stay missing. Restart with the stale volume read last (always in the crash form): the DN registers with the stale cTime, the NN rejects it (registration ID mismatch) and the DN's whole block pool service ends, so all its replicas are unavailable until a -rollback restart. Restart with the stale volume read before a healthy one: the stale slice is served and the FinalizeCommand the rolled-back NN returns for the block report deletes its previous/, permanently destroying the only replicas of files restored by the rollback; a later -rollback restart hits L421 again and recovers nothing.
- **Premises:** Ad hoc target hdfs-adhoc-24: the oracle is the target check (TargetSafe), an IOException thrown by the statement starting at BlockPoolSliceStorage.java:421; javac maps its constructor call to line 424, so the JVM frame reads :424. The NN has been rolled back after a non-rolling upgrade: its cTime is the pre-upgrade value and isUpgradeFinalized() is true (FSImage.java:568), so every block report gets a FinalizeCommand (NameNodeRpcServer.java:1682-1686). A volume with BP previous/ is not loaded by the DN -rollback start (disk offline with dfs.datanode.failed.volumes.tolerated >= 1, or DN crash after L637) and is later loaded by hot swap or by a start without -rollback; per modeling-brief section 1 these faults (DN crash/restart, volume offline and back, hot swap) are in the fault model, while a DN started without -rollback right after an NN rollback with no fault is not. Startup loads volumes sequentially in dfs.datanode.data.dir order into one shared BlockPoolSliceStorage, so the consequence depends on whether the stale volume is read last (registration rejected, recoverable) or before a healthy volume (served, previous/ finalized, permanent loss). No upstream issue or PR reported this mechanism as of 2026-10-29 (JIRA, GitHub and local-history queries recorded in confirmation/CR-6/investigation.md).

## Evidence

- TLC: none (code-review finding); the evidence is the reproduction.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-24` (all phases) | 6h09m | 552.9M | $297.19 |
| of which: confirming this finding | | 32.1M | $24.01 |

Time is active time; quota sleeps are excluded.
