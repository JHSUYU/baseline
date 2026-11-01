# HDFS: classification of reproduced findings (B6 step 4)

Classes: real new bug / by design / already known (cite) / variant of a known one. Checked against upstream trunk
(`origin/trunk` f8422975702, fetched 2026-10-26; no commit touches the cited files since 734dd8a67cd unless noted),
JIRA and merged PRs. Nothing is filed without the owner.

## hdfs-adhoc-10 (run 20261028-194745-c40a; target REACHED_CONFIRMED by MC-1)

All five share one root: `IPCLoggerChannel.startLogSegment` leaves `outOfSync` false when the start fails, so the
segment's first `journal()` reaches a JN whose `lastWriterEpoch` was never advanced, and `checkWriteRequest` throws at
L518. The JN is then out of sync until the next roll (HDFS-3726's designed handling); the quorum write succeeds.

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | one `startLogSegment` RPC lost at one JN | KNOWN (HDFS-17563) | already known | HDFS-3726's designed behavior; the symptom is reported as HDFS-17563 (open). |
| MC-2 | JN down/restarting across the epoch's first start | KNOWN (HDFS-17563) | already known | same symptom and handling as MC-1, with a restart as the trigger |
| MC-3 | writer crash leaves a header-only `edits_inprogress`; the next writer's `newEpoch` to that JN is lost; its start throws `IllegalStateException` at L600 | NEW | real new bug | `startLogSegment` (L588-603) rejects a 0-txn in-progress file that the newEpoch scan, the constructor and `getSegmentInfo` all treat as removable. L570-615 unchanged on trunk; no JIRA, PR or commit found (the run's post-verdict search of JIRA, GitHub PRs, the web and git history: `confirmation/MC-3/investigation.md`) |
| MC-4 | start times out at the client but still runs late on the JN, after the first `journal()` | NEW | by design | IPC gives no cross-call ordering after a client timeout; the JN is fenced out of the segment as designed |
| MC-5 | disk error while persisting `lastWriterEpoch` (L611) | NEW | variant of a known one (HDFS-17563) | a different trigger (JN disk fault, in the fault model) of the same failed-start → stale `lastWriterEpoch` → L518 path; handled as designed (JN out of sync until next roll) |

Bug runs (B6 step 5): the target bug MC-1 plus MC-2, MC-3, MC-5 (not the target). MC-4 is by design. TLC files of all
five are kept in `bugs/hdfs-adhoc-10/` (each rerun reports `TargetSafe` violated).

## hdfs-adhoc-08 (run 20261028-194804-49b4; target REACHED_CONFIRMED by MC-1)

Target: `Journal.checkRequest` L487, `reqInfo.getEpoch() < lastPromisedEpoch.get()` (the frame prints L489, the end of the throw statement).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | two failed epoch attempts (writer stop or lost `newEpoch`) leave an orphan promise on a minority JN; a late `getJournalState` reply lets the next writer pick an epoch below it | NEW | real new bug | the fence itself is correct, but epoch selection reads only a quorum's promises, so the newest legitimately established writer is rejected by that JN for its whole term (across JN restarts and log rolls): no spare JN, and one more JN failure stops the NameNode. No JIRA/PR found (run's post-verdict search); qjournal code unchanged on trunk except HADOOP-19951 (unrelated) |
| MC-2 | `hdfs namenode -rollback` with the JNs left running | NEW | real new bug | `Journal.doRollback` (L1189-1196) refreshes storage properties but not the cached `lastPromisedEpoch`, so a JN that stayed up keeps its pre-rollback promise and fences the next writer for its tenure (56/60 natural-timing attempts); unchanged on trunk; no JIRA/PR found |
| CR-6 | power loss before the promise rename is directory-synced | — | not reproduced (ENV_LIMITED) | argued from fsync semantics; not counted as a bug |
| CR-2, CR-4, CR-5, CR-7, CR-8 | — | — | false positive | see `bug-severity.md` |

Bug runs: MC-1 (target) and MC-2. TLC files kept in `bugs/hdfs-adhoc-08/` (reruns report `TargetSafe` violated).

