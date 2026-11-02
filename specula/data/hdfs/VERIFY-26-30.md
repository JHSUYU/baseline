# VERIFY-26-30: independent source review of hdfs-adhoc-26 and hdfs-adhoc-30

Source: `/bulk/specula-adhoc/src/hadoop` @ `734dd8a67cd`. Abbreviations: `BPSS` = `.../server/datanode/BlockPoolSliceStorage.java`,
`DS` = `.../datanode/DataStorage.java`, `FSI` = `.../namenode/FSImage.java`, `BRW` = `.../datanode/BlockRecoveryWorker.java`,
`BPOS` = `.../datanode/BPOfferService.java`, `BPSA` = `.../datanode/BPServiceActor.java`.
Runs: 26 = `runs/20261029-113905-f621`, 30 = `runs/20261029-150547-7238`.
Upstream: `git log 734dd8a67cd..origin/trunk` over BPSS, DS, FSImage, BRW, BPOS, BPSA, BlockPoolManager shows only
unrelated commits (HADOOP-19986, HDFS-17953, revert b15adbcfa3b). Nothing below is fixed on trunk.

## Summary

| case / ID | verdict | reason class |
| --- | --- | --- |
| 26/MC-1 | **KEEP** (medium confidence) | real; documented ops plus a DN outage; the documented rollback can never complete on that DN |
| 26/MC-2 | DUPLICATE of 24/CR-6 (+ 26/MC-1 for the re-upgrade step) | same trigger (volume skipped at `-rollback`, `failed.volumes.tolerated` >= 1) and same harm (failed slice only logged, then finalized) |
| 26/MC-3 | DUPLICATE of 24/MC-2 | same root cause: `BPSS.format` stamps the upgraded cTime with no `previous/` |
| 26/MC-5 | DROP | wall-clock cTime regression (same class as 24/MC-4, 37/MC-1) plus a long operator chain |
| 26/CR-8 | DROP | unrealistic chain; NN-cTime-regression class; the first symptom (L421) is loud and the unfinalized case is fixed by DN `-rollback` |
| 30/MC-1 | DROP | designed/transient: HA failover cost; the old NN's recovery id cannot commit on the new active anyway; NN re-drives |
| 30/MC-2 | DROP | by design: the DN left the active NN's service (HDFS-15651 handling, refresh, include list); same class as 31 |
| 30/MC-3 | DROP | duplicate of 29/MC-1 (HDFS-4701 race); bounded stall, NN re-drives |
| 30/MC-4 | DROP | HDFS-4843 family (refreshNamenodes same-pool BPOS replacement); transient, NN re-drives |

---

## hdfs-adhoc-26: `BPSS.doRollback` L621 "Cannot rollback to a newer state"

Guard (BPSS:618-620): rollback only if `prev.LV >= softwareLV && prev.cTime <= nsInfo.cTime`. The comment at BPSS:614-617 says this is
intended: rollback is allowed only to a state "consistent with the namespace state or can be further upgraded to it". So every
candidate must show how the real code produces a `previous/` whose cTime is above the cTime of the rolled-back NN.

Shared facts verified:
- `doTransition` (BPSS:369-425): ROLLBACK with `previous/` -> `doRollback` (375-379); a regular start upgrades whenever
  `this.cTime < nsInfo.cTime` (414-417), and throws "newer than the namespace state" when it is greater (419-424).
- `doUpgrade` (BPSS:445-519) deletes any existing BP `previous/` without looking at it (477-480), renames current to
  previous.tmp (486), stamps `cTime = nsInfo.cTime` (512) and renames previous.tmp to previous (517). The javadoc (432) and
  `TestDFSUpgrade` "DataNode upgrade with existing previous dir" (TestDFSUpgrade:275-284) make this deliberate: a DN `previous/`
  is assumed disposable (for example, left over from a finalize the DN missed).
- NN side: `FSI.checkUpgrade` (FSI:423-433) refuses `-upgrade` only if an **NN** `previous/` exists; `FSI.doUpgrade` sets
  `cTime = now()` (FSI:465). `NamespaceInfo` carries no NN-previous cTime, so a DN cannot tell an abandoned epoch from a current one.
