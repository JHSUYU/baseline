# HDFS: classification of reproduced findings, batch 2

Classes: real new bug / already known (cite) / variant of a known one (cite) / same defect as <case>/<finding> /
by design. Only findings whose `verdict.json` status is REPRODUCED are classified (FALSE POSITIVE, MASKED and NEEDS MORE
INFO are left out). Classified from each run's `issue.json`, `investigation.md` (post-verdict novelty searches),
`confirmed-bugs.md`, `bug-severity.md` and the cited code in the base tree 734dd8a67cd. Upstream check:
`git log 734dd8a67cd..origin/trunk` (origin/trunk f8422975702, fetched 2026-10-26) on every cited file. Commits since the
base that touch cited files, all unrelated unless noted: DataNode.java (HDFS-17978, HADOOP-19986, HADOOP-19951,
HDFS-17899 [relevant to 12/MC-5], revert b15adbcfa3b), BPServiceActor.java (HDFS-17953 IBR OOM, revert),
DataXceiver.java (HDFS-17967 DEK retry in writeBlock/replaceBlock; `checkAccess`/`checkAndWaitForBP` unchanged),
DatanodeManager.java (HDFS-18014 slow-peer lookup), BlockManager.java (HDFS-17931, revert), BlockPoolManager.java
(HADOOP-19986, adds `signalShutDownAll` for test shutdown), FsDatasetImpl.java (HDFS-17938 metric), FSImage.java and
Storage.java (revert only), NNStorage.java (HADOOP-19951), FSNamesystem.java (HDFS-17980, HADOOP-19951, HDFS-17924).
Unchanged: BlockTokenSecretManager, BPOfferService, HeartbeatManager, BlockPoolSliceStorage, DataStorage,
BlockRecoveryWorker, FSDirAppendOp, INodeFile, FSDirAttrOp. Nothing is filed without the owner.

## hdfs-adhoc-12 (run 20261029-002846-51f8; target REACHED_CONFIRMED by MC-1)

Target: `BlockTokenSecretManager.retrievePassword` L518, `key == null` (`allKeys.get(identifier.getKeyId())`; frame :520). The same block-key delivery area as hdfs-adhoc-11 (L559, DEK path); here the block-token path.

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | NN in safe mode across two key rotations (manual, resource-low or startup); a client reads, or a post-exit replication | NEW | same defect as 11/MC-1 | `DatanodeManager.handleHeartbeat` returns before `addKeyUpdateCommand` in safe mode (DM:1884-1886) while `HeartbeatManager.Monitor` keeps rotating. Here the symptom is InvalidToken on reads/replications instead of an unknown DEK. Counted once, under 11/MC-1 |
| MC-2 | one heartbeat reply carrying the KeyUpdateCommand lost after the NN cleared `needKeyUpdate` | KNOWN (HDFS-13441) | same defect as 11/MC-2 (already known, HDFS-13441, unfixed) | no ack/resend of the push (BM:1674-1676) |
| MC-4 | three consecutive lost KUC replies; the source signs with a key verifiers expired | KNOWN (HDFS-13441, HDFS-13473) | same defect as 11/MC-2 (already known, HDFS-13441) | the same lost-push mechanism repeated; the longer outage (up to one key interval) follows from it |
| MC-3 | a key rotation lands between `registerDatanode`'s key export (DM:1209) and the heartbeat-list insert (DM:1300/1337); sub-case (b): between `addKeyUpdateCommand`'s export and flag clear (BM:1675-1676) | NEW | same defect as 11/MC-3 | the Monitor's rotate-and-mark is not atomic with the export paths. Sub-case (a) is 11/MC-3 exactly; sub-case (b) is a second, microsecond window of the same unsynchronized rotate-and-mark (held with a Mockito spy). Counted once |
| MC-5 | NN restart; a pre-restart replication's slow connect outlasts the source's re-registration; the source mints with the new key space, the target has not re-registered | NEW | same defect as 11/MC-6 | the restarted NN's fresh random key space is unknown to DNs until each re-registers (11/MC-6: NN-issued DEKs; here a DN-minted token). The late-mint window itself is gone on trunk: HDFS-17899 (62729b06d70) moves the connect after the token is minted. The consequence self-heals (the new NN reschedules within seconds) |
| MC-6 | restarted DN publishes `bpRegistration` (BPOS:432) before installing its keys (BPOS:439); a replication token arrives in between | NEW | by design (benign race) | microsecond window (0 natural hits in 20 restarts; the test held the thread). A DN-to-DN replication rejected there is re-driven by the NN's pending-reconstruction timeout and client reads refetch the token, both designed retries. The harmful form of this window (NPE/IAE under encryption, which defeats the client retry) is 11/CR-4 |
| CR-1 | DN command thread busy across several key rotations while heartbeats continue; queued KUCs (pushed with `putFirst`, HDFS-17372) run newest-first, so the oldest `currentKey` wins | NEW | real new bug (low) | the same mechanism as 11/CR-7, which was MASKED there; reproduced here: with 4 queued KUCs the DN signs with a pruned key and its replications are rejected for up to one key interval. Ordering bug introduced by HDFS-17372 (in the base); BPServiceActor KUC code unchanged on trunk (HDFS-17953 does not touch it); no JIRA/PR found by the run's post-verdict search. Needs a single command stalling the thread about 3 key intervals (~30 h at defaults); 2 queued KUCs are absorbed |
| CR-4 | HA with no active NN for longer than keyUpdateInterval + tokenLifetime (~20 h at defaults); right after failover a pipeline-recovery transfer is signed by a DN before its first heartbeat to the new active | NEW | real new bug (low) | standby KUCs are applied with `updateCurrentKey=false` (HDFS-17383) and `addKeys` purges expired keys but keeps `currentKey`, so every DN signs with a key no verifier holds; client hflush/close failed 3/3. Unchanged on trunk; no JIRA/PR found (post-verdict search). Precondition is a long no-active-NN period; the window closes at the first heartbeat after failover (~0.8 s) |