## hdfs-adhoc-06 (run 20261028-202514-bbdd; target NOT_REACHED_BOUNDED)

Target: the assert `data.length == bufToSend.getLength()` at `QuorumOutputStream.java:108`. No hunt config violated `TargetSafe`: 3 exhaustive BFS hunts (up to 44.2M states, diameter 78-82) and 3 simulation runs stopped at their cap (295-381M states).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| CR-3 (not the target) | a non-HA BackupNode whose `dfs.namenode.edits.dir` lists a `qjournal://` URI; ordinary edits and log rolls, no faults | NEW | real new bug (niche configuration) | `EditsDoubleBuffer.writeRaw` (EDB:64-66), reached from `QuorumOutputStream.writeRaw`, never sets the batch's `firstTxId`/`numTxns`, which `flushAndSync` relies on: AssertionError at EDB:123 with -ea; with -da the JNs drop the records and QOS:118 throws, so the QJM journal is disabled every segment (or the BackupNode exits if it is its only edits dir). Reproduced on the unmodified base under -ea and -da. EditsDoubleBuffer and QuorumOutputStream unchanged on trunk; no JIRA/PR found |
| CR-4 | — | — | masked | `close()` drops an unflushed ready buffer, but FSEditLog syncs before close |
| CR-1, CR-2, CR-5..CR-8 | — | — | false positive | see `bug-severity.md` |

