# VERIFY-storage: independent source review of storage-transition claims

Source: `/bulk/specula-adhoc/src/hadoop` @ `734dd8a67cd`. All file:line references are to that tree. Paths are abbreviated:
`BPSS` = `hadoop-hdfs/.../server/datanode/BlockPoolSliceStorage.java`, `DS` = `.../datanode/DataStorage.java`,
`FSI` = `.../namenode/FSImage.java`, `FSN` = `.../namenode/FSNamesystem.java`.
Upstream check: `git log 734dd8a67cd..origin/trunk` over BPSS, DS, FSImage, NNUpgradeUtil, BPOfferService, DataNode,
FsDatasetImpl, FSDirAppendOp, INodeFile, FSDirAttrOp, FSDirRenameOp and FSNamesystem shows only unrelated commits
(HDFS-17978, HADOOP-19986, HADOOP-19951, revert b15adbcfa3b, HDFS-17938, HDFS-17899, HDFS-17980, HDFS-17924). None of the
claims below is fixed on trunk.

## Summary

| case / ID | verdict | reason class |
| --- | --- | --- |
| 24/MC-2 | **KEEP** | real, documented ops plus a disk replacement; rollback cannot complete |
| 24/MC-3 | **KEEP** (medium confidence) | real, documented ops only; rare timing window |
| 24/MC-4 | DROP | low severity: an environmental clock fault, a loud failure, recoverable through the documented rollback |
| 24/CR-6 | **KEEP** (representative of 24/CR-2) | real; the severe part is that a slice failing L421 stays in the dataset and is then finalized |
| 24/CR-7 | DROP | low likelihood: two independent faults, one inside a millisecond window |
| 37/MC-1 | DROP | duplicate of 24/MC-4, with an even less realistic trigger |
| 25/MC-1 | DROP | non-default config only (PROVIDED storage), low severity |
| 35/MC-1 | DROP | unrealistic trigger; duplicate of the hot-swap race (HDFS-14311 variant); retry succeeds |
| 35/MC-2 | DROP | duplicate of 35/MC-1 (same race, same far-fetched trigger) |
| 38/MC-1 | **KEEP** (representative; 38/MC-2 grouped) | real; contradicts LAZY_PERSIST copy-on-create semantics; can lead to scrubber data loss |
| 38/MC-2 | DROP as a duplicate of 38/MC-1 | same root cause; rename is a more common trigger |

---

## hdfs-adhoc-24 / MC-2: disk formatted during an unfinalized upgrade, then the documented rollback — KEEP

**Code path (verified):**
1. `hdfs namenode -upgrade`: `FSI.doUpgrade` sets `storage.cTime = now()` (FSI:465), giving cUp > c0.
2. The upgrade is still unfinalized. A DN starts with an empty (new or replaced) data dir. `BPSS.loadStorageDirectory`
   hits `NOT_FORMATTED` (BPSS:167-171), and `BPSS.format` (BPSS:283-292) writes `cTime = nsInfo.getCTime()` (cUp) with
   **no `previous/`**. Hot-add (`DS.prepareVolume`, DS:324-346) reaches the same format path.
3. Documented rollback: `namenode -rollback` (NN back to c0), then the DN starts with `-rollback`. In `BPSS.doTransition`,
   ROLLBACK without `previous/` only restores trash (BPSS:380-387). `readProperties` (BPSS:388) loads cUp into the
   **shared** BPSS fields. L404 (cUp != c0) and L414 (cUp < c0 is false) are not taken, so the **L421 throw** happens on every later
   start too.
4. Consequences: `DS.loadBlockPoolSliceStorage` only logs the failure (DS:473-476), and `DS.recoverTransitionRead` throws only if all
   volumes fail (DS:566). The DN-level dir stays in `DataStorage`, so `FsDatasetImpl` still adds the volume
   (FsDatasetImpl:361-362) and `FsVolumeImpl.addBlockPool` (FsVolumeImpl:1122-1131) serves the slice's post-upgrade replicas.
   If that slice is the last one read, the shared BPSS keeps cUp. `DataNode.createBPRegistration` (DataNode:2073-2074) then
   registers with it, and `NameNodeRpcServer.verifyRequest` (1777-1786) rejects every heartbeat with
   `UnregisteredNodeException`. Repro log: "Registration IDs mismatched ... -1793281844888 but expected
   ...-1793281840515", the BP service exits, and the NN stays in safe mode.

