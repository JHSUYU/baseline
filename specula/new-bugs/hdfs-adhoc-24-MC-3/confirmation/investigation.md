# MC-3 — Phase 1 investigation (evidence only)

Finding: a stale rolling-upgrade (RU) marker plus a replayed, finalized RU status
delete a regular upgrade's rollback snapshot (`previous/`); the later documented
rollback then throws at the target `BlockPoolSliceStorage.java:421`.

- Source: MC (actual TargetSafe counterexample: `spec/output/MC_hunt_ru_marker_bfs.out`, 83 states, BFS).
- Tree: worktree at `734dd8a67cd` (== target `base_commit`), `git status` clean.
- Persistent-findings lookup (`specula findings lookup --query BlockPoolSliceStorage --query clearRollingUpgradeMarkers --query TargetSafe --query doTransition`): `[]` (no prior record; context has `previous: null`).

## Step 1 — Code audit

### Cited sites (all re-read in the pinned worktree)

| Site | What it does |
|---|---|
| `BlockPoolSliceStorage.java:73-82` | javadoc + `ROLLING_UPGRADE_MARKER_FILE = "RollingUpgradeInProgress"`, one marker per `<vol>/current/<bpid>/` |
| `BlockPoolSliceStorage.java:110-111` | `private static Set<String> storagesWith(out)RollingUpgradeMarker` — process-wide caches, re-created by every BPSS constructor (L119-122, L127-130) |
| `BlockPoolSliceStorage.java:863-881` `setRollingUpgradeMarkers` | creates the marker file on every BP root (one loop over all DN storage dirs) |
| `BlockPoolSliceStorage.java:889-909` `clearRollingUpgradeMarkers` | for each BP root not cached as "without marker": if the marker file exists → `doFinalize(sd.getCurrentDir())` (L900), then delete the marker |
| `BlockPoolSliceStorage.java:651-689` `doFinalize` | if `<bpRoot>/previous` exists → rename to `finalized.tmp` (L670) and delete it on a daemon thread. No check of *which* upgrade created `previous/`, of the NN's upgrade state, or of the marker's age |
| `BlockPoolSliceStorage.java:369-425` `doTransition` | ROLLBACK with `previous/` → `doRollback`; ROLLBACK without `previous/` → only restore trash (L382-388); then `readProperties`; LV equal & cTime equal → regular (L404-407); LV newer or cTime older → upgrade (L414-417); else **throw IOException at L421** ("Datanode state ... is newer than the namespace state") |
| `BlockPoolSliceStorage.java:603-645` `doRollback` | returns immediately if `previous/` does not exist |
| `BPServiceActor.java:742-743` | every heartbeat response from the ACTIVE NN → `handleRollingUpgradeStatus(resp)` (L656) → `bpos.signalRollingUpgrade(status)` |
| `BPOfferService.java:554-567` `signalRollingUpgrade` | not finalized → `enableTrash` + `setRollingUpgradeMarker`; finalized → `clearTrash` + `clearRollingUpgradeMarker` |
| `DataStorage.java:192-198` | delegates marker set/clear to the BPSS with **all** DN storage dirs |
| `FSNamesystem.java:4511-4512` `handleHeartbeat` | `new HeartbeatResponse(cmds, haState, rollingUpgradeInfo, ...)` — the in-memory `rollingUpgradeInfo`, finalized or not, goes in every heartbeat |
| `FSNamesystem.java:7727-7729` `isRollingUpgrade` | `rollingUpgradeInfo != null && !rollingUpgradeInfo.isFinalized()` |
| `FSNamesystem.java:7792-7798` `checkRollingUpgrade` | throws only if `isRollingUpgrade()`; a *finalized* info does not block |
| `FSImage.java:455-462` `doUpgrade` | `loadFSImage(target, UPGRADE)` (replays edits) then `target.checkRollingUpgrade("upgrade namenode")` → passes with finalized info; new cTime = now() (L465); `saveFSImageInAllDirs` does not clear `rollingUpgradeInfo` |
| `FSNamesystem.java:1298-1300` | `rollingUpgradeInfo = null` only on `-rollingUpgrade rollback` startup |
| `FSEditLogLoader.java:892-918` | replay of `OP_ROLLING_UPGRADE_START` → `startRollingUpgradeInternal`; `OP_ROLLING_UPGRADE_FINALIZE` → `finalizeRollingUpgradeInternal` ⇒ after any NN restart before a post-finalize checkpoint, `rollingUpgradeInfo` is re-created **finalized** |
| `DataStorage.java:450-505` `loadBlockPoolSliceStorage` | catches the BP-level IOException (L473-476, WARN "Failed to add storage directory ... for block pool"), the volume is dropped for the BP; `recoverTransitionRead` L564-568 throws "All specified directories have failed to load." if none succeeds |
| `BPServiceActor.java:909-921`, `BPOfferService.java:860-867` | BP init failure → `Initialization failed for ...`, retry every 5 s (fails again each time) |
| `NameNode.java:1628-1648` `doRollback`, `:1879-1881` | what `hdfs namenode -rollback` runs (the CLI passes `isConfirmationNeeded=true`; only the Y/N prompt differs) |

