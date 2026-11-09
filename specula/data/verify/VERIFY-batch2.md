# Independent verification, batch 2 (HDFS 33, 40, 45, 49, 50; ZooKeeper 01, 03)

Reviewed 2026-11-05 against the unmodified source: apache/hadoop `734dd8a67cd` and apache/zookeeper `eab16599`.

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands; a realistic trigger, not designed, not a test artefact, not already reported; and severe.

**Result: no finding clears the bar. 0 KEEP-A, 0 KEEP-B.** The closest calls are listed right after the summary, so the owner can overrule them.

## How this was checked

- Source was read with `git show <commit>:<path>` from `src/hadoop` and `src/zookeeper`, not from the case trees. Citations below are at the commits above, and I read each one I cite as code. References to a report's own claims are marked as such.
- **No test was run.** Reproduction results (hit rates, frames, consequences) come from each run's `confirmed-bugs.md`. I read the finding text and log extracts there, not the repro test sources or the raw repro logs, so "Level 0" and "no hooks" are the reports' claims. For findings dropped on the trigger or on severity, that is enough, because the claim being rejected is taken at face value.
- Web: the Apache JIRA REST API and the GitHub search API both answered. Each negative below is bounded: JQL text search is coarse, and most hits were judged by title. For these I read the start of the description (up to about 1800 characters) and the last two comments, not the whole thread: HDFS-15357, 7269, 16987, 17399, 17954, 17960, 16804, 3122; ZOOKEEPER-2600, 1740, 2322, 3471, 1049, 2985.
- Trunk: `origin/trunk` (`f8422975702`, 2026-10-26) has no change to `DirectorySnapshottableFeature`, `DataStorage`, `FSDirAppendOp`, `FSEditLog` or `BlockManagerSafeMode`. `FSImage` differs only in a thread class. The `saveNamespace` TODO is still in trunk (`FSNamesystem` :5163). No ZooKeeper upstream ref is available locally, so ZooKeeper was not compared with master.
- Compared with `hdfs/VERIFIED-BUGS.md`, `zookeeper/VERIFIED-BUGS.md` and `VERIFY-batch1.md`. No finding duplicates a kept bug. Two groups match earlier drops: 20/MC-1..3 (a Java `assert` target) and 52/MC-2 (HDFS-17399).
- `hdfs-adhoc-48` is not covered: its run has no `adhoc-result.json` yet. Nothing under `/bulk/GraphChecker` was read.

## Summary

