# MC-2 investigation (Phase 1: evidence only)

Finding: *A disk formatted during an unfinalized upgrade cannot be rolled back and fails the documented rollback.*
Source: model checking. `MC_hunt_rollback_gap.cfg` violates `TargetSafe` (`spec/output/MC_hunt_rollback_gap_bfs.out`, 23 states, uses `MCDataNodeCrash`). The crash-free form is `spec/output/MC_char_rollback_gap_attach_bfs.out` (51 states). Its only fault is `MCAttachEmptyVolume`.
Target: `BlockPoolSliceStorage.doTransition`, the `throw new IOException(...)` at BlockPoolSliceStorage.java:421-424. Source tree pinned at `734dd8a67cd`; the worktree is clean at that commit.

Ad hoc rule (adhoc-coordination, Shared Rule 2): no git history or tracker lookup about the target happens until the reproduction verdict is settled. The novelty search is in the last section and was run after the verdict.

## Step 1: Code audit

### Cited code, as it reads at 734dd8a67cd

| Site | What it does |
|---|---|
| BlockPoolSliceStorage.java:154-171 (`loadStorageDirectory`) | `analyzeStorage` is called. In the `NOT_FORMATTED` case (L167) the slice is formatted with `format(sd, nsInfo)` (L171). `nsInfo` is the NamespaceInfo from this DataNode start's NameNode handshake. |
| BlockPoolSliceStorage.java:283-292 (`format`) | `clearDirectory()`, then `this.cTime = nsInfo.getCTime()` (L288), then `writeProperties`. No `previous/` is created. The slice's VERSION carries the NameNode's current cTime, which is the upgraded cTime while an upgrade is pending. |
| BlockPoolSliceStorage.java:181 → 369-425 (`doTransition`) | L375: `ROLLBACK && previous exists` leads to `doRollback`. L380-387: `ROLLBACK && !previous` only restores trash. L388: `readProperties(sd)` loads the slice's cTime into the **shared** BPSS fields. L404-407: regular startup if LV and cTime are equal. L414-418: upgrade if `cTime < nsInfo.cTime`. Otherwise L421-424 throws `IOException("Datanode state: LV = .. CTime = .. is newer than the namespace state: ..")`. The comment at L419-420 reads "layoutVersion == LAYOUT_VERSION && this.cTime > nsInfo.cTime // must shutdown". |
| BlockPoolSliceStorage.java:603-613 (`doRollback`) | "regular startup if previous dir does not exist": nothing is rolled back without `previous/`. |
| FSImage.java:465 (`doUpgrade`) | `storage.cTime = now(); // generate new cTime for the state`. |
| FSImage.java:521-568 (`doRollback`) | Renames the NameNode `previous` back to `current`. The NameNode cTime returns to the pre-upgrade value. |
| DataStorage.java:268-306 (`loadStorageDirectory`, format at L283-286) and DataStorage.java:571-582 (`format`) | DataNode-level format sets `cTime = 0` (L577). The DataNode-level storage is not affected by the NameNode cTime. Only the block-pool slice is. |
| DataStorage.java:450-501 (`loadBlockPoolSliceStorage`) | The catch at L473-476 logs "Failed to add storage directory {} for block pool {}". The slice is dropped and the start continues. |
| DataStorage.java:564-569 (`recoverTransitionRead`) | Throws only if *all* directories failed. |
| FsDatasetImpl.java:411-427 (`getInitialVolumeFailureInfos`) | Counts only DataNode-level failures. A block-pool-level failure is not counted against `dfs.datanode.failed.volumes.tolerated`, so it does not stop the DataNode. |
| DataNode.java:2073-2087 (`createBPRegistration`) | `storageInfo = storage.getBPStorage(bpid)`. The registration carries the shared BPSS cTime, which is the value left by the **last** slice that ran `readProperties`/`format`, including a slice that then failed. |
| NameNodeRpcServer.java:1626-1635 and 1777-1787 (`sendHeartbeat`, `verifyRequest`) | Registration ID `NS-<nsid>-<clusterid>-<cTime>` (Storage.java:1417-1421). On a mismatch the NameNode logs "Registration IDs mismatched" and throws `UnregisteredNodeException`. |
| BPServiceActor.java:791-799 (`offerService`) | `UnregisteredNodeException` leads to "is shutting down", `shouldServiceRun = false`. The block-pool actor exits. |