**Reproduction:** `repro/test_bugMC-2_rollback_gap.java` starts from the TestDFSUpgrade set-up and uses only `-upgrade`,
`NameNode.doRollback`, DN `-rollback`, and an empty data dir (`UpgradeUtilities.createEmptyDirs`), which models a new or replaced disk.
No VERSION file is hand-written and no reflection is used. The target frame is `doTransition(BPSS:424)` (the throw statement that starts at L421). Tests: 4 run, 0 failures.

**Bug vs design:** The HdfsUserGuide upgrade section ("may be after a few days of operation") and the hot-swap section
document both operations, and nothing forbids adding or replacing a disk while an upgrade is unfinalized. HDFS-6728 made
formatting hot-added volumes intended behaviour. No code path handles a slice that was created after the snapshot: there
is no `previous/`, and no discard or re-format happens on rollback. The rollback therefore cannot complete for that disk. The L421 guard
itself behaves correctly; the bug is the missing rollback path for a slice formatted during the upgrade window (BPSS:283-292
together with BPSS:380-388).

**Severity:** high. The documented rollback leaves a permanently failing slice, and only a manual deletion of the slice or a re-upgrade
recovers it. Depending on the order of `dfs.datanode.data.dir`, either the whole DN drops out of the block pool (pre-upgrade replicas on
its other disks become unreachable), or the stale volume keeps serving post-upgrade replicas that the rolled-back NN does not
know about. Those replicas can match block IDs and generation stamps that the NN hands out again (the CR-2 mechanism). Default config.
Trigger likelihood is moderate: replacing a disk during a multi-day upgrade window is ordinary operations.

**Known?** No JIRA found by the run's 18 queries. The code is unchanged on trunk. **Confidence: high.**

## hdfs-adhoc-24 / MC-3: stale RU marker plus a replayed finalized RU status deletes a regular upgrade's `previous/` — KEEP (medium)

**Code path (verified):**
1. `dfsadmin -rollingUpgrade prepare`. Each heartbeat runs `BPServiceActor.handleRollingUpgradeStatus` (BPServiceActor:656-667), then
   `BPOfferService.signalRollingUpgrade` (BPOfferService:555-567), then `setRollingUpgradeMarkers`, which writes
   `<vol>/current/<bpid>/RollingUpgradeInProgress` (BPSS:863-881).
2. The DN is down when `-rollingUpgrade finalize` runs (FSN:7800-7831). Its markers stay on disk. Only `clearRollingUpgradeMarkers`
   removes them, and only from the heartbeat path.
3. The NN restarts with `-upgrade` before any post-finalize checkpoint. `FSI.doUpgrade` replays OP_ROLLING_UPGRADE_START and FINALIZE
   (FSEditLogLoader:892-918), so `rollingUpgradeInfo` is non-null and finalized. `checkRollingUpgrade` passes, because it only blocks an
   in-progress RU (FSN:7727-7729, 7792-7798). A checkpoint would drop the info, because the image stores the RU start only while
   it is in progress (FSImageFormatProtobuf:982-983, 513-517).
4. The DN restarts. Its slices are upgraded and get `previous/` (BPSS:414-417, 436-519). The marker sits in the bp root, not
   in `current/`, so the upgrade does not move it.
5. Every heartbeat carries the finalized info (`new HeartbeatResponse(cmds, haState, rollingUpgradeInfo, ...)`, FSN:4512).
   `signalRollingUpgrade` sees it finalized, `clearRollingUpgradeMarkers` finds the marker, and `doFinalize` (BPSS:900, 651-689)
   deletes the **regular** upgrade's `previous/` while the NN upgrade is still unfinalized. This contradicts the design comment
   at BPSS:73-81 ("marker absent ⇒ regular upgrade may be in progress. Do not delete 'previous'"), which assumes
   that a present marker means an RU just completed.
6. Documented rollback with DN `-rollback`: there is no `previous/` (BPSS:380-387), the slice cTime is cUp and the NN cTime is c0, so **L421**
   throws on every volume. That leads to "All specified directories have failed to load" (DS:566-567), and the DN cannot rejoin.

**Reproduction:** `repro/test_bugMC-3_SpeculaAdhocMC3Test.java` uses only dfsadmin RU prepare/finalize, `stopDataNode`,
`restartNameNode("-upgrade")`, `NameNode.doRollback` and DN `-rollback`. Mode DN_DOWN_FIRST needs no timing help. A
control run with the DN up during finalize succeeds. Output: `repro/MC-3.run.out` (3/3 runs, the L421 frame appears, and `previous/` is logged as finalized
by the heartbeat).