### Call chain (entry points → target)

1. Operator: `hdfs dfsadmin -safemode enter`, `hdfs dfsadmin -rollingUpgrade prepare` → `FSNamesystem.startRollingUpgrade` (non-HA: rollback image, leave safemode, log START).
2. DN heartbeat → `BPServiceActor.offerService` L742 → `handleRollingUpgradeStatus` → `BPOfferService.signalRollingUpgrade` L560-562 → `DataStorage.setRollingUpgradeMarker` → `BPSS.setRollingUpgradeMarkers` → marker file on every volume.
3. DN is down (crash / maintenance / RU restart) when the operator runs `hdfs dfsadmin -rollingUpgrade finalize` → NN logs FINALIZE. Nothing else ever removes the marker (grep: only `clearRollingUpgradeMarkers` touches it, reached only from the heartbeat path).
4. Operator does a regular (non-rolling) upgrade: NN restarted with `-upgrade` before any checkpoint post-finalize → `FSImage.doUpgrade` → replay START+FINALIZE → finalized `rollingUpgradeInfo`; `checkRollingUpgrade` passes; NN cTime := now().
5. DN restarted (REGULAR) → `BPOfferService.verifyAndSetNamespaceInfo` → `DataNode.initBlockPool` → `DataStorage.recoverTransitionRead` → `BPSS.recoverTransitionRead` → `doTransition` L414-417 (`cTime < nsInfo.cTime`) → `doUpgrade` → `previous/` created on every volume (the regular upgrade's rollback snapshot).
6. First heartbeat after registration carries the finalized RU status (FSNamesystem L4511) → `signalRollingUpgrade` L564-565 → `clearRollingUpgradeMarkers` → marker present → `doFinalize` L900 → `previous/` renamed to `finalized.tmp` and deleted — while the NN's regular upgrade is still un-finalized.
7. Documented rollback (HdfsUserGuide.md:322-328): stop cluster, `hdfs namenode -rollback`, `start-dfs.sh -rollback` → DN `-rollback` → `doTransition`: no `previous/` → only trash restore (L382-388) → `readProperties` → LV equal, DN cTime (upgrade) > NN cTime (rolled back) → **L421 throws**.

Reachability: every step is a public operator command or a normal DN/NN restart; no failpoints. Preconditions: non-HA NN (or no checkpoint between RU finalize and the `-upgrade` restart, so START/FINALIZE are replayed); a DN that was down across the RU finalize and is restarted after the NN `-upgrade`.

### Mapping to the counterexample (83 states)
S2 DN start; S3 NN RU start; S26 `SignalRollingUpgrade(v1)` (marker); S27 NN RU finalize; S28 DN stop; S29 NN `-upgrade` (nnC 1→2, RU info finalized via replay); S30–S67 DN start, both volumes upgraded (`prev` = c1); S69 `SignalRollingUpgrade(v1)` finalized → `marker v1 := FALSE`, `prev v1` deleted, `finTmp v1`; S70 DN stop; S71 NN rollback (nnC 2→1); S72 DN start ROLLBACK; S75–S76 no `previous/` → trash restore; S80 `c405 = 2` vs `nsC = 1`; S83 `TargetCheck(v1)` → `err = "B421"`.
Model granularity note: the CE marks only v1 (per-volume action); the code marks all volumes in one call (L866-880), so in the real system every volume is affected — same mechanism, larger blast radius.

### Safeguards encountered (recorded, to be tested in Phase 2)
- `checkRollingUpgrade` (FSNamesystem L7792) blocks `-upgrade` only while an RU is *in progress*, not after finalize.
- `checkUpgrade` (FSImage) only checks NN `previous/`.
- `doTransition` ROLLBACK guard (L376-388) handles "no previous" as an RU rollback (trash restore) — no detection of a lost regular-upgrade snapshot.
- `clearRollingUpgradeMarkers` caches (`storagesWithoutRollingUpgradeMarker`) are reset on DN restart (static field re-created in the constructor), so they do not suppress the stale-marker check.
- A post-finalize checkpoint (SecondaryNameNode / saveNamespace) would drop the finalized info from the next restart; not present in the trigger scenario (non-HA, no checkpoint yet).

## Step 2 — Developer knowledge (code/docs/tests only; tracker + history deferred)

Per adhoc-coordination Shared Rule 2 (Phase 4), the issue-tracker and git-history search is done **after** the reproduction verdict is settled and may only set Novelty. Queries are logged in the "Novelty search" section below.

- `BlockPoolSliceStorage.java:73-81` (verbatim): "A marker file that is created on each root directory if a rolling upgrade is in progress. The NN does not inform the DN when a rolling upgrade is finalized. All the DN can infer is whether or not a rolling upgrade is currently in progress. When the rolling upgrade is not in progress: 1. If the marker file is present, then a rolling upgrade just completed. If a 'previous' directory exists, it can be deleted now. 2. If the marker file is absent, then a regular upgrade may be in progress. Do not delete the 'previous' directory."
  → Stated intent: the marker exists precisely so that a regular upgrade's `previous/` is **not** deleted. Assumption "marker present ⇒ a rolling upgrade just completed" is what a stale marker breaks.
- `FSEditLogLoader.java:906-908` (verbatim): "Only do it when NN is actually doing rolling upgrade. We can get FINALIZE without corresponding START, if NN is restarted before this op is consumed and a new checkpoint is created." → developers know START/FINALIZE are replayed across restarts.
- `DataStorage.java:168-172`: "Even if trash is enabled by the caller, it is superseded by the 'previous' directory if a layout upgrade is in progress."
- `HdfsUserGuide.md:304-328`: regular upgrade keeps one backup until `-finalizeUpgrade`; rollback = `hdfs namenode -rollback` + `start-dfs.sh -rollback`. "HDFS allows administrators to go back to earlier version of Hadoop and rollback the cluster to the state it was in before the upgrade."
- `HdfsRollingUpgrade.md:144-146`: "An upgrade can be terminated by either finalize, downgrade or rollback." (about the RU itself; the RU here was finalized, the later regular upgrade was not).
- Tests: `TestDataNodeRollingUpgrade#testDatanodeRUwithRegularUpgrade` (L231-249) runs RU+finalize **with the DN up**, then NN `-upgrade`, DN restart, `finalizeUpgrade`. No test covers a DN that was down across the RU finalize, nor a rollback after the regular upgrade. `TestDFSUpgrade#testUpgrade` ("DataNode upgrade with newer fsscTime in current") reaches L421 only by writing a VERSION file with `cTime = Long.MAX_VALUE` (direct operand injection) and expects the BP to fail — developers treat L421 as "must shutdown".

## Step 3 — Known-status / pre-filter
MC-sourced with an actual counterexample → the code-review × known drop does not apply; proceed to Phase 2. Novelty is decided by the post-verdict search below.

## Phase 2 pointer
Reproduction: `repro/test_bugMC-3_ru_marker_rollback.sh` + `repro/test_bugMC-3_SpeculaAdhocMC3Test.java`; output `repro/MC-3.run.out` (3/3 runs: Level-0 and CE-order variants hit the target throw, control clean). Verdict settled as REPRODUCED **before** the search below.

## Novelty search (post-verdict; sets Novelty only — Shared Rule 2)
All queries run 2026-10-29 after the reproduction verdict was settled.

| # | Where | Query | Result |
|---|---|---|---|
| 1 | Apache JIRA REST | `project = HDFS AND text ~ "RollingUpgradeInProgress"` | 0 issues |
| 2 | Apache JIRA REST | `project = HDFS AND text ~ "rolling upgrade marker"` | 12 issues; NN edit-log-marker work (HDFS-5645/5869/6019/5920/5835/5963/5754/5535/7934, 2013-15), HDFS-6981 (DN marker origin, fixed 2.6.0), HDFS-8893 (open: DNs with failed volumes stop serving during RU — different mechanism), HDFS-12348 (trash during RU — different) |
| 3 | Apache JIRA REST | `text ~ "rolling upgrade" AND text ~ "previous" AND text ~ "finalize" AND text ~ "marker"` | HDFS-5869, 5920, 6981, 5754, 5138, 1073 — none about this mechanism |
| 4 | Apache JIRA REST | `text ~ "is newer than the namespace state"` (target message) | HDFS-16890 (RBF state refresh), HDFS-14311 (multi-thread layoutVersion conflict while loading BP storage — different mechanism), HDFS-4477 (SNN tokens) |
| 5 | Apache JIRA REST | `text ~ "regular upgrade" AND text ~ "rolling upgrade" AND text ~ "datanode"` | 19 issues (HDFS-17396, 14305, 13532, 10301, 8791, 8551, 7668, 7645, 7443, 7056, 7035, 6981, 6482, 5924, 5907, 5535, 5223, 5138, 4015) — none reports a stale marker finalizing a regular upgrade |
| 6 | Apache JIRA REST | `summary ~ "rolling upgrade" AND summary ~ "datanode"` | HDFS-17164, 16752, 15569, 9752, 7932, 6800, 6198, 5446 — none matches |
| 7 | Apache JIRA REST | `summary ~ "rolling upgrade" AND (summary ~ finalize OR …)` | HTTP 400 (bad JQL); superseded by #5/#6 |
| 8 | JIRA HDFS-6981 comments | read | Design intent (Arpit Agarwal): "When rolling upgrade is no longer signaled by NN, 'previous' is cleaned up only if the marker file is present. Else a regular upgrade is in progress and 'previous' is left alone." No discussion of a DN that missed the finalize. |
| 9 | JIRA HDFS-7645 comments (fixed 2.7.2/2.8.0/3.0.0-alpha1; introduced finalized status in heartbeats) | read | Vinayakumar B: "After restart RollingUpgradeStatus will be non-null after finalize only till NN is restarted." (the repro shows the status is re-created by edit replay after a restart without checkpoint). Arpit Agarwal asked for a test of a regular upgrade right after RU completion → `testDatanodeRUwithRegularUpgrade` (DN up during finalize). No report of this defect. |
| 10 | GitHub search issues/PRs | `repo:apache/hadoop clearRollingUpgradeMarkers` | total_count 0 |
| 11 | GitHub search PRs | `repo:apache/hadoop is:pr "rolling upgrade" marker` (sorted by updated) | total_count 0 |
| 12 | GitHub search PRs | `repo:apache/hadoop is:pr RollingUpgradeInProgress` | total_count 0 |
| 13 | GitHub search PRs | `repo:apache/hadoop is:pr BlockPoolSliceStorage` (sorted by updated) | total_count 0 |
| 14 | GitHub commits API (trunk) | path `.../datanode/BlockPoolSliceStorage.java` | newest 62c86eaa0e5 2021-10-23 HADOOP-17970 (Guava cleanup); nothing marker-related since |
| 15 | GitHub commits API (trunk) | path `.../datanode/BPOfferService.java` | newest fb0519253d6 2024-05-11 HDFS-17488 (IBR NPE); nothing RU-related |
| 16 | Web search | "HDFS rolling upgrade marker RollingUpgradeInProgress deletes previous directory regular upgrade rollback datanode" | docs + Cloudera articles + HDFS-8551/6005/5920 — no report |
| 17 | local `git log -S clearRollingUpgradeMarkers` | stopped: the shared clone is a promisor (partial) clone and `-S` triggered per-blob lazy fetch + auto-pack; superseded by #14/#15 | — |

Outcome: no issue / PR / commit reports THIS mechanism (stale DN marker + replayed finalized RU status → `doFinalize` of a regular upgrade's `previous/` → rollback fails at L421). **Novelty: NEW.**