- Consumers: `DS.loadBlockPoolSliceStorage` only logs a per-volume failure (DS:473-476); if every volume fails,
  `DS.recoverTransitionRead` throws "All specified directories have failed to load." (DS:566-567) and the actor exits (BPSA:910-922).
  `DS.finalizeUpgrade` (DS:1016-1029) iterates every DN-level dir, including slices that failed to load.

### 26/MC-1: a DataNode that misses an NN rollback silently re-upgrades its abandoned epoch — KEEP (medium)

**Code path (verified):**
1. NN `-upgrade` (c0 -> c1 = now(), FSI:465). The DN starts normally: c0 < c1 -> `doUpgrade` (BPSS:414-417). Its BP is now current = c1, previous = c0.
2. Documented rollback (HdfsUserGuide.md:324-328): `hdfs namenode -rollback` restores NN c0 and removes the NN `previous/`. One DN is
   out of service (hardware repair) and is never started with `-rollback`. Its slices stay current = c1, previous = c0.
   (If it came back now, BPSS:419-424 would refuse it loudly and a `-rollback` start would fix it; that path is fine.)
3. The operator retries the upgrade later: `FSI.checkUpgrade` passes because the NN has no `previous/` (FSI:427-431), and c2 = now() > c1.
4. The repaired DN starts normally. c1 < c2, so BPSS:414-417 upgrades it: BPSS:478-480 **deletes the valid c0 snapshot**, and current c1 (the
   abandoned epoch) becomes previous (486, 512-517). Nothing is logged as wrong. The DN registers and reports its abandoned-epoch replicas.
5. The second upgrade is also rolled back: NN back to c0 (its `previous/` was saved at step 3). DN `-rollback`: BPSS:375-379 -> `doRollback`;
   previous cTime c1 > nsInfo c0 -> **throw at BPSS:621** on every volume -> DS:566-567 -> actor exits.
6. Permanence: a regular restart throws at BPSS:421 (c2 > c0), a `-rollback` restart throws at 621 again. Only hand-edited VERSION files,
   wiping the DN, or another `-upgrade` (abandoning the rollback) gets out.

**Reproduction:** `repro/test_bugMC-1_dn_missed_rollback_reupgrade.java`, a variant of `TestDFSRollback#testRollback`. It uses only
NN `-upgrade`, `NameNode.doRollback`, DN REGULAR/`-rollback` starts, and a DN that is simply not started (the outage). It writes no
VERSION file and uses no reflection (it only reads VERSION files). Target frame `doRollback(BPSS:626)` (the throw statement starting at
621), 4/4 runs; the control (the DN took part in the first rollback) rolls back cleanly.

**Bug vs design:** the guard at 621 is correct. The defect is upstream: the DN-side BP upgrade (BPSS:414-417 + 477-480) accepts any stale
cTime below the NN's and throws away an unfinalized `previous/`, while the NN refuses exactly that for itself (FSI:424-431, "Finalize or
rollback first"). The javadoc/test treat a leftover DN `previous/` as a missed finalize; nothing distinguishes a missed rollback. The user guide's
procedure has no step for a DN that was absent during the rollback, and step 4 gives no signal that one was missed.

**Severity:** the documented rollback cannot complete on that DN, permanently, without manual storage surgery (same severity class as the
kept 24/MC-2). Data in that DN's `previous/` is actually the right snapshot (the cTime label is what is wrong), so with replication >= 2 and other
DNs rolled back, there is no data loss; the NN marks the DN dead and re-replicates. The repro's BlockMissingException is at replication 1. An
unproven aggravation: at step 4 the DN re-admits abandoned-epoch replicas whose block IDs/genstamps the rolled-back NN reallocates (the
24/CR-2 wrong-data risk). Default configuration.
**Trigger realism:** every step is a documented operation plus a DN outage spanning a rollback and the re-upgrade, but it needs two
rolled-back non-rolling upgrades in a row. Moderate-to-low likelihood.
**Known?** No JIRA found (run: 14 JIRA queries, GitHub, web; my web search found only HDFS-5526/6137 layout-version issues, HDFS-6005, HDFS-6800,
HDFS-12120, all different mechanisms). **Duplicate?** No: 24/MC-2 is a newly formatted slice, 24/CR-6 is a single volume plus the finalize consumer,
24/MC-3 is the RU marker. This is a distinct root cause (silent DN re-upgrade over an abandoned epoch). **Confidence: medium.**