Bug run (not the target): CR-3. Its confirmation files are kept in `bugs/hdfs-adhoc-06/CR-3/` (a code-review finding, so no TLC counterexample of its own; the run's `spec/` is kept with it).

## hdfs-adhoc-07 (run 20261028-202514-8167; target REACHED_CONFIRMED by MC-1)

Target: `Journal.acceptRecovery` L926 `throw new AssertionError("Cannot replace segment ...")` (an explicit throw, so it fires with assertions off too; frame line 932).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | a JN acks the last batch and restarts; a checkpoint purge reaches it after the restart; failover while the JN holding the committed txn is slow | NEW | real new bug (critical: an acknowledged edit is lost) | `FileJournalManager.purgeLogsOlderThan` (L199-213) marks stale every in-progress segment at or after `minTxIdToKeep` except `currentInProgress`, which is null after a JN restart until the next `startLogSegment`, so the writer's open segment becomes `.stale`. Recovery then finalizes the shorter segment on a majority; with assertions off (as daemons run) txn 2, already acknowledged to the writer, is permanently lost. Code unchanged on trunk; no JIRA/PR found by the run's post-verdict search. Worth an owner review before filing |
| MC-4 | fault-free failover with one slow JN | NEW | real new bug | `IPCLoggerChannel` binds each request's `committedTxId` when the executor task runs, so a queued `acceptRecovery` for segment S carries the next segment's committed txid and trips the L926 check; the JN abandons recovery of S and keeps an overlapping, never-committed in-progress copy that fails `finalizeLogSegment` and in-progress manifests (reduced redundancy). Unchanged on trunk; no JIRA/PR found |
| CR-2, CR-3 | — | — | false positive | see `bug-severity.md` |

Bug runs: MC-1 (target) and MC-4. TLC files kept in `bugs/hdfs-adhoc-07/`.

## hdfs-adhoc-21 (run 20261029-025123-aa11; target NOT_REACHED_BOUNDED)

Target: `BPServiceActor.checkNNVersion`, `VersionUtil.compareVersions(nnVersion, minimumNameNodeVersion) < 0`. Two exhaustive hunts (5.5M and 3.3M states) found no violation. 5 code-review findings, all false positives. No bugs.

## hdfs-adhoc-19 (run 20261029-025123-a69f; target NOT_REACHED_BOUNDED)

Target: the DNA_FINALIZE `assert getBlockPoolId().equals(bp)` in `BPOfferService.processCommandFromActive`. 7 exhaustive hunts (up to 12.6M states) and one wide config (225M states BFS, 605M simulation, stopped at the 30-min cap) found no violation. 3 code-review findings, all false positives. No bugs.

## hdfs-adhoc-22 (target NOT_REACHED_BOUNDED)

Target: `BlockPoolSliceStorage.doTransition` L393, `getNamespaceID() != nsInfo.getNamespaceID()`. 8 hunt configs, all exhaustive with no violation (up to 23.2M states). 3 code-review findings, all false positives. No bugs.

## hdfs-adhoc-09 (target REACHED_CONFIRMED by MC-1)

Target: `Journal.checkRequest` L504, `Preconditions.checkArgument(reqInfo.getCommittedTxId() >= committedTxnId.get())`. Code checked on trunk: `JournalSet`, `FSEditLog`, `Journal`, `FileJournalManager` unchanged; HDFS-17924 changes `FSNamesystem`/`EditLogTailer` but not the failover read path.

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | HA failover with `dfs.ha.tail-edits.in-progress=true`; the standby applied txid a mid-segment; during transitionToActive the catch-up read and openForWrite's read of the QJM both fail at quorum level | NEW | real new bug (critical) | `JournalSet.selectInputStreams` (L276-282) logs and skips an IOException even from the required shared QJM, so catch-up and `openForWrite`'s safety check see no streams; the new active opens a segment at a+1 inside a finalized segment, every JN rejects its next RPC at L504, the write quorum fails and the new active terminates |
| MC-3 | `-rollingUpgrade rollback` recovery while one JN is partitioned; a late RPC of the pre-rollback NN reaches it after `discardSegments` | NEW | real new bug | `Journal.discardSegments` (L1198-1202) takes no RequestInfo/epoch and resets `committedTxnId` unconditionally; a JN that missed the rollback NN's newEpoch is not fenced, so stale-epoch RPCs re-raise or trip the check |
| CR-3 | after `doRollback`, a delayed finalize of the post-upgrade writer reaches one JN | NEW | real new bug | `doRollback` rewinds `committedTxnId` but nothing fences writers of the rolled-back history (rollback RPCs carry no epoch); the late RPC re-raises `committedTxnId`, and the post-rollback writer is rejected at L504 on that JN, even across restarts. A different defect from 08/MC-2 (stale cached promise), same rollback area |
| CR-5 | two JNs restart inside an open segment; a purge then hides their copies; failover | NEW | same defect as 07/MC-1 | `purgeLogsOlderThan` marks a restarted JN's live in-progress segment `.stale` (HDFS-8178 logic, `currentInProgress` null after restart); here the symptom is L504 and lost quorum-acked edits. Counted once, under 07/MC-1 |
| MC-2 | power loss after rolling-rollback `discardSegments` | — | not reproduced (ENV_LIMITED) | not counted |
| CR-4 | — | — | false positive | |

Bug runs: MC-1 (target), MC-3, CR-3, CR-5 (= 07/MC-1). Files kept in `bugs/hdfs-adhoc-09/`.

## hdfs-adhoc-11 (target REACHED_CONFIRMED by MC-1)

Target: `BlockTokenSecretManager.retrieveDataEncryptionKey` L559, `key == null` (frame :561): a DataNode cannot resolve the block key a DEK names. Classified from the run's evidence (reproductions on the unmodified base, post-verdict JIRA/PR/history searches in each `investigation.md`) and the cited code; owner review recommended before filing, as this check produced many related findings.

| finding | mechanism | Specula novelty | class |
| --- | --- | --- | --- |
| MC-1 (target) | `DatanodeManager.handleHeartbeat` returns no commands while the NN is in safe mode (L1884-1886), before the KeyUpdateCommand is added, while `HeartbeatManager.Monitor` keeps rolling keys and DEKs are issued from the new keys | NEW | real new bug |
| MC-5 | the same suppression on a standby/observer in safe mode; observer-read clients fail with BlockMissingException while the observer stays in safe mode | NEW | same defect as MC-1 (counted once) |
| MC-3 | `registerDatanode` exports keys (L1209) before the node joins the heartbeat set (L1300/L1332), so a concurrent roll sweep misses it and the next roll's DEKs fail | NEW | real new bug |
| MC-4 | after an NN restart and a DN restart a long-lived client's cached DEK is rejected; reads recover by refetch, but snapshot-path and explicit-length `getFileChecksum` silently return a wrong checksum (MD5 over zero CRCs), e.g. to DistCp | NEW | real new bug (wrong result) |
| MC-6 | a restarted NN issues DEKs from its new random key range before DNs re-register; the client refetches the same key, dead-lists healthy DNs, reads stall 6-20 s or fail | NEW | real new bug (transient unavailability; the pull model proposed in HDFS-13473 would avoid it) |
| CR-4 | encrypted SASL before a block pool's keys are installed fails with NPE/IAE instead of ERROR_UNKNOWN_KEY, so the client skips its refetch-and-retry and excludes the DN (a single-DN write fails) | NEW | real new bug |
| MC-2 | a lost heartbeat reply drops the key push until the next roll | KNOWN | already known (HDFS-13441, unfixed) |
| MC-7 | DN-to-DN transfer from a DN not yet re-registered after an NN restart | KNOWN | already known (HDFS-16136, unfixed) |
| CR-3 | a dead CommandProcessingThread never applies a delivered KeyUpdateCommand | KNOWN | already known (HDFS-15651, HDFS-13473, unfixed) |
| CR-6, CR-7 | clock skew past the key interval; LIFO key-update enqueue | — | masked |

Bug run: MC-1 (target) and MC-2..MC-7, CR-3, CR-4 (not the target). Files kept in `bugs/hdfs-adhoc-11/`.

## hdfs-adhoc-14 (target REACHED_CONFIRMED by MC-1)

Target: `BlockTokenSecretManager.checkAccess` L418, token password mismatch. All four reproduced findings are one defect: with `dfs.encrypt.data.overwrite.downstream.derived.qop=true` (non-default), `DataXceiver.writeBlock` (L823-832) passes the DataNode's own current block key to `SaslDataTransferClient.updateToken` (L450-460), which re-signs the forwarded block token with it but keeps the identifier's keyId; the next DataNode recomputes the password with the keyId's key and rejects an authorized write (ERROR_ACCESS_TOKEN), the client excludes a healthy DataNode or a replication stays a replica short. Manifestations: after a key rotation (MC-1), DN-signed replication tokens (MC-2), after HA failover (MC-3), after an NN restart (MC-4). Specula novelty NEW for all. Class: one real new bug (non-default configuration).

## hdfs-adhoc-15, -16, -23 (targets NOT_REACHED_BOUNDED)

No hunt config violated `TargetSafe`; no finding reproduced. No bugs.

## hdfs-adhoc-20 (target REACHED_CONFIRMED by MC-1)

Target: `BPOfferService.updateActorStatesFromHeartbeat` L615, `assert txid >= lastActiveClaimTxId`.

| finding | mechanism | class |
| --- | --- | --- |
| MC-1 (target), MC-2, CR-2 | NameNode heartbeats advertise the last *assigned* txid (`getCorrectLastAppliedOrWrittenTxId`; async edit logging assigns at enqueue), not the durable one; after a crash the restarted (non-HA, or re-activated HA) NN advertises a lower txid. With -ea the assert kills the BPServiceActor (the DN never re-registers; 0 live DNs). In production (-da, CR-2) every DN takes the split-brain branch and routes the legitimate active's commands to `processCommandFromStandby`, dropping DNA_TRANSFER/INVALIDATE/RECOVERBLOCK until its txid exceeds the lost one (reproduced: setReplication not honored for 39 s) | one real new bug |
| MC-3 | `verifyAndSetNamespaceInfo` installs `bpServiceToActive` from a versionRequest that reports ACTIVE without comparing against `lastActiveClaimTxId`, so a deposed NN can be installed; its next heartbeat trips the assert (-ea) | real new bug (lower severity: a gap in the txid split-brain fence) |

Files kept in `bugs/hdfs-adhoc-14/` and `bugs/hdfs-adhoc-20/`.