### Call chain (entry points to the target)

`DataNode` start (`hdfs datanode [-rollback]`, `MiniDFSCluster.startDataNodes(.., StartupOption, ..)`) → `BPServiceActor.run` → `connectToNNAndHandshake` → `BPOfferService.verifyAndSetNamespaceInfo` → `DataNode.initBlockPool` (L2185) → `initStorage` (L2251) → `DataStorage.recoverTransitionRead` (L564) → `addStorageLocations` → `loadBlockPoolSliceStorage` (L450) → `BlockPoolSliceStorage.recoverTransitionRead` → `loadBpStorageDirectories` → `loadStorageDirectory` → `doTransition` → L421.

Reachability: this is the normal DataNode start path, taken on every start for every volume. The target's guard needs `LV == current && slice cTime > nsInfo cTime`.

### Trigger scenario (normal operations; one environmental event)

1. The operator starts the NameNode with `-upgrade`, as `HdfsUserGuide.md` "Upgrade and Rollback" describes. The NameNode cTime changes from c0 to cUp = now().
2. The upgrade is not finalized. The guide says "may be after a few days of operation".
3. In that window a DataNode starts with an empty data directory: a newly added disk, or a failed disk replaced by an empty one. `NOT_FORMATTED` leads to `format`, so the slice gets cTime = cUp and no `previous/`. The populated disks are upgraded: they get `previous/` with c0, and `current` with cUp.
4. The operator rolls back as documented: stop the cluster, `hdfs namenode -rollback` (`NameNode.doRollback`, FSImage.java:521), then `start-dfs.sh -rollback`. That script starts the NameNode with no option and the DataNodes with `-rollback` (start-dfs.sh:69-72, 99, 111).
5. DataNode `-rollback` start. The populated slices are rolled back to c0. The empty-disk slice has no `previous/`: L380-387 restores the trash only, `readProperties` gives cTime cUp, and cUp is greater than c0, so the L421 throw fires.
6. If the empty-disk slice is the last one loaded (for example a new disk appended to `dfs.datanode.data.dir`), the shared BPSS keeps cTime cUp. The DataNode then registers with cUp, the NameNode rejects its heartbeat (`verifyRequest`), and the block-pool actor exits.

The counterexamples model step 3 as `MCAttachEmptyVolume` before `MCDataNodeStart`. The official counterexample also uses `MCDataNodeCrash` after v1 is formatted. It leaves the same on-disk state on v1 that the crash-free form leaves.

### Safeguards encountered (recorded, not judged)

- `DataStorage.loadBlockPoolSliceStorage` catches the exception (L473-476), so a single failed slice does not abort the DataNode start. The rest of the DataNode continues.
- `DataStorage.recoverTransitionRead` throws only when all volumes fail (L566-567).
- No code path deletes or re-formats a slice that has no `previous/` on rollback. `doRollback` returns when `previous/` is absent (L606-609).
- No code path resets the BPSS cTime after a failed slice before `createBPRegistration` reads it.

## Step 2: Developer knowledge (in-tree only; history and tracker deferred by Shared Rule 2)

