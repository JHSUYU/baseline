# HDFS: verified bugs (high quality, severe, make the ad hoc check fail)

The owner's bar (2026-11-02) is a bug that:
- (1) makes the target ad hoc check fail in the real system (the target exception at the target line);
- (2) is real: a realistic trigger, not designed behaviour, not already reported;
- (3) is severe: data loss, a wrong result, a crashed or wedged component, or lasting loss of availability or redundancy.

How each was verified:
- Every candidate was first reviewed against the source by an independent verifier (`VERIFY-qjm.md`, `VERIFY-keys-dn.md`, `VERIFY-storage.md`).
- The operator then read the decisive code for each bug kept here. The file:line citations are at apache/hadoop `734dd8a67cd`; none of the cited code changed on `origin/trunk` (2026-10-26).
- The reproductions are Specula's, on the unmodified base; their TLC counterexamples were rerun on the pinned TLC.

## Tier A: severe, default configuration

| # | case/finding | defect (root cause) | consequence | trigger |
| ---: | --- | --- | --- | --- |
| 1 | hdfs-adhoc-07/MC-1 | `FileJournalManager.purgeLogsOlderThan`/`isStaleInProgressLog` (L199-224) mark `.stale` every in-progress segment at or after `minTxIdToKeep` except `currentInProgress`. That field is in memory only, set by `startLogSegment` (L124), and so null after a JournalNode restart | a restarted JN's copy of the writer's open segment, including edits it acknowledged, is hidden by the next checkpoint purge. A later failover finalizes a shorter segment; **an acknowledged edit is lost** (the target `AssertionError` at `Journal.acceptRecovery`:926, an explicit throw) | one JN restart inside a segment, a checkpoint purge, and a failover while the JN holding the edit is slow; QJM tolerates this |
| 2 | hdfs-adhoc-11/MC-4 | `FileChecksumHelper.checksumBlock` subtracts the block from `remaining` before contacting a DataNode (L508-511). The retry paths for `InvalidBlockTokenException`/`InvalidEncryptionKeyException` (L520-546) redo the block (`blockIdx--`) without restoring `remaining` | `getFileChecksum` with an explicit length, or on a `/.snapshot/` path (`remaining` bounded, L119-123), **silently returns a wrong checksum** (MD5 over zero CRCs), e.g. to DistCp | any one-time DEK or block-token rejection during the checksum; reproduced with only an NN restart and a DN restart (target `InvalidEncryptionKeyException` at BTSM:559) |
| 3 | hdfs-adhoc-38/MC-1 (=MC-2) | `INodeFile.getStoragePolicyID` inherits the parent's policy (L592-597). LAZY_PERSIST is meant to apply only at creation: it cannot be set on an existing file (`FSDirAttrOp` L446-459), and `MemoryStorage.md` says a directory's policy applies to "new files". Yet append (`FSDirAppendOp`:122) and the lazy-persist scrubber (`FSNamesystem` ~L4700-4712) use the inherited policy | existing DISK files under a directory later tagged LAZY_PERSIST (or renamed into one) cannot be appended to (the target), and **the scrubber deletes such a file when its replicas are briefly all unavailable: data loss** | any user with write access sets LAZY_PERSIST on a parent directory or renames a file into one; default configuration |
| 4 | hdfs-adhoc-24/MC-2 | `BlockPoolSliceStorage.format` (L283-292) stamps a new disk with the upgraded NameNode cTime and creates no `previous/`; `-rollback` skips a directory without `previous/` (L375-385) | after an unfinalized upgrade, a disk added or replaced in the meantime makes `doTransition` throw at the target (L421) on every `-rollback` start: **the documented rollback cannot complete on that DataNode** | replacing or adding a disk during an upgrade window, then rolling back; default configuration |
| 5 | hdfs-adhoc-08/MC-1 | `QuorumJournalManager.createNewUniqueEpoch` takes `maxPromised` from a write quorum of `getJournalState` replies only and never re-proposes | a JN outside that quorum that holds a higher orphan promise (left by failed epoch attempts) rejects every request of the new writer for its whole term, at the target (`Journal.checkRequest`:487-489): **no JN fault tolerance until the next failover**; one more JN failure stops the NameNode (reproduced) | two failed or interrupted epoch attempts during failovers, then a late `getJournalState` reply |

## Tier B: real, but narrower trigger or lower severity