Findings marked FALSE POSITIVE by the run are listed for completeness; I did not re-derive them.

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| hdfs-33 / MC-2 | DROP, assert target | with `-da` no target exception: NPE at :261 instead; also needs two racing admin ops | high |
| hdfs-33 / MC-1 | DROP, assert target | same; controlled timing only, 0/140 without it | high |
| hdfs-33 / MC-3 | DROP, assert target and not severe | the leak ends with the stopping process | high |
| hdfs-40 / MC-4 | DROP, known | HDFS-15357, HDFS-7269 (false client corrupt reports) | high |
| hdfs-40 / CR-1 | DROP, known | HDFS-16987 same chain and message; storage-move route is a variant; clears at next FBR | high |
| hdfs-40 / MC-3 | DROP, not severe | real inconsistency, clears on re-replication; lasting only with no spare DN | medium-high |
| hdfs-40 / MC-1 | DROP, not severe | about 3 s after restart; 1-block namespace rounds the safe-mode threshold to 0 | high |
| hdfs-40 / MC-2 | DROP, by design | replica really gone; refusal is correct at default `min` | high |
| hdfs-40 / MC-5 | DROP, unrealistic | no firing without test hooks; assertions off; clears on IBR | medium-high |
| hdfs-40 / MC-6 | DROP, not severe | queued IBR clears the mark; HDFS-3122 closed Not A Problem | high |
| hdfs-40 / MC-7 | DROP, not severe | same as MC-6; 1 in 600 rounds | high |
| hdfs-40 / MC-8 | DROP, not severe | clears on IBR; forced by a hook, 0/440 without | high |
| hdfs-45 / MC-4 | DROP, unrealistic | severe, but stacked non-default config; reproduced only on an empty namespace; TODO at the site. **Closest call** | medium |
| hdfs-45 / MC-3 | DROP, unrealistic | off-label admin command on BackupNode/CheckpointNode | medium-high |
| hdfs-45 / MC-1 | DROP, not severe | needs an embedder calling `stop()`; one failed call | high |
| hdfs-45 / MC-2 | DROP, not severe | one failed save on a stopping BackupNode | high |
| hdfs-45 / MC-5 | DROP, not severe | node already stopping; test callers only; 0/40 unassisted | high |
| hdfs-45 / CR-2 | DROP, false positive | run's verdict | n/a |
| hdfs-49 / MC-1 | DROP, unrealistic | private flag flipped at a directory holding 65536 snapshots | high |
| hdfs-49 / MC-2 | DROP, unrealistic | same plus mixed config and a checkpoint window | high |
| hdfs-49 / MC-3 | DROP, unrealistic | same; at the default FS limit it dies at a different check, not the target | high |
| hdfs-49 / MC-4 | DROP, known | HDFS-17399 | high |
| hdfs-49 / MC-5 | DROP, known | HDFS-17399 | high |
| hdfs-49 / CR-1 | DROP, false positive | run's verdict; agrees with the audit of operands | n/a |
| hdfs-50 / MC-6 | DROP, unrealistic | as 49/MC-3 plus a client snapshot literally named `b#<id>` | high |
| hdfs-50 / MC-4 | DROP, known | HDFS-17399; adds consequences, not a new defect | high |
| hdfs-50 / MC-5 | DROP, known | HDFS-17399 | high |
| hdfs-50 / CR-1 | DROP, known | HDFS-17954, PR #8633 open | high |
| hdfs-50 / MC-2 | DROP, not severe | a wrong answer to one call; namespace correct. **Second-closest** | medium |
| hdfs-50 / MC-3 | DROP, not severe | same, narrower: needs checkpoint and restart within the retry budget | high |
| hdfs-50 / MC-1 | DROP, not severe | one retriable failure from a same-millisecond collision | high |
| hdfs-50 / CR-2 | DROP, false positive | run's verdict: documented result of disabling the retry cache | n/a |
| zk-01 / MC-1 | DROP, by design and not severe | lease semantics; needs a test-held stall; common 3-server case misses the target | medium-high |
| zk-01 / MC-3 | DROP, by design and not severe | session loss happens without the target firing; target is a symptom | medium-high |
| zk-01 / MC-4 | DROP, not severe | deadline really passed; client is told at once and recovers | high |
| zk-01 / MC-2 | DROP, masked | run's own verdict; I agree | high |
| zk-01 / CR-2 | DROP, masked and non-default | local sessions; wire-protocol client | high |
| zk-01 / CR-3 | DROP, false positive | run's verdict | n/a |
| zk-03 / MC-1 | DROP, masked | same gap as 01/MC-4; close commit expires the client | high |
| zk-03 / MC-2 | DROP, masked | results match a legal order | high |
| zk-03 / MC-3 | DROP, source patch and not severe | needs an injected sleep (Level 3); client retries. Its "known" label is wrong | high |
| zk-03 / CR-1 | DROP, false positive | run's verdict: hand-built packet | n/a |

