# MC-1 investigation (Phase 1: evidence only)

Target: `BlockPoolSliceStorage.doTransition`, IOException at BPSS:422 (pinned tree `b0c5a8f9`).
Property: `TargetSafe == ~targetFired`. Source: MC (counterexample `spec/output/MC_hunt_s1a_workload_shape_bfs.out`, not opened here per the confirmation rules; the finding's own summary of it is used).

Line numbers below are from the clean pinned files (`git show HEAD:<file>`). The checked-out worktree carried
Specula trace instrumentation; it was saved to `instrumentation-aside/instrumentation.patch` and reverted
before the reproduction, so the tree that ran is the unmodified base commit (plus test files only).

## Step 1: Code audit

### Shared state
- `StorageInfo.java:46,49`: `public int layoutVersion; public long cTime;` are plain fields (not volatile,
  not guarded by a lock).
- `DataStorage.loadBlockPoolSliceStorage` (DS:445-488) uses **one** `BlockPoolSliceStorage bpStorage`
  per block pool (DS:449) for all volumes.

### Call chain (normal DataNode startup)
`BPServiceActor` handshake → `DataNode.initBlockPool` → `DataNode.initStorage` →
`DataStorage.recoverTransitionRead` (DS:551) → `addStorageLocations` (DS:382, synchronized, executor of
`min(dfs.datanode.parallel.volumes.load.threads.num, #dirs)` threads, DS:385-387) →
`loadBlockPoolSliceStorage` (DS:391) → loop over volumes (DS:452):
`bpStorage.recoverTransitionRead` (DS:456) → `loadBpStorageDirectories` → `loadStorageDirectory` →
`doTransition` (BPSS:367-426).

### What the code does
- Per volume, on the startup thread: `readProperties(sd)` (BPSS:389) loads that volume's VERSION into
  `this.layoutVersion` / `this.cTime`; then the guards re-read the fields:
  BPSS:405-406 (regular), BPSS:409 (LV > DNLV → restore trash), BPSS:415-416 (upgrade), else throw at
  **BPSS:422**.
- If upgrade: `doUpgrade` (BPSS:446) renames current→previous.tmp on the startup thread and, because
  `callables != null` at startup, **adds a callable** (BPSS:493-500). DS:463-464 submits it to the executor
  **before** the loop moves to the next volume.
- The callable runs `doUpgrade(name, …)` (BPSS:504-520): `linkAllBlocks` (509), then writes
  `this.layoutVersion = DNLV` (BPSS:510) and `this.cTime = nsInfo.getCTime()` (BPSS:513) on the **same**
  shared `bpStorage` object, on an executor thread, while the startup thread continues with the next
  volume's `doTransition`.

### Trigger scenario (path b, = the workload's shape)
1. NN started with `-upgrade` (new namespace cTime C1). DN has 2 dirs, BP VERSION = (DNLV, C0), C0 < C1.
2. Volume 1: `doTransition` → 416 true → `doUpgrade` → callable submitted (DS:464).
3. Volume 2 (startup thread): `readProperties` sets cTime=C0; 405-406: C0 != C1 → not regular; 409 false.
4. Volume 1's callable (executor thread) writes BPSS:510 (LV=DNLV) and BPSS:513 (cTime=C1).
5. Volume 2: 415-416: `DNLV > DNLV || C1 < C1` → false → **IOException at BPSS:422**
   ("Datanode state: LV = … CTime = C1 is newer than the namespace state …").
6. DS:467-469 catches it, logs `Failed to add storage directory … for block pool …`, and volume 2's block
   pool slice is not added to `success` (not upgraded, not loaded into bpStorage).

Path c (DN layout upgrade, dirs at (OLDLV, nsCTime)) is the same mechanism with the callable's BPSS:510 write
landing between 405/409 and 415; its window additionally contains `restoreBlockFilesFromTrash` + `LOG.info`
(BPSS:410-413), i.e. it is wider.

Side observation (not the target): if step 4 lands between BPSS:389 and the BPSS:405 read, volume 2
takes the "regular startup" branch and `loadStorageDirectory` writes volume 2's VERSION with cTime=C1
without performing its upgrade (no `previous/`). Recorded only.

### Reachability / safeguards
- Reachable in normal operation: any DN with ≥2 data dirs restarted after an NN `-upgrade` (or a DN layout
  upgrade). Default thread count = #dirs (DS:351), so parallel by default.
- No lock covers the fields: `addStorageLocations` is `synchronized` on DataStorage but the callable thread
  does not take it; nothing synchronizes `bpStorage` field accesses between threads.
- The window on path b is narrow (from the BPSS:406 read of cTime to the BPSS:416 read; only the BPSS:409 LV
  check and `nsInfo.getCTime()` call lie between), so a black-box run rarely hits it — the workload
  `TestAdhocWorkload7#run` passes.
- Downstream safeguard: DS:467 catches the IOException; DN keeps running with the volume's BP slice
  missing / un-upgraded. Nothing retries the volume during this startup.

## Step 2: Developer knowledge (code/comments/tests; no tracker search before the verdict — adhoc Shared Rule 2)
- Comment DS:292-295 / BPSS:174-177: "Each storage directory is treated individually. During startup some
  of them can upgrade or roll back while others could be up-to-date for the regular startup." — intent is
  per-directory independence, which the shared fields contradict.
- Comment BPSS:420-421: "layoutVersion == LAYOUT_VERSION && this.cTime > nsInfo.cTime — must shutdown":
  the throw is meant for a DN whose on-disk state is newer than the NN, not for a DN at C0 < C1.
- Tests: `TestDFSUpgrade`, `TestAdhocWorkload7` assert that every dir is upgraded and has `previous/` —
  i.e. developers expect the upgrade of all dirs to succeed in exactly this scenario.

## Step 3: Known-status (run AFTER the reproduction verdict was settled; it sets only the Novelty field)
Persistent-findings lookup (`specula findings lookup --query doTransition --query TargetSafe --query BlockPoolSliceStorage`): `[]`.
Local git history: the pinned checkout has one squashed commit (`b0c5a8f9 base`), so it says nothing.

Apache JIRA REST queries (`/rest/api/2/search`, ORDER BY updated DESC):
1. `project=HDFS AND text ~ "is newer than the namespace state"` → HDFS-16890, **HDFS-14311**, HDFS-4477
2. `project=HDFS AND text ~ "BlockPoolSliceStorage" AND text ~ "upgrade" AND text ~ "parallel"` → 13 hits incl. HDFS-8578 (introduced parallel upgrade), HDFS-9654, HDFS-15569
3. `project=HDFS AND summary ~ "upgrade" AND summary ~ "parallel"` → HDFS-9536, HDFS-8578, HDFS-270, HDFS-1826
4. `project=HDFS AND text ~ "BlockPoolSliceStorage" AND text ~ "race"` → incl. **HDFS-12800** (Open)
5. `project=HDFS AND text ~ "loadBlockPoolSliceStorage"` → HDFS-15569, HDFS-15416, **HDFS-14311**, HDFS-12800, HDFS-8578

Matches:
- **HDFS-14311** "Multi-threading conflict at layoutVersion when loading block pool storage"
  (https://issues.apache.org/jira/browse/HDFS-14311), Resolved/Fixed 2019-08-20, fix versions 2.8.6, 2.9.3,
  2.10.0, 3.1.3, 3.2.1, 3.3.0. Same mechanism at the same site: the callable submitted inside the per-volume
  loop of `DataStorage.loadBlockPoolSliceStorage` writes the shared `bpStorage.layoutVersion`, and a later
  volume's `doTransition` throws "Datanode state: LV = -57 CTime = 0 is newer than the namespace state" (their
  stack: `BlockPoolSliceStorage.doTransition`, `DataStorage.loadBlockPoolSliceStorage`). The report shows path c
  (DN layout upgrade 2.7.3→2.9.2). Path b (cTime) is the same race, and the same fix covers it. Fix commit
  4cb22cd867a9 (DataStorage.java only) collects the callables in a map and submits them **after** the loop.
  The pinned tree `b0c5a8f9` (3.3.0-SNAPSHOT) does **not** contain it: DS:463-464 still submit inside the loop.
  Comment by S. O'Donnell (2019-08-13): "I have tried to reproduce this in a unit test, but without success."
- HDFS-12800 (Open, 2017): same root race, a different consequence (volumes silently skip the layout upgrade
  instead of throwing). Related, not the target throw.

Novelty: **KNOWN (cite: HDFS-14311; fix-status: fixed upstream, absent at pinned base_commit)**.
MC-sourced, so the code-review × known pre-filter does not apply. The verdict is unchanged.