| # | case/finding | defect | why tier B |
| ---: | --- | --- | --- |
| 6 | hdfs-adhoc-08/MC-2 | `Journal.doRollback` (L1189-1196) refreshes the storage properties but not the cached epochs (`refreshCachedData`, L202-212); a JN left running through `namenode -rollback` fences the next writer | needs the rollback procedure with the JNs left up; it clears when that JN restarts |
| 7 | hdfs-adhoc-24/CR-6 (=CR-2) | a block-pool directory that fails to load is only logged (`DataStorage` L473-476), but `finalizeUpgrade` (L1019-1029) still finalizes it; a volume that missed the `-rollback` start fails the target (L421) and then loses its `previous/` for good | needs `dfs.datanode.failed.volumes.tolerated` ≥ 1 (common, not the default) |
| 8 | hdfs-adhoc-24/MC-3 | `clearRollingUpgradeMarkers` (BPSS L889-909) trusts a stale rolling-upgrade marker plus a replayed finalized rolling-upgrade status, and `doFinalize` deletes a regular upgrade's `previous/`; the rollback then fails at L421 | needs `-upgrade` before the next checkpoint after a DN missed a rolling-upgrade finalize (medium confidence) |
| 9 | hdfs-adhoc-11/MC-1 | `DatanodeManager.handleHeartbeat` returns early in safe mode (L1884-1886), before the key update (L1971), while keys keep rolling and DEKs are issued | encrypted reads fail only after about 10 h in one safe-mode period at the default key interval |
| 10 | hdfs-adhoc-14/MC-1 | with `dfs.encrypt.data.overwrite.downstream.derived.qop=true`, `DataXceiver.writeBlock` (L823-832) re-signs the forwarded token with the DN's own key and keeps the keyId (`SaslDataTransferClient.updateToken` L450-460) | non-default flag; rejections in 1-3 s windows after each key rotation or failover |
| 11 | hdfs-adhoc-26/MC-1 | a DataNode's block-pool `doUpgrade` upgrades whenever its cTime is below the NameNode's (BPSS L414-417) and **unconditionally deletes an existing `previous/`** (L477-480), which the NameNode refuses for itself (`FSImage.checkUpgrade` L424-431); a DN that was down during `namenode -rollback` is silently re-upgraded after the next upgrade, losing its pre-upgrade snapshot, so rolling back that upgrade throws at the target (L621) on every volume | needs a DN down during one rollback and a second upgrade that is rolled back too (medium confidence); no data loss with replication ≥ 2 |

## Dropped (not new, not real, or not severe)

- **09/MC-1 (`JournalSet` swallows a QJM read error):** already known. HDFS-5058, "QJM should validate startLogSegment() more strictly", is the same defect and was closed **Won't Fix**.
- **10/MC-1, MC-2, MC-4, MC-5:** HDFS-3726's designed handling, or HDFS-17563.
- **10/MC-3, 07/MC-4:** low severity; self-healing at the next log roll.
- **09/MC-3, 09/CR-3:** unrealistic trigger.
- **24/MC-4 (=37/MC-1):** needs an NN clock set behind the last upgrade; the failure is loud and recoverable.
- **24/CR-7:** two independent faults, one inside a millisecond window.
- **25/MC-1:** PROVIDED storage only.
- **35/MC-1, MC-2:** variant of HDFS-14311; unrealistic pre-federation trigger.
- **11/MC-2 (HDFS-13441), 11/MC-7 (HDFS-16136):** known.
- **11/MC-3, MC-6:** transient.
- **26/MC-2:** duplicate of 24/CR-6. **26/MC-3:** duplicate of 24/MC-2. **26/MC-5:** the wall-clock cTime regression. **26/CR-8:** unrealistic trigger.
- **30/MC-1..MC-4:** routine HA failover (the new active rejects the old recovery id and re-runs it), by design (HDFS-15651 handling), or known (HDFS-4701, HDFS-4843); the NameNode's re-issue completes the recovery.
- **27:** NOT_REACHED_BOUNDED; its CR-5 does not hit the target check.
- **20/MC-1..MC-3:** the target is a Java `assert`. With `-da` the DN correctly lowers its txid; the production harm (20/CR-2) never reaches the target line.
- Every other finding is a duplicate, by design, known, or a false positive. See the VERIFY files and `CLASSIFICATION*.md`.

- **34/MC-1, MC-2:** needs a pre-federation disk in a hot add (as 35/MC-1). **39/MC-1:** HDFS-17757, non-default, transient. **52/MC-1, MC-3:** HDFS-17960. **52/MC-2:** HDFS-17399. **52/CR-2:** CheckpointNode only, not severe. Details: `../batches/VERIFY-batch1.md`.

- **33/MC-1..3:** the target is a Java `assert` (as 20/MC-1..3). **40/MC-4:** HDFS-15357, HDFS-7269. **40/CR-1:** HDFS-16987. **40/MC-1, 3, 6, 7, 8:** transient. **40/MC-2:** by design. **40/MC-5:** needs test hooks. **45/MC-4:** stacked non-default settings, empty namespace only (the closest call). **45/MC-3:** off-label `rollEdits`. **45/MC-1, 2, 5:** one failed call, or a node already stopping. **49/MC-1..3:** private flag plus 65536 snapshots. **49/MC-4, 5, 50/MC-4, 5:** HDFS-17399. **50/CR-1:** HDFS-17954. **50/MC-6:** unrealistic. **50/MC-1, 2, 3:** one wrong or failed call, namespace intact. Details: `../batches/VERIFY-batch2.md`.
- **48:** NOT_REACHED_BOUNDED; its CR-1, CR-2 are false positives.
