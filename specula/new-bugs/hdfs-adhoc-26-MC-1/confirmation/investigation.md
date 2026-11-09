# MC-1 — Phase 1 investigation (evidence only, no verdict)

Finding: a DataNode that misses an NN rollback has its abandoned epoch snapshotted by the
next upgrade, so the next rollback throws at `BlockPoolSliceStorage.java:621`.
Source: model checking (`MC_hunt_S1_dn_outage.cfg`, CE `spec/output/MC_hunt_S1_bfs.out`, 30 states,
invariant `TargetSafe`). Target (`target.yaml`): `BlockPoolSliceStorage.doRollback(StorageDirectory,
NamespaceInfo)`, line 621, throws `InconsistentFSStateException`, guard
`!(prevInfo.getLayoutVersion() >= DataNodeLayoutVersion.getCurrentLayoutVersion() && prevInfo.getCTime() <= nsInfo.getCTime())`.

All line numbers are for the pinned tree, `base_commit` 734dd8a67cd. I read them with `git show HEAD:<path>`
because the checkout carries the harness's line-preserving trace instrumentation: 35+/35- lines, with
hooks that call through and rethrow.

Persistent-findings lookup: `specula findings --work <out> lookup --query BlockPoolSliceStorage --query doRollback
--query TargetSafe --query InconsistentFSStateException` returned `[]`. `persistent-findings-context.json` has
`previous: null`, so there are no prior records.

## Step 1 — Code audit

### Cited code (pristine)
- `BlockPoolSliceStorage.doRollback` BPSS:603-645. It reads `previous/VERSION` into `prevInfo` (611-612). If
  `prevInfo.LV < softwareLV` or `prevInfo.cTime > nsInfo.cTime`, it throws `InconsistentFSStateException`.
  The `throw` statement spans 621-626.
- `BlockPoolSliceStorage.doTransition` BPSS:369-425.
  - ROLLBACK with `previous` present: `doRollback` (375-379).
  - `readProperties`, then a regular start if LV and cTime match (404-407).
  - **Upgrade if `this.cTime < nsInfo.cTime`** (414-417).
  - Throws "is newer than the namespace state" if `cTime > nsInfo.cTime` (419-424).
- `BlockPoolSliceStorage.doUpgrade` BPSS:445-519.
  - **Deletes any existing `<bp>/previous`** with no check of what it holds (477-480).
  - Renames `current` to `previous.tmp` (484-486), hard-links the blocks, and writes `cTime = nsInfo.cTime` (512-513).
  - Renames `previous.tmp` to `previous` (515-517).
- `DataStorage.loadBlockPoolSliceStorage` DS:450-501 catches a per-volume `IOException` from
  `bpStorage.recoverTransitionRead` and logs "Failed to add storage directory {} for block pool {}" (473-476).
  `addStorageLocations` (382-401) returns the BP success list. `DataStorage.recoverTransitionRead` (564-568) throws
  "All specified directories have failed to load." when that list is empty.
- DN-level `DataStorage.doTransition` DS:719-780 only compares LV. With the same software it is a regular start, and
  ROLLBACK without a DN-level `previous` just rewrites LV (DS:919-933). So only the **block-pool** level carries cTime.
- NN: `FSImage.checkUpgrade` FSImage:423-433 refuses an upgrade only if an **NN** `previous` exists.
  `FSImage.doUpgrade` FSImage:455-465 sets `storage.cTime = now()`. The NN rollback is a standalone command
  (`NameNode.doRollback`). `FSImage.recoverTransitionRead` FSImage:333-335 asserts that the NN never *starts* with ROLLBACK.

### Call chain (public entry → target)
DataNode `-rollback` start (`start-dfs.sh -rollback` / `hdfs datanode -rollback`, parsed at DataNode.java:3434-3435):
- `BPServiceActor.run`
- → `connectToNNAndHandshake`
- → `BPOfferService.verifyAndSetNamespaceInfo` (BPOS:382-415)
- → `DataNode.initBlockPool` (DN:2185-2199)
- → `initStorage` (DN:2251-2263)
- → `DataStorage.recoverTransitionRead` (DS:564-567)
- → `addStorageLocations` → `loadBlockPoolSliceStorage` (DS:464-465)
- → `BlockPoolSliceStorage.recoverTransitionRead` → `loadBpStorageDirectories` → `loadStorageDirectory`
- → `doTransition` (BPSS:375-379)
- → **`doRollback` (BPSS:621)**.