**Severity:** high when it happens. The rollback snapshot of every volume on that DN is deleted (permanent), and the DN cannot
join the rolled-back cluster for that block pool without manual cleanup. Blocks that were deleted after the upgrade are lost from that DN.
**Likelihood:** low. The DN must stay down from before the RU finalize until after the NN `-upgrade`, and the `-upgrade` must
come before the next checkpoint (SNN or standby, every hour by default). That means a regular upgrade shortly after finishing a rolling upgrade.
Default config.
**Known?** HDFS-6981 and HDFS-7645 designed this marker logic, and neither covers a DN that missed the finalize. No JIRA was found, and the code is unchanged on trunk.
**Confidence: medium.** The bug is real and fully on documented paths. It is kept, but the trigger window is narrow.

## hdfs-adhoc-24 / MC-4: NN `-upgrade` cTime from the wall clock without a monotonic check — DROP (low severity / environmental)

The path is correct: FSI:464-465 sets `storage.cTime = now()` and compares it with nothing. If that value is below the DN slices' cTime, L404 and L414 are both
false and every slice throws at **L421**. However:
- The trigger requires the NN wall clock to read earlier than the previous format or upgrade stamp. That stamp is usually months old
  (NNStorage:626-630 also uses `Time.now()`), so the clock has to be badly wrong (for example an RTC reset without NTP) at exactly the
  `-upgrade` run. Wall-clock cTime has been the design for a long time (format also uses `Time.now()`).
- The failure is loud and cluster-wide (no DN registers, the NN stays in safe mode), and it occurs before anything can be finalized. The
  documented `namenode -rollback` restores c0, which matches the DN slices, and the upgrade can then be retried with a correct clock. Nothing is lost.
The repro mocks `Time.now` with `MockedStatic<Time>`. That is a fair model of a clock fault, but the outcome is a clean, recoverable
refusal. **Class: low severity (clean, recoverable error under an environmental misconfiguration).** Confidence: high.

## hdfs-adhoc-24 / CR-6: a volume misses the DN `-rollback`, then a regular restart (with CR-2) — KEEP

**Code path (verified):**
1. NN `-rollback`, then DN `-rollback`. With `dfs.datanode.failed.volumes.tolerated` ≥ 1, an offline disk is skipped
   (`DS.loadDataStorage` DS:403-448), and its slice keeps current(cUp) and previous(c0).
2. The disk comes back and the DN restarts normally. In `doTransition`, the start option is not ROLLBACK, so `readProperties` (BPSS:388) gives cUp > c0 and **L421** throws.
3. As in MC-2, the failure is only logged (DS:473-476). The DN-level dir is still a volume (FsDatasetImpl:361-362, FsVolumeImpl:1122-1131),
   which contradicts the javadoc at BPSS:199-202 and 236-239 ("a failure on loading any block pool storage results a faulty data volume").
4. The rolled-back NN has `isUpgradeFinalized` set, so every block report returns a `FinalizeCommand` (NameNodeRpcServer:1682-1686).
   `DS.finalizeUpgrade` (DS:1016-1029) iterates **all** DN-level dirs, including the volume that failed L421, and
   `BPSS.doFinalize` deletes its `previous/`, the only copy of that volume's pre-upgrade replicas. A later `-rollback` hits L421
   again and recovers nothing (repro: BlockMissingException, 2 missing blocks). If the stale volume is listed last instead, its cUp leaks into the
   registration and the BP service exits (as in MC-2).
5. Crash variant: a DN crash after BPSS:637 followed by a regular restart leads to RECOVER_ROLLBACK and then L421. The tail of volumes is always stale, so the last-read
   volume is stale, which gives the loud registration-mismatch outcome. A `-rollback` restart recovers from it.

**Reproduction:** `repro/test_bugCR-6_rollback_missed_volume.java` uses MiniDFSCluster with a volume that is absent during the `-rollback`
start (an offline disk) and a real-JVM SIGKILL for the crash variant. No VERSION writes. 6 tests, 0 failures. The hot-swap sub-case
(the volume is refused) is the guard working and is not counted.

**Severity:** high. The permanent-loss outcome deletes the rollback snapshot on a volume that never rolled back, and the stale volume
serves post-upgrade replicas whose block IDs and generation stamps the rolled-back NN will hand out again (the CR-2 wrong-data risk). **Trigger:** `failed.volumes.tolerated` ≥ 1
(not the default, but common on JBOD DataNodes) plus a disk that is offline during the rollback start and returns later. The default-config crash variant
is only loud and recoverable.
**Duplicate grouping:** 24/CR-2 (an L421 at startup is only logged, and the volume keeps serving and gets finalized) is the shared root defect. CR-6 is kept as
the representative, and MC-2 is an additional trigger of the same downstream damage. **Known?** HDFS-8127 hits the same FinalizeCommand consumer with a
different trigger. Nothing on point was found. **Confidence: medium-high.**