Totals: 42 findings; 0 KEEP-A, 0 KEEP-B, 42 DROP (5 of them false positives by the run's own verdict).

## Closest calls, for the owner to overrule

1. **hdfs-45/MC-4.** The only finding here that passes bar 1 with a severe, lasting effect and no known report. It fails on realistic trigger, and that is a judgement. If stacked non-default settings count, this is the one KEEP-B candidate. See its section.
2. **hdfs-50/MC-2.** Default configuration, one lost reply, a final wrong answer. It fails bar 3 only because the namespace stays correct. If "client told a successful create failed" counts as a wrong result, it is a KEEP-B.
3. **hdfs-33/MC-2.** Lasting damage until a DataNode restart, but in production it is an NPE at :261, not the target. Same ruling as 20/MC-1..3.

## Root-cause groups

- **G1, replay obeys the replayer's own `ordered` flag** (`SnapshotManager`:511-547; the edit does not record the mode): 49/MC-1, MC-2, MC-3; 50/MC-6.
- **G2, `addSnapshot` inserts before the capture and never rolls back** (`DirectorySnapshottableFeature`:202-223), HDFS-17399: 49/MC-4, MC-5; 50/MC-4, MC-5. Same as the already dropped 52/MC-2.
- **G3, a `createSnapshot` re-send misses the retry cache**: 50/MC-2 (WebHDFS), MC-3 (entry lost), CR-1 (Router, HDFS-17954), CR-2 (cache disabled).
- **G4, stale reports mark a good replica corrupt** (`checkReplicaCorrupt` on a stale stamp): 40/MC-6, MC-7, CR-1 (HDFS-3122, HDFS-16987).
- **G5, a COMPLETE block with no location yet**: 40/MC-1, MC-8, and CR-1's one-storage route.
- **G6, hot-swap add races block-pool shutdown**: 33/MC-1, MC-2, MC-3; same family as HDFS-16804, at a different site.
- **G7, `NameNode.stop` is not atomic with respect to in-flight work**: 45/MC-1, MC-5 (near HDFS-12173), and 45/MC-2 on the BackupNode.
- **G8, ZooKeeper's poll-to-mark gap** (`SessionTrackerImpl`:167-169): 01/MC-4, 03/MC-1.
- **G9, the leader expires sessions on its own silence**: 01/MC-1, MC-3.

---

## hdfs-adhoc-33 (target `DataStorage.java`:259, a Java `assert`)

**The target is a Java `assert`** (`assert bpStorage != null;`, :259). With assertions off, as a production DataNode runs, it does not fire. Read: `build()` at :252-266 then dereferences at :261, and the reports show an NPE there. This fails bar 1 for all three findings and matches the ruling on 20/MC-1..3.

The race itself is real. `addVolume` (`FsDatasetImpl`:515-562) holds a `VolumeBuilder` from `prepareVolume` (:521) until `build()` (:559) with no lock, while `DataNode.shutdownBlockPool` removes the map entry (`DataNode`:2168). Only IOException reaches the cleanup at `FsDatasetImpl`:547-553, so an unchecked error skips `sd.unlock()`.

### MC-2: DROP

Federated DataNode, `refreshNamenodes` drops a nameservice during a disk add. The report's Level 0 hit 1/5 and 0/5 at uniform offsets, and 8/8 only when the second command was timed by watching for the new disk's pool directory. Worst case per the report (4/8 of its hits, by HashMap order): the surviving pool keeps a directory of the disk, and re-adding it fails until a DataNode restart.

Severity even if the assert counted: one disk on one DataNode, no data loss, other volumes serving, restart clears it. Two independent admin commands must overlap in tens of milliseconds. HDFS-16804 (Open, PR closed stale) is the same race family; the review the report quotes from HDFS-16785 accepted "one volume instance will be failed to add" but only as a clean failure.

This is worth filing on its own terms: `build()` applies partially. It just does not meet this bar.

### MC-1: DROP

Same site, triggered by a NameNode rejecting the DataNode. The summary says 140 attempts without controlled timing gave no hit. Dropped as MC-2.

### MC-3: DROP

DataNode stop during an add; 3 of 365 unassisted. In production the process exits, which releases the lock. The harm the report saw was on a JVM that outlives the DataNode, that is, a test.

---

## hdfs-adhoc-40 (target `FSDirAppendOp.java`:139)

Guard read at :137-141: a COMPLETE last block where `isSufficientlyReplicated` is false. `BlockManager.isSufficientlyReplicated` (:1727-1736) counts live replicas only, against `min(minReplication, numLiveDNs)`. The neighbouring COMMITTED branch (:132-136) throws a retriable exception; this one does not, despite saying "yet".

### MC-4: DROP, known

Mechanism confirmed: `reportBadBlocks` marks with `CORRUPTION_REPORTED` (`BlockManager`:1939-1941), and a good report only clears `GENSTAMP_MISMATCH` (:3823-3824). With every replica marked, the block is neither invalidated (:2003) nor counted live, so append throws.

**Known.** HDFS-15357 ("Do not trust bad block reports from clients", Open) and HDFS-7269 (Open) describe this with the same comment and the same workarounds, a NameNode failover or copying the file. Append is a consequence they do not name, not a different defect. The run rated this Critical and also labels it KNOWN; the two do not go together under this bar. Reads keep working and no data is lost.

### CR-1: DROP, known

Confirmed: `PendingDataNodeMessages.removeQueuedBlock` filters by storage (:130), while corrupt marks are per DataNode (`BlockManager`:1976). HDFS-16987 (Open, PR closed stale) has the same chain and the same exception text. The storage-move route is a new variant needing a held report, a Mover-style move and a failover. It clears at the next full report, 6 h by default. The report itself shows the one-storage route is just the "no location yet" case of MC-8.

### MC-3: DROP, not severe

Real inconsistency. The close path counts decommissioning and entering-maintenance replicas (`BlockManager`:1236-1241), but the append path does not (:1729). So a readable file refuses append while all its replicas are on out-of-service nodes. JIRA negative: the search for `isSufficientlyReplicated` plus decommissioning returned nothing relevant (bounded).

With a spare DataNode it clears when re-replication finishes. It lasts indefinitely only when no usable target exists, for example the report's one-DataNode cluster, where decommission cannot finish either. Reads work and a retry succeeds later. Times were measured with compressed intervals (1.5-2.5 s), so the real window at default intervals is unknown; it could be long for a large node. That is the main doubt. A cheap fix, worth reporting separately.

### MC-1: DROP, not severe

About 3 s after a restart. The report's route needs safe mode to have ended early because one block rounds the threshold to 0. In a real namespace safe mode covers most of this; the routes with the shipped extension and larger namespaces were not reproduced. A retry succeeds.

### MC-2: DROP, by design

A fatal disk error removes the node's replicas, and the test also stops the DataNode. The data is really unreadable, so refusing append is the guard's purpose (HDFS-6325, per the report). A readable file is refused only with `dfs.namenode.replication.min=2`.

### MC-5: DROP, unrealistic

The forced branch is real (`BlockManager`:1246-1251). The route needs an earlier failed close leaving a stale entry, IBRs held across several steps, and assertions off. The report: no firing without timing hooks, and a production delay long enough for the first hold was not shown. Clears with the IBR. Not read by me: `PendingRecoveryBlocks`:91, `FSNamesystem`:4179, `INodeFile`:350. The close reporting success with zero live replicas would be the concern if a natural route existed; HDFS-13757 and HDFS-12747 are nearby per the report.

### MC-6, MC-7: DROP, not severe

A stale RBW or RECEIVING report marks the only replica corrupt, and the queued RECEIVED report clears it (:3823-3824). A retry succeeds with intact data. MC-6's race is HDFS-3122, which reads the same but was closed Not A Problem; the run's "KNOWN-unfixed" is loose. MC-7 fired once in 600 rounds under DEBUG logging and 0/800 at default logging.

### MC-8: DROP, not severe

After failover, no location until the IBR. Forced with a hook; 0/440 without. Clears on the IBR.

---

## hdfs-adhoc-45 (target `FSEditLog.java`:1469)

### MC-4: DROP, unrealistic (closest call)

Target reached, severe, and I found no report. The defect, as read:

- `saveNamespace` holds only the FS read lock (`FSNamesystem`:5112) and ends the segment (`FSImage`:1162), reopening it only after the image is written (:1177).
- `registerDatanode` holds only the BM write lock (`FSNamesystem`:4455) and calls `checkSafeMode` (`BlockManager`:2755).
- With thresholds met and no extension, that leaves safe mode directly (`BlockManagerSafeMode`:215-225, :422). `startSecretManagerIfNecessary` passes because `isOpenForWrite` is true between segments (`FSNamesystem`:1344-1345).
- The master-key edit takes the FS **read** lock (`DelegationTokenSecretManager`:376), so it enters the gap. `doEditTransaction` then dereferences a null stream (`FSEditLog`:496). By the report, `txid` has already advanced in `beginTransaction`, which I did not read.
- The reopen fails at `FSEditLog`:1425, the log stays between segments, and the next `rollEdits` (`FSNamesystem`:5377) throws at the target. By the report, `mkdirs` fails too and only a restart recovers.

Why it does not meet the bar:

- **Reaching the target needs all of:** `FineGrainedFSNamesystemLock` (non-default, `DFSConfigKeys`:1084-1085); `dfs.namenode.edits.asynclogging=false` (default true, `hdfs-default.xml`:5434), because the async control terminated the NameNode first, off-target; delegation tokens; an operator `saveNamespace` during startup safe mode.
- **Plus one of:** an empty namespace with `min.datanodes` ≥ 1 (default 0), which is the only route run; or `dfs.namenode.safemode.extension=0`, argued from the code and not run. At the default extension the exit goes through `SafeModeMonitor`, which takes the GLOBAL write lock (`BlockManagerSafeMode`:666) and so waits for the save. I confirmed this; it closes the default-extension route.
- **Awareness:** the TODO at `FSNamesystem`:5110-5111 says this `readLock` should become `writeLock(RwLockMode.FS)` in "MileStone2". The interleaving is unreported, but the gap is known and the feature is unfinished.

Novelty (bounded, for the record): JQL `FineGrained`+`saveNamespace` 0 hits; `FGL`+`saveNamespace` 1 (HDFS-17412, different); `fine-grained`+`safemode` 9 by title (HDFS-17423 is the safe-mode conversion, not this); `summary ~ saveNamespace` since 2024, 0; GitHub issues/PRs: one hit, PR 6667 (HDFS-17412). HDFS-17424 confirmed Resolved Fixed; I did not read the PR #6696 review quote the report cites.

Off-target, but related and arguably more important to an FGL user:

- **Lock-order inversion.** `registerDatanode` holds BM and then takes FS (`FSNamesystem`:4455 to `DelegationTokenSecretManager`:376), against the documented order "FSLock,BMLock" (`FineGrainedFSNamesystemLock` class comment). I read this. The report saw one JVM deadlock against `DatanodeAdminMonitor` (1 in 8 JVMs); I did not read the jstack.
- **Async variant.** The same race on the default async log terminates the NameNode (`FSEditLogAsync`:279 per the report; not read by me). It avoids one non-default setting, but never reaches the target.

### MC-3: DROP, unrealistic

`rollEditLog` relies on the safe-mode check (`FSNamesystem`:5373). Per the report, `-safemode leave` or a low-disk episode lifts it on a BackupNode or CheckpointNode. It needs a superuser pointing `-rollEdits` at a node the docs do not offer it for. The CN result is one failed call. The BN result (journal detached, checkpoint blocked for at least 240 s) comes from the solo roll, not from the target firing, and "forever" is argued. I did not read the BackupNode paths.

### MC-1: DROP, not severe

`NameNode.stop` exits state without `setState` (`NameNode`:1237-1238) and clears `started` at the end (:1259). Per the report, a standalone daemon only joins, so an embedder must call `stop()`. One failed call, no state damage. I did not read all callers of `stop()`; the report's list has `BackupNode.stop` and the constructor's failure path.

### MC-2: DROP, not severe

Check-then-end gap at `FSImage`:1159-1162 against `BackupNode.stop`. Per the report: 5/5 with timing help, 0/30 without; one failed save on a stopping BackupNode, which restarts cleanly.

### MC-5: DROP, not severe

The stale read at `NameNode`:1237-1238 is real. The node is already stopping, callers were test harnesses, 1/40 with async logging even with timing help and 0/40 unassisted. Close to HDFS-12173 (Open), per the report's text.

---

## hdfs-adhoc-49 (target `DirectorySnapshottableFeature.java`:189)

### MC-1, MC-2, MC-3: DROP, unrealistic (G1)

Mechanism confirmed. `deleteSnapshot` branches on the local flag (`SnapshotManager`:511) and, for a non-earliest snapshot under ON, renames and returns before the decrement (:538-540, :546-547). The edit carries no mode. The quota check (`DirectorySnapshottableFeature`:188) has no replay relief, and a failure is rethrown at startup (`FSEditLogLoader`:296-299) or terminates the tailer (`EditLogTailer`:548-551).

The consequence is severe: the NameNode cannot start until the flag is reverted, and for MC-2 until an image is removed by hand. The run's Critical rating ignores what it takes to get there:

- The key sits under "The following are private configurations" (`SnapshotManager`:89-91). Per the reports it is absent from `hdfs-default.xml` and the docs.
- A directory must really hold 65536 snapshots, and the delete and re-create must be in the replayed tail (MC-1). The run itself calls this rare.
- MC-2 and MC-3 also need the two NameNodes to differ. Rolling enable passes through that state, which is the best argument, but it is an undocumented flag.
- MC-3's few-snapshots variant needs 65535 create/delete cycles under a mismatch that persists, and needs the FS limit raised. At the default limit the standby dies at a neighbouring check, so **the target is not reached**.

Not known, as far as bounded search shows: `text ~ "snapshot.deletion.ordered"` gave 0; `ordered snapshot deletion` + `standby` gave HDFS-15961 as nearest, a different defect. HDFS-17960 is the opposite direction.

The defect is real and cheap to state: replay should not depend on local config. Worth a note upstream, with the OFF-to-ON restart as the reproducer.

### MC-4, MC-5: DROP, known (G2)

`addSnapshot` inserts at :204 before the capture at :210-222, and the catch at :218 throws without undoing it. HDFS-17399 (Open, no comments) has the same production OOM stack. Non-default `capture.openfiles`. Same ruling as 52/MC-2.

---

## hdfs-adhoc-50 (target `DirectorySnapshottableFeature.java`:198; the frame reports :199, same statement)

### MC-6: DROP, unrealistic (G1)

Confirmed: `generateDeletedSnapshotName` gives `name#id` (`Snapshot`:68-70). With the writer OFF and the standby ON, the standby holds `b#1` and the client may legally create it. Consequences per the report are serious: the standby exits, and after a checkpoint neither NameNode restarts under either flag value. I did not verify that last claim; it comes from a test with compressed checkpoint intervals, and manual recovery was untested.

The trigger needs the private flag mismatched **and** a client creating a snapshot literally named `<deleted-name>#<its id>`. Nothing generates such a name: the default is `'s'yyyyMMdd-HHmmss.SSS` (:62). The ON/ON and OFF/OFF controls are clean. The report's "PR #8672 closed" is inaccurate: it merged (seen in HDFS-17960's comments).