Bug runs: MC-1 (target, = 11/MC-1), MC-2 and MC-4 (= 11/MC-2, HDFS-13441), MC-3 (= 11/MC-3), MC-5 (= 11/MC-6), CR-1, CR-4. MC-6 is by design.

## hdfs-adhoc-24 (run 20261029-090048-2c84; target REACHED_CONFIRMED by MC-1)

Target: `BlockPoolSliceStorage.doTransition` L421, "Datanode state ... is newer than the namespace state" (neither the regular-start nor the upgrade return is taken; frame :424).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | one `dfsadmin -reconfig` hot-adds two disks of a block pool (one stale); loaders tear the shared `layoutVersion`/`cTime` | NEW (closest HDFS-14311) | variant of a known one (HDFS-14311; also HDFS-12800, open) | `DataNode.refreshVolumes` runs unsynchronized `DataStorage.prepareVolume` per disk on the one shared `BlockPoolSliceStorage`; HDFS-14311 is the same race on the startup path, and its fix touched only `loadBlockPoolSliceStorage`. The hot-swap path is unfixed (BPSS/DataStorage unchanged on trunk). Here a not-newer disk is refused (FAILED TO ADD) |
| CR-8 | same race, other order: an older-layout disk takes the regular return; VERSION rewritten to -57 without re-laying blocks | NEW | same defect as 24/MC-1 | same unsynchronized hot-swap load; the consequence is worse (replicas mapped to the wrong path, unreadable after every restart). Close to HDFS-12800's un-upgraded-disk outcome |
| CR-9 | same race persists another loader's cTime into a volume's VERSION; the next restart re-upgrades and replaces the real `previous/` | NEW | same defect as 24/MC-1 | same root; the consequence is silent data loss at a later documented rollback (1 natural hit in 1594 loads) |
| CR-4 | block-pool load failure during hot swap (e.g. the L421 refusal above) leaves the DN-level `in_use.lock` held; the repaired disk cannot be re-added | NEW (closest HDFS-7830) | variant of a known one (HDFS-7830) | HDFS-7830 ("DataNode does not release the volume lock when adding a volume fails", fixed 2.7) added `sd.unlock()` only for failures after the StorageDirectory is built; `DataStorage.prepareVolume`'s block-pool phase has no try/finally. Same symptom, uncovered step. Recovers on GC or DN restart |
| MC-2 | a disk added or replaced during an unfinalized `-upgrade` is formatted with the upgraded cTime and no `previous/`; then the documented rollback | NEW | real new bug (high) | `BlockPoolSliceStorage.format` (L283-292) stamps `nsInfo.getCTime()` with no snapshot, so the slice fails L421 on every later start and only manual deletion or a re-upgrade recovers it; when it loads last, the DN's registration carries the upgraded cTime and the NN rejects the whole DN (see CR-3's live-object registration). Unchanged on trunk; no JIRA/PR found (post-verdict search) |
| CR-2 | startup L421 failure on one volume (e.g. MC-2's disk at rollback) | NEW | real new bug (critical: wrong data) | `DataStorage.loadBlockPoolSliceStorage` only logs the IOException (L473-476); the volume stays a FsDataset volume and keeps serving its post-upgrade replicas. After rollback the NN reuses block IDs/GS and later adopts the stale replica: clients read another file's bytes with no checksum error. Unchanged on trunk; no JIRA/PR found |
| CR-6 | one volume misses the DN `-rollback` start (offline within `failed.volumes.tolerated`, or a crash after L637), then a default restart or hot swap | NEW | same defect as 24/CR-2 | a different trigger of the non-fatal L421 handling: the stale slice is served and the rolled-back NN's FinalizeCommand deletes its `previous/` (permanent loss), or, loaded last, its cTime leaks into the registration (CR-3's mechanism). The hot-swap refusal alone is the guard working |
| CR-3 | NN asks for re-registration while a hot-swapped old-cTime disk is being upgraded inline | NEW | real new bug | `DataNode.createBPRegistration` uses the live shared BPSS as the registration StorageInfo, which the loader mutates in place (L388 to L512); the accepted registration carries the transient cTime, every later heartbeat fails `verifyRequest` and the actor exits for good (DN silently drops out until restart/refresh). Unchanged on trunk; no JIRA/PR found |
| MC-3 | non-HA: RU prepare; DN down while the RU is finalized; NN restarted with `-upgrade` before a checkpoint; DN restart | NEW | real new bug (critical) | the replayed finalized RU status reaches the DN in heartbeats and `clearRollingUpgradeMarkers` calls `doFinalize` for every marked volume, deleting the regular upgrade's `previous/`; the documented rollback then fails at L421 and the snapshot is gone. Only documented operator commands and a DN outage. Unchanged on trunk; no JIRA/PR found (HDFS-6981/HDFS-7645 discussions do not cover a DN that missed the finalize) |
| MC-4 | NN wall clock below the previous cTime when `namenode -upgrade` runs (clock behind, or ahead at the earlier stamp and since corrected) | NEW | real new bug (high impact, rare trigger) | `FSImage.doUpgrade` sets `cTime = now()` (FSImage:465) with no monotonic check while DNs order states only by cTime; every slice of every DN fails L421, 0 live DNs, only `namenode -rollback` recovers. Clock behavior is in the fault model. FSImage changed on trunk only by the revert b15adbcfa3b; no JIRA/PR found |
| CR-7 | NN crash inside `FSImage.doUpgrade`'s per-directory VERSION loop; later loss of the upgraded name directory | NEW | real new bug (two in-model faults) | restart recovery rolls back only the unfinished dirs and NNStorage accepts mixed cTimes; after finalize, losing the upgraded dir makes the NN report the old cTime and every DN slice fails L421 with no `previous/` left anywhere. No JIRA/PR found (HDFS-2017/HDFS-5840 cover other partial-upgrade sites) |
| CR-5 | `dfs.datanode.data.dir` lists a PROVIDED location before a DISK one (non-default PROVIDED storage); layout-changing RU finalized, then a later RU rolled back | NEW | real new bug (PROVIDED, non-default) | `setRollingUpgradeMarkers` returns at the first dir with a null current dir (BPSS:866-868) where `clearRollingUpgradeMarkers` continues (BPSS:892-894), so no marker is written on later DISK volumes, RU finalize never finalizes them and the next RU rollback deletes every replica written in between. Verified in the base; unchanged on trunk |

