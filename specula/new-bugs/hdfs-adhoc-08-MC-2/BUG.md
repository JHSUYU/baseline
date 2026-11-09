# hdfs-adhoc-08 MC-2 (tier B): Journal.doRollback does not refresh cached epochs; a JN left up through rollback fences the next writer

System: hdfs. Found by Specula's ad hoc run `hdfs-adhoc-08`; verified as a real, severe, new bug that makes the ad hoc check fail (source re-read by the operator).

## Explanation (verified)

- **case/finding:** hdfs-adhoc-08/MC-2
- **defect:** `Journal.doRollback` (L1189-1196) refreshes the storage properties but not the cached epochs (`refreshCachedData`, L202-212); a JN left running through `namenode -rollback` fences the next writer
- **why tier B:** needs the rollback procedure with the JNs left up; it clears when that JN restarts

**Specula's finding MC-2:** Journal.doRollback keeps the cached lastPromisedEpoch, so a JournalNode that stayed up fences the next writer at Journal.checkRequest

- **Cause:** Journal.doRollback (Journal.java:1189-1196) renames previous/ back to current/ and re-reads VERSION but never calls refreshCachedData() (Journal.java:202-213; format() does at :259), and JournalNode.doRollback (JournalNode.java:487-491) runs on the live Journal. The PersistentLongFile caches of lastPromisedEpoch/lastWriterEpoch (PersistentLongFile.java:53-59) of a JournalNode that stays up across 'namenode -rollback' therefore keep their post-upgrade values while the disk holds the pre-upgrade ones.
- **Trigger:** After an HA upgrade at epoch E_up, two or more later active NameNodes raise a JN's (j1) promise to E_up+2 or more; 'namenode -rollback' runs with j1 left running (documented procedure); the next writer's getJournalState majority comes from JNs that report the rolled-back promise (restarted after the rollback, or never saw the post-upgrade epochs) while j1's reply arrives after that majority, so the writer picks an epoch below j1's cached promise (QuorumJournalManager.java:232-242).
- **Consequence:** j1 rejects every request of the only live writer with java.io.IOException 'IPC's epoch 2 is less than the last promised epoch 3' from the target throw of Journal.checkRequest (Journal.java:487-489, JVM frame Journal.java:489), including startLogSegment after each log roll; the writer runs on 2 of 3 JNs and its next flush fails with QuorumException once one more JN is down, which terminates the NameNode (JournalSet.java:395-408, FSEditLog.java:735-748).
- **Premises:** JournalNodes stay running across 'namenode -rollback', as the HA upgrade/rollback procedure requires (HDFSHighAvailabilityWithQJM.md:708-712, 733); NameNodes may be restarted between upgrade and rollback (:727). A JN that stayed up caches a promise at least two above the upgrade-time promise (two or more writers became active between upgrade and rollback). The next writer's getJournalState quorum consists of JNs whose promise equals the rolled-back value and the stale JN's reply arrives after that quorum (observed naturally in 56 of 60 Level 0 iterations; forced deterministically at Level 1 with SpyQJournalUtil spies). A JN restarted before the rollback is stale as well: its Journal is created by the rollback's canRollBack RPC and the JournalMetrics gauge loads the pre-rollback promise during construction (JMX getMBeanInfo/updateJmxCache); only JNs restarted after the rollback, or that never saw the post-upgrade epochs, answer with the rolled-back promise. CE states 43 (JNRestart(j0)) and 44 (Rollback) write disjoint variables, so the reproduced order 44 then 43 reaches the counterexample's state 44. All bug runs used the pristine sources of base commit 734dd8a67cd; the fix control adds refreshCachedData() at the end of Journal.doRollback and removes the target throw.

## Evidence

- TLC: `tlc/RERUN.md` (config `MC_hunt_rollback_cache.cfg`, expect `Invariant TargetSafe is violated`); rerun 2026-11-07: Invariant TargetSafe is violated.
- Reproduction in the real system: `repro/` (tests and scripts run on the unmodified base) and `confirmation/` (Specula's verdict, investigation, issue).

## Cost

| | time | tokens | cost |
| --- | ---: | ---: | ---: |
| whole Specula run of `hdfs-adhoc-08` (all phases) | 5h53m | 253.0M | $148.60 |
| of which: confirming this finding | | 21.3M | $11.49 |

Time is active time; quota sleeps are excluded.