The same chain with REGULAR reaches `doUpgrade` via BPSS:414-417. Both are normal, reachable startup paths.

### Consumer-side handling (what a failing throw does)
- DS:473-476 logs and drops the volume. If all volumes fail, DS:566-567 throws.
- `verifyAndSetNamespaceInfo` resets nsInfo (BPOS:404-409), so `BPOfferService.shouldRetryInit` (BPOS:860-867) is false.
- `BPServiceActor.run` then logs "Initialization failed for ... Exiting." and the actor ends (BPSA:910-922, 943-945).
- The DN never registers for that block pool. Its replicas are not reported, so after the rollback the NN cannot reach
  its safe-mode block threshold for those blocks.

### Trigger scenario (from the CE, mapped to real operations)
1. **States 1-9.** The cluster is at c0. The NN is started with `-upgrade` (cTime c1 = now()). dn0 starts REGULAR, and
   BPSS:414-417 upgrades its BP storage to `current = c1`, `previous = c0`.
2. **States 10-12.** The cluster stops. The operator runs `hdfs namenode -rollback`, which sets NN `current = c0`
   and removes the NN `previous`.
3. **States 13-14.** dn0 is out of service (CE fault `MCDNOutage`) for the whole rollback window, so it is never started
   with `-rollback`. Its volumes keep `current = c1`, `previous = c0`.
4. **State 15.** The operator re-upgrades (`-upgrade`). This is allowed because no NN `previous` exists
   (FSImage:423-433). cTime c2 = now() > c1.
5. **States 16-23.** dn0 is repaired and started REGULAR.
   - `c1 < c2` at BPSS:414-415 leads to `doUpgrade`.
   - `doUpgrade` deletes the valid c0 snapshot (BPSS:478-480) and snapshots the abandoned c1 `current` as `previous`
     (486, 512-517).
   - dn0 registers normally. Nothing reports the problem.
6. **States 24-27.** The cluster stops. `hdfs namenode -rollback` returns the NN to c0, because its `previous` is the
   c0 image saved at step 4. The NN is started.
7. **States 28-30.** dn0 starts with `-rollback`. The handshake gives `nsInfo.cTime = c0`. `doRollback` reads
   `previous` cTime c1 > c0 and **throws at BPSS:621** on each volume. The block pool fails to initialise
   (DS:566-567).