### MC-4, MC-5: DROP, known (G2)

HDFS-17399. MC-4's extra consequences (id reuse, a path missing from a later snapshot, failed save) follow from the same missing rollback and strengthen that ticket; they are not a new defect. The report says the worker-failure branch was reached only through a mock.

### CR-1: DROP, known

HDFS-17954 (Open) with PR #8633 at the same gate, per the report and the ticket.

### MC-2: DROP, not severe (second-closest)

Per the report: WebHDFS runs with a dummy client id, so the retry cache is skipped, while the HA client hard-codes `isIdempotentOrAtMostOnce=true`. I did not read `WebHdfsFileSystem`:858-859 or `RetryCache`:206-211. Default configuration and one lost reply, 60 s timeout. The caller gets a final exception for a create that succeeded; the snapshot exists once.

Under the bar's "client-visible blip" this is not severe: the namespace is correct and listing resolves it. The default-name variant, which leaves a second snapshot, is more worrying, but the target stays quiet there, so it is off-target. Novelty: JQL `webhdfs`+`retry cache` gave HDFS-4979 and HDFS-5122, the decisions that created this, not a report of it (bounded). The same applies to any at-most-once op over WebHDFS, so it may deserve a report on that footing.

### MC-3: DROP, not severe

Same wrong answer, after the cache entry is lost. Per the report it needs a checkpoint and restart within the client's retry budget, or a shortened expiry.