### 26/MC-2: volume missing a DN `-rollback` keeps the abandoned upgrade — DUPLICATE of 24/CR-6

Path is valid: with `dfs.datanode.failed.volumes.tolerated` >= 1, a disk that fails the startup check at the DN `-rollback` start keeps
current = c1, previous = c0 (the 24/CR-6 trigger). If it returns **after** the NN re-upgrade, BPSS:414-417 re-upgrades it (the 26/MC-1 step), and the next rollback throws
at 621 for that volume. The throw is only logged (DS:473-476), the volume stays in the dataset, and the NN's FinalizeCommand -> `DS.finalizeUpgrade`
(DS:1019-1029) deletes its `previous/`. That is exactly the 24/CR-6 consumer, which also caused 24/CR-6's data loss. Same trigger family
(volume missed `-rollback`, non-default tolerated >= 1) and same harm consumer; the only new piece is the re-upgrade step, which is 26/MC-1's root
cause. Fixing 24/CR-6 (treat a failed slice as a failed volume / skip finalize) plus 26/MC-1 removes it. **Class: duplicate.** Confidence: high.

### 26/MC-3: volume formatted during an unfinalized upgrade — DUPLICATE of 24/MC-2

Root cause stated by the run itself: `BPSS.format` (BPSS:283-292) stamps the upgraded cTime with no `previous/`. That is verbatim 24/MC-2.
24/MC-2 already shows that the first rollback fails at L421 for that slice. MC-3 continues (failure only logged -> re-upgrade at 414-417
snapshots that cTime -> next rollback throws at 621 -> finalize deletes it), which chains 24/MC-2 with the 24/CR-6 consumer. **Class: duplicate of 24/MC-2.**
Confidence: high.

### 26/MC-5: NN `-upgrade` under a stepped-back wall clock — DROP