Bug runs: MC-1 (target; HDFS-14311 variant, with CR-8 and CR-9), CR-4 (HDFS-7830 variant), MC-2, MC-3, MC-4, CR-2 (with CR-6), CR-3, CR-5, CR-7. No by-design findings.

## hdfs-adhoc-25 (run 20261029-103521-29b0; target REACHED_CONFIRMED by MC-1)

Target: `BlockPoolSliceStorage.loadStorageDirectory` L185, `!doTransition(...) && getCTime() != nsInfo.getCTime()` ("Datanode CTime ... is not equal to namenode CTime").

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | PROVIDED location listed after a DISK location (non-default PROVIDED storage); first DN start after NN `-upgrade` | NEW | real new bug (PROVIDED, non-default; low on its own) | `doTransition` returns false for PROVIDED without reading any VERSION (BPSS:372-373), so L184 compares the cTime another directory's load left in the shared BPSS (the DISK dir's old cTime, reset only after the loop at L512). Here only a false "failed storage directory" and a bookkeeping gap for the DN's lifetime; the volume keeps serving. Unchanged on trunk; no JIRA/PR found |
| MC-3 | hot-add of a PROVIDED volume after a refused DISK hot-add (e.g. after NN rollback) or together with a stale DISK volume | NEW | same defect as 25/MC-1 | the same PROVIDED-vs-leftover-cTime check; the PROVIDED volume is refused and every retry fails until another DISK load or a DN restart |
| CR-3 | after a failed block-pool init (DISK slice newer, PROVIDED rejected), the pool is re-initialized in the same process (HA peer retry or `refreshNamenodes`) | NEW | same defect as 25/MC-1 | the failed init's BPSS stays in `bpStorageMap` and is reused, and the PROVIDED check again reads its leftover cTime; the block pool never comes up until restart. The reuse of a failed init's storage object is an aggravating detail of the same PROVIDED check |
| MC-2 | one reconfiguration hot-adds a stale volume and a fresh volume; the fresh one fails L185 | NEW | same defect as 24/MC-1 (HDFS-14311 variant) | the unsynchronized parallel hot-swap load on the shared BPSS cTime; the immediate-retry failure is the 24/CR-4 lock leak |
| CR-4 | one reconfiguration adds good volumes with volumes of different cTime; another volume's cTime is persisted into a good volume's VERSION | NEW | same defect as 24/MC-1 (HDFS-14311 variant) | the same race as 24/CR-9 (VERSION writes serialize the shared fields), reproduced without timing help |
| CR-2 | PROVIDED location precedes a DISK block-pool dir (PROVIDED listed first, or a disk hot-added later); that disk is removed by hot swap or fails a disk check | NEW | real new bug (PROVIDED, non-default) | `BlockPoolSliceStorage.remove` (L305) dereferences `sd.getRoot()`, null for PROVIDED; the NPE escapes `DataNode.removeVolumes` (catches only IOException): the disk stays half-removed with its lock held, the reconfiguration task is "still running" forever, and disk-failure handling (NN report, VolumeFailures, tolerated-failures shutdown) is skipped. Verified in the base; unchanged on trunk |