### MC-1: DROP, not severe

Confirmed: millisecond-resolution name with no uniqueness (`Snapshot`:62-66). Default configuration, no fault, and truly reachable. The harm is one failed call, retriable at once, namespace intact. HDFS-4692 introduced it; no report found (bounded).

---

## zk-adhoc-01 (target `SessionTrackerImpl.java`:317)

The guard at :316-318 is right, and every report agrees: rejecting a request on a closing session is correct.

### MC-1: DROP, by design and not severe (G9)

The leader learns of a follower's sessions from PINGs (`LearnerHandler`:684). A stall in that stream delays them, the session expires, and the client gets `Expired`. Docs (`zookeeperProgrammers.md`:402-404) describe expiry on not hearing from the client, and the report concedes this is partly a design question. It needs a session timeout below `syncLimit*tickTime`, a test-written stall above the socket, and a 2-server ensemble or both followers stalled. With 3 servers and one stalled follower the session is lost the same way but **the target does not fire** (:171 in `LeaderSessionTracker`, per the report). The client is told, and a new session recovers it.

### MC-3: DROP, by design and not severe (G9)

Leader pause past the lease but under the sync limit. The `nothingQueued` controls lose the session with the target silent, so the target is a symptom, as the report says. The firing runs needed a Prep backlog of 293 creates carrying 800 ACLs, or thread holds. ZOOKEEPER-1740's text already describes a stalled leader waking with "several sessions to expire". This is a real operational pain, and a grace period after a stall could be a useful feature, but losing a lease across a leader stall with the client notified is not a defect meeting this bar.