- BlockPoolSliceStorage.java:419-420 comment: "layoutVersion == LAYOUT_VERSION && this.cTime > nsInfo.cTime // must shutdown". The developers treat this state as one that must stop the start, not as a recoverable condition.
- BlockPoolSliceStorage.java:351-360 javadoc: "Rollback if: previousLV >= LAYOUT_VERSION && prevCTime <= namenode.cTime". Rollback is defined only through `previous/`.
- BlockPoolSliceStorage.java:593-602 javadoc of `doRollback`: "Do nothing if previous directory does not exist."
- `HdfsUserGuide.md` lines 304-328 give the rollback procedure, and say "Most of the time, cluster works just fine. Once the new HDFS is considered working well (may be after a few days of operation), finalize the upgrade." Lines 340-356 ("DataNode Hot Swap Drive") document adding or replacing data volumes. Nothing in the guide forbids adding or replacing a disk during an unfinalized upgrade, and nothing says the rollback then needs a manual step.
- Tests:
  - `TestDFSRollback#testRollback` "DataNode rollback without existing previous dir" (TestDFSRollback.java:228-240) covers ROLLBACK without `previous/` and cTime below the NameNode's (that case becomes an upgrade). It asserts nothing about cTime above the NameNode's.
  - `TestDFSUpgrade#testUpgrade` "DataNode upgrade with newer fsscTime in current" (TestDFSUpgrade.java:303-318) reaches L421 only with a hand-written `cTime = Long.MAX_VALUE` VERSION fixture, and asserts that the block pool fails (`startBlockPoolShouldFail`).
  - No test covers a slice formatted during the upgrade window followed by a rollback.

## Step 3: Known status / precedent

The finding is MC-sourced with a real counterexample, so the code-review × known pre-filter does not apply and the finding goes to Phase 2. The tracker and history search for the Novelty field is deferred until after the verdict (Shared Rule 2); see the section below.

## Phase 2 result (recorded before any history or tracker lookup)