Bug runs: MC-1 (target, with MC-3 and CR-3), CR-2, MC-2 and CR-4 (= 24/MC-1). No by-design findings.

## hdfs-adhoc-28 (run 20261029-135708-05f7; target REACHED_CONFIRMED by MC-1)

Target: `BlockRecoveryWorker.getDatanodeID` L565, `bpos == null` (`datanode.getBPOfferService(bpid)`).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | the lease-recovery primary is stopped while its recovery daemon is still running | KNOWN (HDFS-4701) | already known (HDFS-4701, open since 2013, Minor) | the recovery daemon outlives its BPOS; HDFS-11890 turned the NPE into this IOException. Lease recovery completes after the NN's block-recovery timeout with another primary; no data loss |
| MC-2 | documented null to `ns1` `refreshNamenodes` (Federation.md); the old BPOS's `BlockPoolManager.remove` deletes the live new BPOS's `bpByBlockPoolId` entry by key (BPM:94) | KNOWN (HDFS-4843) | already known (HDFS-4843, closed as a duplicate of a test-only fix; product code never changed) | Step 3 starts the new BPOS before Step 4 stops the old one for the same pool; recovery on that DN then always fails |
| CR-6 | the same null to `ns1` refresh, no faults (7/7 runs): the new BPOS's storage load is refused while the old BPOS still holds the pool | NEW | variant of a known one (HDFS-4843) | the same start-new-before-stop-old overlap, a different outcome: with one NN `shouldRetryInit` is false, the new actor exits, the refresh reports success and the DN serves no BPOS for the pool (reads fail, NN declares it dead, `secureMain` terminates the process in production). The most likely outcome of the documented procedure, so worth adding to HDFS-4843 rather than filing as new |
| CR-3 | `refreshNamenodes` races the exit of a BPOS's last actor (NN disallows the DN); later re-allow, refresh, disallow | NEW | real new bug (low likelihood) | `refreshNNList` starts and publishes actors with no BPOS lock and no liveness check, so an actor can join a removed BPOS; its later exit tears down the re-created live BPOS's map entry and pool (by-key remove). The admin-visible NPE in step 5 (BPM:281) and the orphan actor were seen without hooks; the full chain needed controlled timing. BlockPoolManager/BPOfferService changed on trunk only by HADOOP-19986 (test shutdown helper); no JIRA/PR found |