### MC-4: DROP, not severe (G8)

The gap is real: `run` polls at :167 and marks at :169 with no re-check, `touchSession` (:179-194) accepts in between, and `ExpiryQueue.update` cannot pull the session back out of the polled set (:110-116). `Leader`:1791-1793 calls the related branch "(impossible)". But the deadline had really passed, so expiry is the contract. The client learns at once through `SESSIONEXPIRED`, and no stale state is left. The report states this caveat itself. Its "permanent" means only that the session stays gone.

Worth a small fix, as the "(impossible)" log shows the authors' belief is wrong.

### MC-2: DROP, masked

Run's verdict, and I agree. The delivered error is accurate. Its two side defects (below) are separate.

### CR-2: DROP, masked and non-default

Needs `localSessionsEnabled` and `localSessionsUpgradingEnabled`, plus a wire-protocol client. The pending close removes the node. ZOOKEEPER-3471 is the fix that makes the close global, not this.

---

## zk-adhoc-03 (target `SessionTrackerImpl.java`:330)

### MC-1: DROP, masked (G8)

`Leader.revalidateSession` touches at :1785 and sets the owner at :1789, catches the throw and only logs. By the report the reply still says valid. The close commit then expires the client, and writes in the window are refused. Client-visible effect: `valid=true`, then `Expired` moments later. Needed a timed burst of 600 clients. The session had really expired.