### Safeguards encountered (recorded, not dismissed)
- **BPSS:419-424.** If dn0 were started REGULAR *before* the re-upgrade, this check would refuse it ("newer than the
  namespace state"), and a late `-rollback` would still work because `previous = c0 <= c0`. The re-upgrade moves the
  NN cTime past dn0's stale c1. dn0's stale `current` then looks *upgradable* (`c1 < c2`), so it passes this safeguard.
- **NN-side `checkUpgrade` (FSImage:423-433).** It refuses an upgrade with an un-finalized NN `previous`. The DN BP
  upgrade has no equivalent: it deletes the DN `previous` (BPSS:478-480).
- **Registration ID (`NameNodeRpcServer.verifyRequest`).** It includes cTime. It matches after the silent BP upgrade,
  so it does not catch the problem.
- I found no NN→DN message that tells a DN its last un-finalized upgrade was rolled back.

## Step 2 — Developer knowledge (in-code evidence only for now)
Adhoc Shared Rule 2 defers the tracker and git-history search about the target until after the reproduction verdict.
That search is recorded at the end of this file.
- BPSS:614-617 comment: "We allow rollback to a state, which is either consistent with the namespace state or can be
  further upgraded to it. In another word, we can only roll back when ( storedLV >= software LV) && (
  DN.previousCTime <= NN.ctime)". So the throw is the intended reaction *to that state*.
- BPSS:427-439 javadoc on `doUpgrade`: "If <SD>/current/<bpid>/previous exists then delete it". Deleting an existing
  previous on upgrade is deliberate. It assumes that previous is disposable.
- FSImage:424-425 comment: "Upgrade or rolling upgrade is allowed only if there are no previous fs states in any of the
  local directories". This is the NN's own stricter rule.
- Tests:
  - `TestDFSRollback#testRollback` "DataNode rollback with newer fsscTime in previous" (TestDFSRollback:269-292)
    asserts the block pool **fails to start** when the DN `previous` cTime is newer than the NN. The state is built by
    hand-writing VERSION files (`UpgradeUtilities.createDataNodeVersionFile`, cTime = Long.MAX_VALUE), not through
    real operations.
  - `TestDFSUpgrade` "DataNode upgrade with existing previous dir" (TestDFSUpgrade:275-284) expects a REGULAR DN
    upgrade over an existing previous to succeed.
  - `TestDFSUpgrade` "NameNode upgrade with existing previous dir" (269-273) expects the NN to refuse.
  - No test covers a DN that misses a rollback followed by a re-upgrade.

## Step 3 — Known-status / pre-filter
The finding is MC-sourced with an actual counterexample, so the code-review × known drop does not apply. It goes to
Phase 2. The Novelty search runs after the verdict, per adhoc Shared Rule 2.

---

## Phase 2 — Reproduction record (summary; details are in repro/)

**Escalation level reached: 0 (pure black box).** The test uses only:
- the real startup options: NN `-upgrade`, DN REGULAR / `-rollback`;
- the real `hdfs namenode -rollback` implementation (`NameNode.doRollback(conf,false)`), as the workload test does;
- the CE's single fault, a DataNode outage during the rollback window, realised by not starting the DN.

There are no failpoints, no injected state, and no source edits. The main sources were verified pristine at 734dd8a67cd before each run. The harness instrumentation was backed up to `confirmation/MC-1/instrumentation-backup/` and removed from this worktree's checkout only.

Files:
- Test: `repro/test_bugMC-1_dn_missed_rollback_reupgrade.java`, installed as `org.apache.hadoop.hdfs.SpeculaAdhocMC1DnMissedRollbackTest`, a variant of `TestDFSRollback#testRollback`.
- Driver: `repro/test_bugMC-1_dn_missed_rollback_reupgrade.sh`.
- Final run: `.run.txt`, `.excerpt.txt`, `.output.txt.gz`.
- Earlier runs: `run1-*`, `run2-*`, `run3-*`.

Runs:
- 4 runs. The target fired in **4/4**.
- Runs 1-2 failed only on later assertions of my own, which I then corrected:
  - run 1 counted log records, but each throw is logged at both BPSS:230 and DS:474;
  - run 2 asserted safe mode, but one block makes the 0.999 threshold truncate to 0.
- Runs 3-4: `Tests run: 2, Failures: 0`.

Result:
- **Target thrown.** `org.apache.hadoop.hdfs.server.common.InconsistentFSStateException`, top frame
  `BlockPoolSliceStorage.doRollback(BlockPoolSliceStorage.java:626)`, thrown once per volume.
  - The message reads "Datanode previous state: LV = -57 CTime = c1 is newer than the namespace state: ... CTime = c0".
  - javap `LineNumberTable` for `doRollback`: `new InconsistentFSStateException` at pc 56 is line 621. `invokespecial <init>` (pc 86) and `athrow` (pc 89) fall in the line-626 range (pc 78-89). So the frame `:626` is the `throw` statement that begins at BPSS:621.
- **CE match.** The on-disk cTimes logged at each step match the CE values: c0, c1, c0, c2, c0.
  - After the first upgrade, dn0's BP is `current=c1, previous=c0`.
  - It stays that way through the missed rollback.
  - After the re-upgrade, dn0's BP is `current=c2, previous=c1`. The NN at that point is `current=c2, previous=c0`.
  - The final `-rollback` start gets `nsInfo.cTime=c0`.
- **Consumer outcomes.**
  - BPServiceActor logs "Initialization failed for Block pool <registering> ... Exiting." with `IOException: All specified directories have failed to load.` (DS:567), then "Ending block pool service".
  - NN live DataNodes = 0.
  - The client read of `/mc1/written-at-c0`, which the rolled-back namespace still lists, fails with `BlockMissingException ... No live nodes contain current block`.
- **Permanence.**
  - dn0 restarted REGULAR is refused at BPSS:421-424 (frame `doTransition(BlockPoolSliceStorage.java:424)`: "CTime = c2 is newer than the namespace state").
  - dn0 restarted with `-rollback` throws at BPSS:621 again.
  - On disk, dn0 stays at `current=c2, previous=c1`. The c0 snapshot no longer exists on dn0.
- **Negative control.** Same sequence, but dn0 takes part in the first rollback. The final `-rollback` start succeeds, no target exception is thrown, and the client reads all 8192 bytes of F0.

## Novelty search (after the verdict was settled; it sets only the Novelty field)
Every query is listed below. Raw results are in `confirmation/MC-1/novelty/`.
- **Local git** (read-only, no checkout):
  - `git log 734dd8a67cd -- BlockPoolSliceStorage.java`: 40 commits, none about this mechanism.
  - `git blame` at base: the delete-previous code BPSS:477-480 and guard line 620 date back to the original federation BP-storage commit a196766ea077; line 621 comes from ffbe9e5972bf.
  - `git log -i --grep=rollback trunk -- server/datanode`: HDFS-6005, HDFS-5966, HDFS-3970, all different.
  - `git log 734dd8a67cd..trunk` on BPSS / DataStorage / FSImage / Storage: 167 newer commits, up to 2026-10-24. Only b15adbcfa3b touches these files: a Thread/SubjectInheritingThread revert, unrelated.
  - trunk BPSS still contains `deleteDir(bpPrevDir)` (478-479), the `this.cTime < nsInfo.getCTime()` upgrade path (415), and the same guard (622).
  - Side note: `git blame` set off a benign background `git gc --auto` on the shared repo. Later calls used `-c gc.auto=0`.
- **Apache JIRA REST, project HDFS** (`jira-queries.json`, `jira-queries-2.json`):
  - q1 `text ~ "\"Cannot rollback to a newer state\""` returned 0 hits.
  - q2 BlockPoolSliceStorage+rollback (15), q3 summary rollback+datanode (3), q4 rollback+previous+upgrade+datanode+down (20), q5 doUpgrade+previous+delete (5), q6 summary previous+upgrade (1), q7 "newer than the namespace state" (1: HDFS-14311), q8 rollback+re-upgrade (16).
  - q9 InconsistentFSStateException+datanode+rollback (2), q10 datanode+"not rolled back" (3), q11 stale+previous+datanode+upgrade+rollback (6), q12 "upgrade again"+rollback (2), q13 rollback+datanode created ≥ 2024 (2), q14 "previous directory"+datanode+rollback (24).
  - I read the closest candidates (`jira-candidates*.json`). All describe different mechanisms:
    - HDFS-6137 (Open), HDFS-5526, HDFS-6339, HDFS-3028: layout-version or IncorrectVersionException problems.
    - HDFS-9096: rolling-upgrade NN layout version.
    - HDFS-14311: multi-threaded layoutVersion race.
    - HDFS-7231 (Won't Fix): rolling upgrade interfering with an un-finalized upgrade.
    - HDFS-8127: HA failover makes DNs finalize.
    - HDFS-7646: truncate touching previous/.
  - None describes a DN that missed an NN rollback whose abandoned epoch is then snapshotted by a re-upgrade, making the next rollback fail.
- **GitHub PR search, apache/hadoop**:
  - "BlockPoolSliceStorage rollback": 0.
  - "datanode rollback previous upgrade": 1 unrelated (#5451).
  - "\"Cannot rollback to a newer state\"": 0.
- **Web search** ("HDFS datanode missed rollback then upgrade again "Cannot rollback to a newer state" block pool previous cTime"): only generic rolling-upgrade documentation.

Conclusion: **NEW**. The search found no report of this mechanism at this site.