- Test: `repro/test_bugMC-2_rollback_gap.java` (class `org.apache.hadoop.hdfs.TestBugMC2RollbackGap`, module hadoop-hdfs, built from `TestDFSUpgrade#testUpgrade`'s "Normal DataNode upgrade" set-up). Runner: `repro/test_bugMC-2_rollback_gap.sh`.
- Escalation level 0. The test uses public startup options and the documented commands. The only fault is the counterexample's empty volume (`UpgradeUtilities.createEmptyDirs`). There are no failpoints, no sleeps in system code, no source patch, and no VERSION file written by the test.
- Run 2 (`logs/run2.log`): `Tests run: 4, Failures: 0, Errors: 0`. Run 1 (`logs/run1.log`) had already shown the target throw and the rejection in all three bug methods. Its two errors came from the test's own helper: `getBlockLocations` threw SafeModeException, which is itself the client-visible failure. The helper was fixed, and run 2 records that failure.
- Target frame: `java.io.IOException: Datanode state: LV = -57 CTime = <cUp> is newer than the namespace state: LV = -67 CTime = <c0>` at `BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)`. The javap line table (`logs/javap_doTransition.txt`) shows the frame belongs to the throw statement at L421-424: `new` at bci 339 is line 421, and the constructor `invokespecial` at bci 364 falls in the line-424 range.
- Verdict settled: **REPRODUCED**. The novelty search below ran after this point and may set the Novelty field only.

## Novelty search (run after the verdict; sets the Novelty field only)

Every query, in order:

| # | Where | Query | Result |
|---|---|---|---|
| 1 | `specula findings lookup` | `doTransition`, `TargetSafe`, "newer than the namespace state", `rollback` | `[]`: no prior records (the context has `previous: null`). |
| 2 | local git, pinned tree | `git log HEAD -- BlockPoolSliceStorage.java` filtered for rollback, format, ctime, upgrade, swap, volume, newer | Related but different fixes: HDFS-10457 (no auto-format when VERSION is missing), HDFS-6728 (format new hot-swap volumes), HDFS-6005 (simplify DataNode rollback; added the ROLLBACK-without-previous trash branch), HDFS-3970 (rollback VERSION storageType), HDFS-8578, HDFS-7645, HDFS-6981, HDFS-6800. None is about a slice formatted inside an unfinalized upgrade window. |
| 3 | local git | `git log -S "is newer than the namespace state" HEAD -- hadoop-hdfs/src/main/java` | Stopped before it finished, after more than 10 minutes over the full history; it listed no commit. Rows 9-17 cover reports and fixes. |
| 4 | web | `HDFS DataNode rollback "is newer than the namespace state" new disk formatted during upgrade` | HDFS-1969, HDFS-3958, Cloudera troubleshooting pages. None matches. |
| 5 | web | `HDFS JIRA datanode rollback fails volume added during upgrade no previous directory block pool cTime` | HDFS-6981, HDFS-15303, HDFS-6800, HDFS-7443, HDFS-7645, HDFS-12120, HDFS-2017, HDFS-5526, HDFS-8127, HDFS-7934. None matches. |
| 6 | web | `apache hadoop BlockPoolSliceStorage doTransition rollback previous directory does not exist newer cTime issue` | HDFS-3970, HDFS-7645, HDFS-5907. None matches. |
| 7 | web | `HDFS hot swap add volume during unfinalized upgrade then rollback datanode "Registration IDs mismatched"` | Rolling-upgrade docs, HDFS-5526, HDFS-7842. None matches. |
| 8 | web | `github apache hadoop pull request BlockPoolSliceStorage rollback format cTime HDFS` | HDFS-3970, HDFS-5907, HDFS-6005, PR #6583 (HDFS-17396, NameNode rollback image). None matches. |
| 9 | JIRA REST | `project=HDFS AND text~"\"newer than the namespace state\""` | 1 hit: HDFS-14311 (layoutVersion race when loading block-pool storage; hot-swap concurrency). Different mechanism. |
| 10 | JIRA REST | `project=HDFS AND text~"rollback" AND (text~"\"new volume\"" OR "\"new disk\"" OR "\"hot swap\"" OR "\"replaced disk\"" OR "\"empty volume\"")` | 2 hits: HDFS-10301, HDFS-6727. Neither matches. |
| 11 | JIRA REST | `project=HDFS AND summary~"rollback" ORDER BY updated DESC` | 33 issues. The closest were read in full: HDFS-2017 (NameNode-only partial upgrade, Not A Problem), HDFS-3028 and HDFS-6137 (layoutVersion of existing dirs), HDFS-6339 (HA rollback procedure). None matches. |
| 12 | JIRA REST | `project=HDFS AND text~"rollback" AND text~"cTime"` | 10 issues (HDFS-8791, 8578, 7645, 10644, 5840, 2983, 5138, 2843, 5526, 1365). None matches. |
| 13 | JIRA REST | `project=HDFS AND text~"upgrade" AND text~"format" AND (new volume, new disk, empty volume, new data dir, not formatted)` | 15 issues. HDFS-12800 (layout-upgrade race) and HDFS-15606 (NameNode not formatted) were read. None matches. |
| 14 | JIRA REST | `project=HDFS AND text~"rollback" AND ("previous directory" OR "previous dir") AND (volume OR disk)` | 8 issues (HDFS-8791, 7645, 7575, 6981, 6482, 5138, 5526, 5754). None matches. |
| 15 | GitHub API | commits on trunk touching BlockPoolSliceStorage.java (newest first) | Newest is 62c86eaa0e5 (2021-10-23), the same as the pinned tree's newest. |
| 16 | GitHub API | commits since 2026-05-13 (the pinned commit date) touching DataStorage.java, and the same for BlockPoolSliceStorage.java | Both empty: no fix has landed after the pinned commit. |
| 17 | GitHub API | PRs: `repo:apache/hadoop type:pr rollback in:title`, and `repo:apache/hadoop type:pr BlockPoolSliceStorage` | 4 PRs (#6583, #5135, #2162, #2161), all NameNode or JournalNode rollback. The second query returned 0. |
| 18 | Specula dataset | local `case-studies/` (empty); github.com/specula-org/specula-case-studies `systems/` | 79 systems, none is HDFS or Hadoop. |

Outcome: **Novelty: NEW**. No issue, PR, commit or dataset entry reports this mechanism at this site. The mechanism is a block-pool slice formatted with the upgraded cTime and no `previous/` during an unfinalized upgrade, which the documented rollback cannot roll back, so the target throws at BlockPoolSliceStorage.java:421 and the DataNode then registers with the failed slice's cTime.