### MC-2: DROP, masked

Close from a second handle between the same two calls. The report's control shows results identical to a legal order.

### MC-3: DROP, source patch and not severe

Needs a `Thread.sleep` added between `PrepRequestProcessor`:567 and :568 (Level 3), standing in for a backlog never exercised. The client retries and connects. **Correction:** the run labels this KNOWN-unfixed under ZOOKEEPER-2600, but that ticket is Resolved, Cannot Reproduce, and its reporter attributed it to a local non-upstream change. So it is not a valid prior report; the drop stands on the other grounds.

---

## Could not check

- **Reproductions and logs:** nothing was rerun; repro test sources and raw logs were not read. See "How this was checked".
- **ZooKeeper master:** no upstream ref locally, so "unchanged upstream" for the ZooKeeper code is the reports' claim.
- **Novelty negatives:** JQL is coarse and most hits were judged by title. Only 45/MC-4 got a dedicated search from me, since it was the only finding where novelty could affect the verdict; other negatives are noted where stated and otherwise rest on the reports.
- **Real windows:** 40/MC-3 at default re-replication intervals; 50/MC-1's production rate; 45/MC-4 with a populated namespace and `extension=0`.
- **Code named only by reports, not read by me:** `PendingRecoveryBlocks`, `INodeFile`:350, `FSEditLogAsync`:279, `WebHdfsFileSystem`:858-859, `RetryCache`:206-211, the BackupNode paths, `beginTransaction`.
- **Unverified side claims, off-target here, each possibly worth its own look:**
  - 45/MC-4: FGL NameNode deadlock (the lock inversion is confirmed by reading; the deadlock itself is not) and termination with async logging.
  - 40/MC-3: `addStoredBlock` not zeroing the delta for maintenance nodes, tripping `assert curReplicas >= 0` (`LowRedundancyBlocks`:222).
  - 50/MC-2: the extra snapshot left by a re-sent default-name create.
  - 50/MC-6: neither NameNode restarting after a checkpoint.
  - zk-01/MC-2: `ServerCnxnFactory`:64-94 keeping one connection per session, leaving a handle `CONNECTED` on a session no server tracks; and `CommitProcessor`:325-327 matching on session and cxid only, giving a false `OK`.
