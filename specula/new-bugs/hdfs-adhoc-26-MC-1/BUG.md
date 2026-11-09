# hdfs-adhoc-26 MC-1 (tier B): DN doUpgrade deletes an existing previous/; a DN down during one rollback is silently re-upgraded

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-26`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-26/MC-1
- **defect:** a DataNode's block-pool `doUpgrade` upgrades whenever its cTime is below the NameNode's (BPSS L414-417) and **unconditionally deletes an existing `previous/`** (L477-480), which the NameNode refuses for itself (`FSImage.checkUpgrade` L424-431); a DN that was down during `namenode -rollback` is silently re-upgraded after the next upgrade, losing its pre-upgrade snapshot, so rolling back that upgrade throws at the target (L621) on every volume
- **why tier B:** needs a DN down during one rollback and a second upgrade that is rolled back too (medium confidence); no data loss with replication ≥ 2

**Specula's finding MC-1:** DataNode that misses an NN rollback silently re-upgrades its abandoned epoch, so the next rollback throws at BlockPoolSliceStorage.java:621

- **Cause:** BlockPoolSliceStorage.doTransition upgrades any block-pool dir whose cTime is older than the NameNode's (BPSS:414-417), and doUpgrade deletes an existing un-finalized previous without checking it (BPSS:477-480) before snapshotting current as previous (BPSS:486, 512-517). A DataNode that missed an NN rollback (current=c1, previous=c0) is therefore silently upgraded after a re-upgrade to c2>c1: its only valid c0 snapshot is deleted and the abandoned c1 epoch becomes previous.
- **Trigger:** Upgrade c0->c1; a DataNode is out of service through `hdfs namenode -rollback` and the rollback window; the operator re-upgrades (c2=now()>c1, allowed by FSImage.checkUpgrade because the NN has no previous); the repaired DataNode starts normally; later `hdfs namenode -rollback` again and the DataNode is started with -rollback.
- **Consequence:** BlockPoolSliceStorage.doRollback throws InconsistentFSStateException at BPSS:621 (previous cTime c1 > namespace cTime c0) on every volume; DataStorage.recoverTransitionRead fails ('All specified directories have failed to load'), the BPServiceActor exits, the DataNode never rejoins (a REGULAR restart is refused at BPSS:421-424), and replicas held only by it are unreadable (BlockMissingException). The c0 snapshot is gone, so recovery needs manual storage surgery.
- **Premises:** A DataNode can be out of service for the whole window of a regular (non-rolling) upgrade rollback and be repaired only after the operator has re-upgraded. During an upgrade DataNodes start without -rollback (only the NameNode gets -upgrade), and the NameNode handshake (NamespaceInfo) carries no information about rolled-back upgrades. The re-upgrade cTime is now() and the wall clock advances between upgrades, so c2 > c1 (no clock skew needed). Reproduced at Level 0 on pristine base_commit 734dd8a67cd with MiniDFSCluster, two volumes on one DataNode, and an unchanged DataNode layout version (LV -57 throughout); a DataNode layout-version change was not tested.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_S1_dn_outage.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-26` (all phases) | 4h10m | 429.8M | $236.47 |
| of which: confirming this finding | | 15.1M | $8.65 |

Time is active time; quota sleeps are excluded.