Path: FSI:465 `cTime = now()` with no monotonic check (24/MC-4's root cause). It additionally requires the DN to stay down while the NN runs at the
regressed cTime (otherwise BPSS:419-424 refuses it loudly), a `-finalizeUpgrade` in that state, a later re-upgrade once the clock passes c0, and then a rollback.
The repro mocks `Time.now` with `MockedStatic`. Wall-clock cTime regression was already dropped as not severe/realistic (24/MC-4, 37/MC-1); this is the
same root with a longer operator chain. **Class: duplicate of a dropped class (environmental clock fault).** Confidence: high.

### 26/CR-8: `-importCheckpoint` of a pre-upgrade checkpoint regresses cTime — DROP

Path verified: `FSI.doImportCheckpoint` adopts the checkpoint's StorageInfo, cTime included (FSI:605). With a checkpoint older than the last
`-upgrade`, the NN goes back to c0 while DN slices hold c1. Then:
- Every regular DN start throws loudly at BPSS:421 (not the target). If the upgrade was unfinalized, the obvious DN `-rollback` succeeds (previous c0 <= c0).
- Reaching 621 needs the operator to choose `-upgrade` as a workaround (c2), which re-upgrades the DNs (the 26/MC-1 mechanism, BPSS:477-480), and then to roll
  **that** upgrade back.
The trigger is disaster recovery (all NN name dirs lost, with no HA/JournalNodes), a checkpoint older than the last upgrade (SNN checkpoints hourly by default),
and two further voluntary operator steps. The root is an NN cTime regression, the same class as the dropped clock case, and the 621 step reuses 26/MC-1's mechanism.
**Class: unrealistic trigger / NN-cTime-regression class.** Confidence: medium-high.

---

## hdfs-adhoc-30: `BRW.getActiveNamenodeForBP` L609 `activeNN == null`

Verified: `getActiveNamenodeForBP` (BRW:600-612) looks up the BPOS (602) and reads `bpos.getActiveNN()` (607, BPOS:532-543, null if
`bpServiceToActive == null`). It is called from `syncBlock` (BRW:188-189) after the `initReplicaRecovery` round and before any
`updateReplicaUnderRecovery` / `commitBlockSynchronization`. On the IOException, `recoverBlocks` only logs "recover Block ... FAILED"
(BRW:628-631). Replicas are left in RUR state, which the next `initReplicaRecovery` with a higher recovery id handles. The NN re-drives recovery via
`PendingRecoveryBlocks` (BlockManager:596-597, timeout = 30 x heartbeat interval = 90 s by default), the lease hard limit, or a client `recoverLease`.
`bpServiceToActive` becomes null in exactly three places: a non-ACTIVE heartbeat from the believed-active NN (BPOS:608-611), `shutdownActor` (BPOS:479-480),
and a fresh BPOS whose first handshake was with a standby (BPOS:386-390). Each candidate is one of these.

### 30/MC-1: HA demotion during lease recovery — DROP (designed / transient)

Graceful failover: the old active's STANDBY heartbeat clears the active (BPOS:608-611), and L609 throws until the new active's claim (BPOS:586-606).
Even without the throw, the commit could not succeed: the recovery id was issued by the old active and lives in its memory, and the new active rejects a mismatching
`recoveryId` at `FSNamesystem.commitBlockSynchronization` (FSNamesystem:4104-4108). The new active re-runs recovery. No data loss, bounded delay; this is the
failover's designed cost, and the run's own severity notes say so. **Class: transient, retried by the NN.** Confidence: high.

### 30/MC-2: active NN's actor exits while the standby actor keeps the pool — DROP (by design)

Routes: CommandProcessingThread death -> `shouldServiceRun = false` (BPSA:1411-1421, the HDFS-15651 fix, which deliberately makes the actor exit so the NN
treats the DN as dead), an Error in the actor (BPSA:938-946), DisallowedDatanodeException after include-list removal, or `refreshNamenodes` dropping nn0.
`shutdownActor` clears the active (BPOS:479-480), and the standby actor keeps the BPOS alive (BPOS:483-487). In every route the DN has stopped serving the active NN
(no heartbeats or block reports), and the NN reacts by marking it dead and re-replicating. The single-replica "stays open" outcome follows from the DN having left the
active NN, not from L609; the operator routes are what the operator asked for. This is the same class as the 31 DN-leaving-pool findings (judged by design).
**Class: by design; the NN re-drives.** Confidence: medium-high.

### 30/MC-3: single NN, actor exit between L602 and L607 — DROP (duplicate of 29/MC-1, HDFS-4701)

The race of a recovery daemon against block-pool teardown (DN shutdown, disallow, disk error): `shutdownActor` nulls the active and deregisters the BPOS in one
locked section that can fall between the two reads. This is 29/MC-1 (the same race at BRW:602), already classified as HDFS-4701. The window is a few instructions (0/6 hook-free),
the DN is usually going down anyway, and the NN's timeout re-issue closed the file. Only the error message is misleading. **Class: duplicate (HDFS-4701 family), transient.**
Confidence: high.

### 30/MC-4: recovery re-looks up the BPOS after `refreshNamenodes` — DROP (HDFS-4843 family)

A nameservice rename/re-add via `refreshNamenodes` starts a new BPOS for the same bpid before stopping the old one (BlockPoolManager:209-252). The new one is
registered by bpid at its first handshake, and if that handshake was with the standby (BPOS:386-390) its active view is null until the active handshakes or heartbeats.
This is the start-new-before-stop-old overlap of HDFS-4843 (28/MC-2, 28/CR-6, 29/CR-4). The outcome here is milder: one failed attempt until the active is acknowledged
(about one heartbeat), and the NN's timeout re-issue completes the recovery. It needs an operator rename refresh during a recovery plus a standby-first handshake (0/6
hook-free). **Class: known family, transient.** Confidence: high.