## hdfs-adhoc-24 / CR-7: NN crash in the per-dir VERSION loop, then loss of the upgraded name dir — DROP (low likelihood)

The path is plausible. `FSI.doUpgrade` writes VERSION one directory at a time (FSI:501-509 → NNUpgradeUtil:183-204). On restart,
`Storage.doRecover` applies RECOVER_UPGRADE only to the unfinished dir, and `StorageInfo.setcTime` does not cross-check cTime between dirs, so mixed
cTimes are accepted. After a finalize, losing the one dir that was upgraded makes the NN report c0, and every slice throws at L421 with no
`previous/` left anywhere. This needs (a) an NN crash between two `writeProperties` calls, a window of milliseconds, (b) no
`saveNamespace` in between (any stale-image startup save or `-saveNamespace` runs `storage.writeAll()` at FSI:1170-1173 and heals the split),
and (c) a later loss of that specific name dir. That is two independent faults, one of them in a tiny window. The severity would be high, but
the realistic likelihood is negligible. **Class: low likelihood.** Confidence: medium.

## hdfs-adhoc-37 / MC-1: NN wall clock behind a legacy DN-level `previous/` cTime at DN `-rollback` (DS:942) — DROP (duplicate)

This is the same root as 24/MC-4 (FSI:465 and NNStorage:629 use the wall clock), reached at `DS.doRollback`'s guard (DS:938-947). It additionally needs a
DN-level `previous/`, which exists only after a pre-federation (0.20/1.x) upgrade that was never finalized, and an NN clock earlier than 2008-2011 (the repro
uses an LD_PRELOAD wall-clock shim). A regular DN start still works and nothing is lost. **Class: duplicate of 24/MC-4, and not realistic.**

## hdfs-adhoc-25 / MC-1: PROVIDED dir after a DISK dir fails the cTime check at BPSS:185 — DROP (non-default config)

The path is verified. For PROVIDED, `doTransition` returns false without reading VERSION (BPSS:372-374), so the check at BPSS:184 compares the
cTime that the previous DISK dir's load left in the shared BPSS. If that DISK slice was queued for upgrade, its cTime is updated only later
in the callable (BPSS:512). The result is a false "Datanode CTime ... is not equal to namenode CTime". The ordering matches the documented example
(`HdfsProvidedStorage.md:82-85`), but PROVIDED storage is an experimental, non-default feature. The outcome is a logged BP-load failure for the
PROVIDED volume until the next restart, with no data loss. **Class: non-default config only, low severity.**

## hdfs-adhoc-35 / MC-1 and MC-2: parallel hot-swap workers tear DataStorage's `layoutVersion`/`clusterID` (L750) — DROP

The race is real. `DataNode.refreshVolumes` submits one `data.addVolume` per new location to a thread pool (DataNode:1312-1325).
`DS.prepareVolume` (DS:324-346) is not synchronized, and `loadStorageDirectory` → `doTransition` (DS:719-753) reads and writes the shared
`layoutVersion`/`clusterID` fields. This is the same unsynchronized hot-swap load that HDFS-14311 (4cb22cd867a) fixed only on the
startup path. Reaching L750 needs the DN to have no DISK directory loaded **and** one reconfiguration that hot-adds a genuine
pre-federation (0.20/1.x) data dir together with a current one. Hot-adding a pre-federation dir is not a documented
procedure. MC-1's effect is a false "Incompatible clusterIDs" and a refused add, and a manual retry succeeded 81/81. MC-2 (an empty clusterID
persisted into the 1.x dir's VERSION) has the same trigger. **Class: unrealistic trigger; a variant of the known HDFS-14311 race; MC-2 is a duplicate of MC-1.**

## hdfs-adhoc-38 / MC-1: LAZY_PERSIST set on an ancestor after create makes append throw at FSDirAppendOp:122 — KEEP (MC-2 grouped)

**Code path (verified):**
1. A file is created and closed with no policy. Its local policy is UNSPECIFIED. Because no copy-on-create policy was in effect at create, the file
   is not stamped (FSDirWriteFileOp:831-840).