Bug runs: MC-1 (target, HDFS-4701), MC-2 (HDFS-4843), CR-6 (HDFS-4843 variant), CR-3.

## hdfs-adhoc-29 (run 20261029-141612-728f; target REACHED_CONFIRMED by MC-1)

Target: `BlockRecoveryWorker.getActiveNamenodeForBP` L604, `bpos == null` (`datanode.getBPOfferService(bpid)`).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | volume failure (`failed.volumes.tolerated=0`) or shutdown of the recovery primary between its two pool lookups | NEW | same defect as 28/MC-1 (HDFS-4701) | the same race of a recovery daemon against pool removal, at the second lookup (BRW:602) instead of BRW:131; recovery completes after the NN's timeout, no data loss |
| MC-2 | operator drops the primary from the include list (`refreshNodes`), or its command thread dies, mid-recovery | NEW | same defect as 28/MC-1 (HDFS-4701) | same race, another way for the pool's last actor to exit; bounded stall |
| MC-3 | `refreshNamenodes` drops a federated nameservice during that pool's lease recovery | NEW | same defect as 28/MC-1 (HDFS-4701) | same race, triggered by a refresh; bounded stall |
| CR-2 | `refreshNamenodes` renames the nameservice of the same NN on the recovery primary during lease recovery (6/14 without hooks) | NEW (closest HDFS-17984) | variant of a known one (HDFS-17984, open; its PR #8778 does not cover this path) | the pool is unmapped and its replica map cleared mid-recovery, so `initReplicaRecovery` returns null and `recover()` counts it as "no replica"; the pool is re-mapped before BRW:602, the guard passes and `syncBlock` sends the empty-syncList `deleteBlock=true` commit: the NN closes the file at length 0 and hsync'ed data is lost. HDFS-17984 reports the same null-means-absent deletion for a restarting peer; the run applied PR #8778 and still lost the data. Critical; worth reporting on HDFS-17984 as an uncovered path |
| CR-4 | same-NN nameservice rename through `refreshNamenodes` (3/13 without hooks) | KNOWN (HDFS-4843) | same defect as 28/CR-6 (HDFS-4843 variant) | the start-new-before-stop-old overlap (storage load refused, by-key remove, `initBlockPool` maps the pool before `initStorage` with no undo) leaves no live registered BPOS |

Bug runs: MC-1 (target), MC-2, MC-3 (= 28/MC-1, HDFS-4701), CR-2 (HDFS-17984 variant), CR-4 (= 28/CR-6).

## hdfs-adhoc-31 (run 20261029-182808-549b; target REACHED_CONFIRMED by MC-1)

Target: `DataNode.getBPOSForBlock` L1838, `bpos == null` (`blockPoolManager.get(block.getBlockPoolId())`). MC-4 (NEEDS MORE INFO) is the 28/MC-2 mechanism and is not classified.

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | the pool's last actor exits (NN include-list rejection, volume failure beyond tolerance, DN shutdown) during a multi-block DNA_TRANSFER | NEW | by design | the DataNode is leaving the pool; its remaining queued transfers are dropped and the NN's pending-reconstruction timeout is the designed re-drive. The 0-live-replica outcome comes from removing a DN from the include list without decommissioning (the documented way to remove a node is decommission). Same race family as HDFS-4701; the window needed a test-hook hold (0/12 natural) |
| MC-2 | a local bad-block report straddles the pool's unpublish after an include-list rejection | NEW | by design | the report is logged and dropped, but the BPOS has no actor left, so even a lookup that won the race would deliver it to no NN (BPOS:296-298); no effect attributable to the throw |
| MC-3 | a BlockReceiver or EC reconstruction still running when an include-list rejection unpublishes its pool finds corrupt data | NEW | by design | same as MC-2 for the receiver path (no NN path left); the EC reconstruction aborted runs on a DN the NN just rejected, and the NN reschedules it |
| CR-6 | `refreshNamenodes` drops a nameservice during in-flight DNA_TRANSFERs; the `DataTransfer` constructor dereferences `blockPoolManager.get()` unchecked (DN:3038) | NEW | by design (benign) | the same race as MC-1 at another line; the NPE ends the command processor of a pool that is already unpublished (its commands were already moot). The residue is a cosmetic metric skew (`SumOfActorCommandQueueLength` stays at 1) |
| CR-2 | federation re-home refresh (2-3/38 natural); the new BPOS's init fails and `initBlockPool` left the pool published (DN:2195 before `initStorage`) | NEW | same defect as 28/CR-6 (HDFS-4843 variant) | the same re-home overlap; the dead BPOS stays mapped, so `deleteBlockPool` is refused and reports hit IllegalArgumentException (a client close failed in a controlled window) |
| CR-9 | documented null to `ns1` re-home with one NN (5/8 natural) | NEW | same defect as 28/CR-6 (HDFS-4843 variant) | identical mechanism and outcome to 28/CR-6 (no BPOS serves the pool; the process would exit) |
| CR-4 | refresh drops two or more nameservices while one of them exits on its own (NN disallow) | NEW | same defect as 28/CR-3 | `doRefreshNamenodes` steps 4/5 re-read `bpByNameserviceId` outside the monitor with no null/liveness check (step 4: NPE at BPM:248 here; step 5: BPM:281 in 28/CR-3); the refresh aborts part-way until re-run. The CME half was refuted by the run |
| CR-7 | an actor exits on its own (NN rejection, all volumes failed, init failure without retry) | NEW | real new bug (minor: resource leak) | `BPServiceActor.cleanUp` never interrupts its `CommandProcessingThread`, which stays parked in `queue.take()` for the life of the JVM (one per rejected actor on a federated DN), pinning the actor/BPOS/DataNode, and survives `DataNode.shutdown()`. No data or client effect. BPServiceActor changed on trunk only by HDFS-17953 and the revert, neither touches this; no JIRA/PR found |
| CR-8 | a DirectoryScanner reconcile straddles a `refreshNamenodes` that drops a nameservice (4/4 without hooks, compressed scan timing) | NEW | real new bug (minor: divergent state) | `FsDatasetImpl.checkAndUpdate` guards removed storage but not a released block pool, so the reconcile re-adds every on-disk replica of the released pool and the dataset disagrees with the pool registry for the rest of the process. No data loss or client effect shown; FsDatasetImpl changed on trunk only by HDFS-17938 (metric); no JIRA/PR found |

Bug runs: CR-2, CR-9 (= 28/CR-6), CR-4 (= 28/CR-3), CR-7, CR-8 (not the target). The target MC-1 and MC-2, MC-3, CR-6 are by design.

## hdfs-adhoc-35 (run 20261029-231311-855a; target REACHED_CONFIRMED by MC-1)

Target: `DataStorage.doTransition` L750, `federationSupported && !getClusterID().equals(nsInfo.getClusterID())` ("Incompatible clusterIDs").

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | a DN that loaded no DISK directory (PROVIDED-only, or its DISK dir failed at startup and is tolerated) hot-adds a genuine Hadoop 0.20/1.x data directory together with a current-layout one | NEW | same defect as 24/MC-1 (HDFS-14311 variant) | the unsynchronized parallel `DataStorage.prepareVolume` again, here on the DN-level shared `layoutVersion`/`clusterID` (a lock in prepareVolume removed every failure in the run). A false "Incompatible clusterIDs" and FAILED TO ADD; a manual retry succeeded 81/81. The trigger is far-fetched: hot-adding a pre-federation directory is not a documented upgrade path, and the DN must have no DISK directory loaded |
| MC-2 | the same race persists layout -57 and an empty `clusterID` in the 1.x directory's VERSION | NEW | same defect as 24/MC-1 (HDFS-14311 variant) | same root, same far-fetched trigger; the on-disk VERSION is corrupted and later loads fail at L750 (DN down at `failed.volumes.tolerated=0`) |

Bug runs: MC-1 (target) and MC-2, both = 24/MC-1 (not counted again).

## hdfs-adhoc-37 (run 20261029-233015-d8a9; target REACHED_CONFIRMED by MC-1)

Target: `DataStorage.doRollback` L942, `!(prevInfo.getLayoutVersion() >= current && prevInfo.getCTime() <= nsInfo.getCTime())` ("Cannot rollback to a newer state"; frame :947).

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | NN wall clock behind a legacy DN cTime at `-upgrade`/`-format`; later a DN `-rollback` start over a DN-level `previous/` holding that legacy cTime | NEW | same defect as 24/MC-4 | the same wall-clock cTime stamp with no monotonic check (FSImage:465, NNStorage:629), seen at the DN-level rollback guard. This trigger is far-fetched (the clock must read before 2011/2008 against the in-tree pre-federation image; a DN-level `previous/` exists only after a pre-federation upgrade); a regular DN start still works and nothing is lost |
| CR-5 | federated DN with an unfinalized DN-level snapshot from a pre-federation (0.20/1.x) upgrade, a second namespace formatted before HDFS-8164 (cTime 0) kept by rolling upgrades; DN started with `-rollback` and the cTime-0 namespace handshakes first | NEW | by design (outside documented procedures) | the scenario needs a pre-federation upgrade left unfinalized for years (the snapshot is removed at the first block report to a finalized active namespace) and then a DN rollback to a pre-federation layout on a federated DataNode, which the rollback procedure (run with the previous software) cannot serve anyway. No monotone-clock, documented sequence reaches it |
| CR-6 | the same state; deterministic when the snapshot's own NN is offline | NEW | by design (same as CR-5) | same mechanism and preconditions as CR-5. Its side note (`BLOCK_POOL_PATH_PATTERN` never matching `<SD>/previous` in `BlockPoolSliceStorage.doUpgrade`) is not what was reproduced |

Bug runs: MC-1 (target, = 24/MC-4). CR-5 and CR-6 are by design.

## hdfs-adhoc-38 (run 20261030-041020-0aa2; target REACHED_CONFIRMED by MC-1)

Target: `FSDirAppendOp.appendFile` L122, `lpPolicy != null && lpPolicy.getId() == file.getStoragePolicyID()` ("Cannot append to lazy persist file").

| finding | trigger | Specula novelty | class | reason |
| --- | --- | --- | --- | --- |
| MC-1 (target) | create and close a file with no policy; `setStoragePolicy(<ancestor>, LAZY_PERSIST)` (WRITE on the ancestor suffices); append | NEW | real new bug | `INodeFile.getStoragePolicyID` (L592-597) resolves an unset file through its current ancestors, and the directory branch of `setStoragePolicy` has no copy-on-create check, so an existing DISK file takes effective id LAZY_PERSIST: append (FSDirAppendOp:122) and truncate (FSDirTruncateOp:101) fail until the tag is unset, and `LazyPersistFileScrubber` (FSNamesystem:4683, also by effective id) deleted such a file, whose replica was intact on disk, after a transient DN outage (shown with shortened timers and replication 1). Default configuration, public unprivileged APIs. Code unchanged on trunk; no JIRA/PR found (34 queries in the run's post-verdict search) |
| MC-2 | rename an existing non-lazy file under a LAZY_PERSIST-tagged directory | NEW | same defect as 38/MC-1 | the same effective-policy resolution; rename neither checks nor copies the copy-on-create policy, which `setStoragePolicy` refuses when asked directly (FSDirAttrOp:446-451). Same append refusal (persists across NN restarts) and scrubber deletion |

Bug runs: MC-1 (target) and MC-2 (same defect).

## Batch 2 summary

Distinct real new bugs (15; the last two are minor, with no client-visible failure):

1. 12/CR-1: queued KeyUpdateCommands are applied newest-first (`putFirst`, HDFS-17372), so a DN's `currentKey` steps back and its transfer tokens are rejected for up to a key interval. Low: needs a ~3-key-interval command-thread stall at defaults.
2. 12/CR-4: in HA, standby key updates purge the DN's expired signing key without replacing it; after a long no-active-NN period, pipeline-recovery writes fail right after failover. Low: needs about 20 h with no active NN at defaults.
3. 24/MC-2: a disk formatted during an unfinalized upgrade gets the upgraded cTime and no `previous/`, so the documented rollback fails on it forever and can get the whole DN rejected. High.
4. 24/MC-3: a stale RU marker plus a replayed finalized RU status deletes a regular upgrade's `previous/`; the documented rollback then fails and the snapshot is gone. Critical, from operator commands only.
5. 24/MC-4 (with 37/MC-1): NN `-upgrade` stamps cTime from the wall clock with no monotonic check; a clock behind the old cTime fails every DN block pool. High impact, rare clock trigger.
6. 24/CR-2 (with 24/CR-6): a startup L421 failure is only logged and the volume keeps serving; after rollback, clients read another file's bytes, or a finalize deletes the only rolled-back replicas. Critical.
7. 24/CR-3: the DN registration is built from the live shared BlockPoolSliceStorage; a re-registration during a hot-swap upgrade carries a transient cTime and the DN silently drops out of the pool. High.
8. 24/CR-5: `setRollingUpgradeMarkers` returns at a PROVIDED dir instead of continuing; a later RU rollback deletes newer replicas. Critical data loss; non-default PROVIDED storage.
9. 24/CR-7: an NN crash mid-way through `-upgrade`'s per-directory VERSION loop leaves mixed cTimes that are accepted; losing the upgraded name dir later fails every DN pool with nothing to roll back to. Critical; needs two in-model faults.
10. 25/MC-1 (with 25/MC-3, 25/CR-3): the PROVIDED cTime check at BPSS:184 uses a cTime another directory's load left in the shared object, giving false failures, refused PROVIDED hot-adds, or a block pool that never re-initializes. Medium/High; PROVIDED only.
11. 25/CR-2: `BlockPoolSliceStorage.remove` NPEs on a PROVIDED dir's null root; the disk stays half-removed, reconfiguration is stuck forever and disk-failure handling is skipped. High; PROVIDED only.
12. 28/CR-3 (with 31/CR-4): `refreshNamenodes` races a BPOS's self-exit (no monitor or liveness check in steps 4/5 or `refreshNNList`), causing an admin NPE, an orphan actor, and later a torn-down live pool. Medium; narrow timing.
13. 38/MC-1 (with 38/MC-2): LAZY_PERSIST set on an ancestor, or a rename under one, applies to existing DISK files; append and truncate are refused, and the lazy-persist scrubber can delete the file after a transient DN outage. Critical (data loss); default configuration, unprivileged APIs.
14. 31/CR-7 (minor): the command-processor thread of a self-exited BPServiceActor is never interrupted, so one thread leaks per rejected actor and it survives `DataNode.shutdown()`.
15. 31/CR-8 (minor): a DirectoryScanner reconcile across a pool release re-adds the released pool's replicas, leaving the dataset and the registry divergent.

Already known or variants of known issues (each counted once):
- HDFS-13441 (lost KeyUpdateCommand reply): 12/MC-2 and 12/MC-4, both = 11/MC-2.
- HDFS-4701 (block recovery vs block-pool removal): 28/MC-1 (already known), plus 29/MC-1, MC-2 and MC-3.
- HDFS-4843 (same-pool BPOS replacement in `refreshNamenodes`): 28/MC-2 (already known), plus these variants of the start-new-before-stop-old overlap that leave no live BPOS: 28/CR-6, 29/CR-4, 31/CR-2 and 31/CR-9.
- HDFS-14311 / HDFS-12800 (shared BlockPoolSliceStorage loader race), on the unfixed hot-swap path: 24/MC-1 (variant), with 24/CR-8, 24/CR-9, 25/MC-2, 25/CR-4, 35/MC-1 and 35/MC-2.
- HDFS-7830 (volume lock not released on a failed add), at an uncovered step: 24/CR-4 (variant).
- HDFS-17984 (null replica answer treated as absent, block deleted), on a path its PR #8778 does not cover: 29/CR-2 (variant, critical data loss; worth reporting there).

Same defect as hdfs-adhoc-11 (not counted again): 12/MC-1 (= 11/MC-1), 12/MC-3 (= 11/MC-3), 12/MC-5 (= 11/MC-6). 12/CR-1 is the 11/CR-7 mechanism (masked there) and is counted here.

Counts over the 51 REPRODUCED findings:
- real new bug: 15 findings, 15 distinct defects (13 significant, 2 minor).
- already known: 2 findings (28/MC-1 HDFS-4701, 28/MC-2 HDFS-4843).
- variant of a known one: 4 findings (24/MC-1 HDFS-14311, 24/CR-4 HDFS-7830, 28/CR-6 HDFS-4843, 29/CR-2 HDFS-17984).
- same defect as another finding: 23 findings.
- by design: 7 findings (12/MC-6, 31/MC-1, 31/MC-2, 31/MC-3, 31/CR-6, 37/CR-5, 37/CR-6).

Non-default configuration: 24/CR-5, 25/MC-1 (with MC-3 and CR-3) and 25/CR-2 need PROVIDED storage. 35/MC-1 and MC-2 need a PROVIDED-only DN or a tolerated failed DISK dir, plus a pre-federation directory.