2. `setStoragePolicy(<ancestor dir>, LAZY_PERSIST)` needs only WRITE on the dir (MemoryStorage.md: "Administrative privileges are
   *not* required"). The directory branch `setDirStoragePolicy` (FSDirAttrOp:465-467) has no copy-on-create check. The file
   branch refuses exactly this change for a file ("Policy ... cannot be set after file creation", FSDirAttrOp:446-451).
3. `INodeFile.getStoragePolicyID` (INodeFile:591-597) falls back to `getParent().getStoragePolicyID()` (INodeDirectory:134-141),
   so the existing DISK file's *effective* id becomes LAZY_PERSIST.
4. `fs.append`: `FSDirAppendOp.appendFile` evaluates `lpPolicy.getId() == file.getStoragePolicyID()` (FSDirAppendOp:119-124), which is true, and
   **throws UnsupportedOperationException "Cannot append to lazy persist file"**.
5. The same effective id drives `LazyPersistFileScrubber.clearCorruptLazyPersistFiles` (FSN:4686-4715). Any such file whose block
   is in the missing/corrupt queue (all replicas temporarily unavailable) is **deleted from the namespace** even though it was written to
   DISK and its replica is intact (repro t9/t10: `exists=false`, `replicaFileOnDisk=true`, with shortened timers and replication 1).
   The default scrub interval is 300 s.

**Bug vs design:** For ordinary policies, ArchivalStorage.md:84-88 documents that inheritance is resolved through the parent and so applies to existing
files. LAZY_PERSIST, however, was made copy-on-create precisely so that it applies only to new files (HDFS-7159, bb84f1fccb1). MemoryStorage.md
says "Setting the policy on a directory causes it to take effect for all new files in the directory", and FSDirAttrOp:446-459
forbids making an existing file lazy-persist. The append check and the scrubber use the inherited id instead of the stamped
local id, so a file that was never written lazily is treated as a lazy-persist file. That contradicts the documented semantics: it is a bug, not intended inheritance.

**Reproduction:** `repro/test_bugMC-1_append_after_ancestor_lazy_persist.java` uses only public client APIs (setStoragePolicy, append,
`hdfs dfs -appendToFile`, a non-admin user via UGI). It adds one line to the workload `TestFileAppend#testAppendTwice`, and NN frames at
FSDirAppendOp:122 appear in every run (`MC-1.stability.txt`: 2/2 repeats, 12 tests).

**Severity:** the append refusal is persistent but clean, and `unsetStoragePolicy` works around it. The scrubber deletion is silent, permanent
data loss of files that were written with full durability. It needs every replica of one block to be unavailable during a scrub, which is likely with replication 1
(typical for scratch dirs where someone would set LAZY_PERSIST) and possible with replication 3 during multi-node outages. One user with
WRITE on a shared parent (for example `/tmp` or a project dir) can expose other users' files to both effects (repro t7). Default config.
**Known?** Nothing found (34 queries in the run, and the code is unchanged on trunk). **Confidence: high** for the path and the design contradiction.

**38/MC-2 (rename into a LAZY_PERSIST dir): duplicate of 38/MC-1.** `FSDirRenameOp` neither checks nor copies a copy-on-create policy,
so a renamed UNSPECIFIED file inherits LAZY_PERSIST through the same INodeFile:591-597 resolution and gets the same append refusal and scrubber
exposure. This is probably the more common trigger in practice (write to a temp dir, then rename into an output dir), but the root cause is the same.

---

## KEEP list (root causes)

1. **24/MC-2**: `BlockPoolSliceStorage.format` (BPSS:283-292) stamps the upgraded NN cTime on a slice created during an unfinalized upgrade, with no `previous/`.
   The rollback has no path to discard it (BPSS:380-388), so L421 fails on every start, and the DN can be rejected or can serve unknown post-upgrade replicas.
2. **24/MC-3**: `clearRollingUpgradeMarkers` (BPSS:889-909) trusts a stale RU marker plus a finalized RU status replayed from edits (FSEditLogLoader:892-918,
   FSN:4512), and `doFinalize` deletes a *regular* upgrade's `previous/`. The documented rollback then fails at L421 (rare timing window).
3. **24/CR-6 (with CR-2)**: a block-pool load failure at L421 is only logged (DS:473-476), but the volume stays in FsDataset and in the `DS.finalizeUpgrade`
   iteration (DS:1016-1029). A volume that missed the DN `-rollback` keeps serving stale replicas, and its `previous/` is deleted by the NN's FinalizeCommand.
4. **38/MC-1 (with MC-2)**: the append check (FSDirAppendOp:121-122) and `LazyPersistFileScrubber` (FSN:4702) use the *inherited* storage policy, but
   LAZY_PERSIST is copy-on-create (new files only). Tagging an ancestor, or renaming a file into a tagged dir, makes existing DISK files unappendable and lets the scrubber delete them.
