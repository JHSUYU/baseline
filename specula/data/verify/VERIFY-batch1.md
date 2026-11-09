# Independent verification, batch 1 (HDFS 34, 39, 52; ZooKeeper 02, b1, b2, b3)

Reviewed 2026-11-04 against the unmodified source: apache/hadoop `734dd8a67cd` and apache/zookeeper `eab16599`.

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands; a realistic trigger, not designed, not a test artefact, not already reported; and severe.

## How this was checked

- Every decisive code path below was read in the source. Line citations are at the commits above.
- **No test was run.** Reproduction results (hit rates, frames, consequences) come from the run reports. For zk-adhoc-b3/MC-1 I also read the level-0 test source and the tail of `repro/MC-1.pristine.log`. For the other findings I relied on the report text for what the repro does, including its claim of having no hooks, except where stated.
- Web: Apache JIRA REST, the GitHub API, raw.githubusercontent.com and api.osv.dev all answered. Novelty is a bounded negative: JQL text search is coarse, and the broad queries were judged by title. The openwall advisory URL returned a redirect page only, so the CVE text comes from OSV.
- Files read beyond the brief: `zookeeper/workloads/zk-adhoc-b1.md` and `zk-adhoc-b3.md` (operator records), for what the workloads do. Nothing under `/bulk/GraphChecker` was read.

## Summary

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| zk-adhoc-b3 / MC-1 | **KEEP-A** | silent, durable delete of a client's PERSISTENT znode; default config, no fault | mechanism high; tier medium |
| zk-adhoc-b3 / CR-3 | **KEEP-B** | after a live restore the manager scans the old tree forever and deletes restored nodes | high (mechanism); needs admin restore |
| zk-adhoc-b2 / MC-1 | **KEEP-B** | offer vanishes between list and read; participant goes FAILED and blocks the election | high (mechanism); medium (severity) |
| zk-adhoc-b2 / MC-3 | DROP, duplicate | same defect as b2/MC-1; its session-end route is included there | high |
| zk-adhoc-b2 / MC-2 | DROP, not severe | false FAILED on an instance already stopping; same fix site | high |
| zk-adhoc-b3 / CR-2 | DROP, duplicate | same gate as b3/MC-1, a narrower window | high |
| zk-adhoc-b3 / CR-4 | DROP, by design | non-default TTL; an already expired node is a documented candidate | medium |
| zk-adhoc-b3 / CR-5 | DROP, unrealistic | four independent conditions including snapshot bit rot | high |
| zk-adhoc-b3 / CR-6 | DROP, known | CVE-2026-79993 | high |
| zk-adhoc-b3 / CR-7 | DROP, known and off-target | ZOOKEEPER-5112; no target frame | high |
| zk-adhoc-b1 / MC-1 | DROP, known | ZOOKEEPER-5117 | high |
| zk-adhoc-b1 / MC-2 | DROP, unrealistic | needs a test-held worker stall; heals | high |
| zk-adhoc-b1 / CR-3 | DROP, known | ZOOKEEPER-5117 delete side; the target route needs two racing admin commands | high |
| zk-adhoc-b1 / CR-4 | DROP, off-target | real bug, but the report itself says the target does not fail | high |
| zk-adhoc-b1 / CR-5 | DROP, off-target and known | fails at SetQuotaCommand:236; its later L270 failure is ZOOKEEPER-5117's state | high |
| zk-adhoc-02 / MC-1 | DROP, known and not severe | ZOOKEEPER-710 handling; one recoverable reconnect | high |
| zk-adhoc-02 / MC-3 | DROP, not severe | same last-writer owner; test-written delay; recoverable | high |
| hdfs-adhoc-34 / MC-1 | DROP, unrealistic | needs a pre-federation disk in a hot add; retry clears | high |
| hdfs-adhoc-34 / MC-2 | DROP, unrealistic | same trigger as MC-1, though with a lasting effect | high |
| hdfs-adhoc-39 / MC-1 | DROP, known and not severe | HDFS-17757; non-default; transient | high |
| hdfs-adhoc-52 / MC-1 | DROP, known | HDFS-17960, fixed by PR #8672 | high |
| hdfs-adhoc-52 / MC-2 | DROP, known | HDFS-17399 | high |
| hdfs-adhoc-52 / MC-3 | DROP, known | same decrement as HDFS-17960; also needs a corrupt edit and `-recover` | high |
| hdfs-adhoc-52 / CR-2 | DROP, unrealistic and not severe | CheckpointNode, failed reload, and a direct saveNamespace to it | medium-high |

Totals: 24 findings; 1 KEEP-A, 2 KEEP-B, 21 DROP.

## Root-cause groups

- **G1, `deleteContainer` gate accepts any childless non-NORMAL node** (`PrepRequestProcessor`:326-338): b3/MC-1, CR-2. It is also the delete step of b3/CR-3, CR-5 and CR-6. A type check there would stop PERSISTENT loss in all of them, but would not fix CR-3's frozen database, or CR-5's stale index, or CR-6's missing ACL check.
- **G2, `toLeaderOffers` has no NoNode handling** (`LeaderElectionSupport`:309-310): b2/MC-1, MC-2, MC-3.
- **G3, `createQuota`/`delQuota` are not atomic** (ZOOKEEPER-5117, PR #2488 open): b1/MC-1, MC-2, CR-3, CR-5.
- **G4, `setOwner` is last-writer-wins and carries no attempt identity**: 02/MC-1, MC-3.
- **G5, `SnapshotManager.deleteSnapshot` decrements unconditionally** (HDFS-17960): 52/MC-1, MC-3. It also makes 52/MC-2's count error durable (MC-2's t3, t4 and t7).
- **G6, hot-swap workers share `DataStorage` fields with no lock**: 34/MC-1, MC-2. Same race as the already dropped 35/MC-1, MC-2 (`hdfs/VERIFY-storage.md`), and the unfixed hot-swap side of HDFS-14311.

---

## zk-adhoc-b3 (target `FinalRequestProcessor.java`:674)

### MC-1: KEEP-A

Stale `deleteContainer` removes a PERSISTENT node re-created at the path.

Walk:
1. `ContainerManager.getCandidates` (`ContainerManager.java`:185-209) picks used, empty containers from a scan.
2. `checkContainers` (:140-160) posts one path-only `DeleteContainerRequest` at a time, paced by `getMinIntervalMs`. At the default `maxPerMinute` of 10000 (:62) that is 6 ms per candidate, so the last post is N × 6 ms after the scan.
3. `PrepRequestProcessor`:326-338 checks only `childCount > 0` and `EphemeralType == NORMAL`. A PERSISTENT node has owner 0, so its type is VOID and it passes.
4. `DataTree`:927-931 applies it as an ordinary delete.
5. The client's later `getData` throws at `FinalRequestProcessor`:674.

Why it meets the bar:
- **Target:** reached with default settings, through a real committed delete. The guard's operands are not written by the test: the node is removed by the server's own manager.
- **Repro:** I read `SpeculaAdhocB3Mc1Level0Test`. It uses no manager subclass, no hook, no `znode.container.*` property, and only client API calls. It polls for the manager's first deletion, then replaces paths. The 3000 ms `postDeleteRequest` delay in the ported workload is used only by the level-1 tests.
- **Logs:** the pristine log shows `checkIntervalMs=60000 maxPerMinute=10000`, 114 of 1000 nodes lost in the quorum run shown, and the same set still missing after a restart. The report gives 98/1000 standalone and 45, 44, 114 on quorum. An earlier quorum run lost 0/1000; the report attributes that to setup crossing the scan.
- **Severity:** silent, durable loss of a node the client never deleted. The node's own data goes with it. No error reaches the client.
- **Not designed:** `ContainerManager`:39-40 claims "no harm" if a delete fails, but says nothing about deleting a different node. The docs tell clients to expect containers to vanish, not persistent nodes. `CreateContainerTest.testFalseEmpty` (:229) shows stale candidates are expected to be harmless.
- **Novelty:** JIRA (`deleteContainer`, `ContainerManager`, container + delete) and GitHub PRs show no report. ZOOKEEPER-2591 and CVE-2026-79993 concern ACL and session checks, a different defect: the CVE fix at master rejects the client opcode in `ZooKeeperServer` (master :1793) and leaves the gate unchanged. Master's `PrepRequestProcessor` :328-338 is the same as the pinned code, so MC-1 is unfixed on master by reading.

Weakest points, for whoever sets the tier:
- The victim must be a **type change**: a client deletes a used, empty container and re-creates the same path as PERSISTENT inside the window. That is legal but not common. Replacing a container with a new container only loses a fresh container, which clients are told to expect.
- The window is microseconds for a lone candidate (the report could not hit it without the hook) and grows only with the number of empty candidates in one pass. The level-0 numbers are stress figures from 1000 candidates, not a production rate.

If the owner counts a type change as a narrow trigger, this is KEEP-B. It meets KEEP-A's literal definition (severe, default configuration).

### CR-3: KEEP-B

After a live restore, the manager keeps the old database.

- `ContainerManager.zkDb` is final (:45, :90), bound at `ZooKeeperServerMain`:170 and `LeaderZooKeeperServer`:80.
- `ZooKeeperServer.restoreFromSnapshot` installs a new database at :627 and never rebinds the manager.
- So the manager scans a frozen tree for the life of the process, and its candidates are applied to the new tree through the gate in G1.
- Restore is enabled by default (`Commands.java`:654) and documented (`zookeeperSnapshotAndRestore.md`), with no restart step. It needs ALL on `/`.
- Master still has the same final field and binding at `ZooKeeperServerMain` :172.

Consequence: a restored childless PERSISTENT node at a stale candidate's path is deleted durably, and any later re-create at that path is deleted again on each 60 s check. By reading (not in the report's evidence), the manager also stops cleaning real containers and TTL nodes of the new tree until a restart or a new leader term.

Target: reached, according to the report, with shipped default intervals. The frame comes from its JDI watcher.

Why tier B: it needs an admin restore without a restart, and a path whose type differs between the old tree and the restored one, or a re-create. Also: only a standalone server was run; the report argues the quorum case from code. It is distinct from MC-1: the fix is rebinding the manager, and MC-1's fix alone would not restore cleanup.

JIRA: ZOOKEEPER-4571 is the feature; I found no report of this.

### CR-2: DROP, duplicate of MC-1

`getCandidates`' container loop has no type check (`ContainerManager`:187-209, unlike the TTL loop at :215), so a replacement read during the scan is selected. The defect is real but the outcome is MC-1's, and fixing the gate covers it. It is also narrower: the report needed ≥10,000 containers and continuous replacement with a child added and removed, and has no run at the default interval or on a quorum. Worth mentioning as a second fix site in any MC-1 report.

### CR-4: DROP, by design (and non-default)

Mechanism is correct: `PrepRequestProcessor`:326-338 does not re-check TTL expiry, and a `setData` after the scan does not save the node. But TTL nodes need `zookeeper.extendedTypesEnabled=true` (`EphemeralType`:158), and the node was already expired when scanned. The docs (`zookeeperProgrammers.md`:242-244, as quoted in the report) say such a node "will become a candidate to be deleted by the server at some point in the future". A client refreshing an expired node has no promise of survival. Medium confidence: the loss of an acknowledged write is unpleasant, and an owner who reads the docs more strictly could call this KEEP-B.

### CR-5: DROP, unrealistic

`DataTree.deserialize` (:1344-1348) clears `nodes` and `pTrie` but not `containers`, and `FileSnap` retries on the same tree, so the stale index is real. Reaching the target needs all of: snapshot bit rot that passes the tail check, an earlier SNAP sync leaving a log gap, a container replaced by a persistent node at the same path, and the affected peer winning the election.

Side note, off-target and unverified by me: the report says the fallback across a log gap silently lost 600 acknowledged versions on that peer, which then led the cluster. That deserves its own look, separately from this finding.

### CR-6: DROP, known

CVE-2026-79993, confirmed on OSV. The pinned tree has no origin gate; master rejects the opcode (`ZooKeeperServer` master :1793). Also needs raw protocol use.

### CR-7: DROP, known and off-target

ZOOKEEPER-5112 (Open, 2026-10-22) is the same request and the same gap (`EphemeralType.validateTTL`:218-224). The crash has no frame at the target.

---

## zk-adhoc-b2 (target `FinalRequestProcessor.java`:674)

Base note: this case's base is `1312ae0187`, a local commit on top of upstream that changes the recipes' test classpath. I compared it with `src/zookeeper`: `LeaderElectionSupport.java` is byte-identical, and FRP lines 672-675 are the same. Citations are valid for both.

### MC-1: KEEP-B (includes MC-3)

Walk:
- `determineElectionStatus` lists children (`LeaderElectionSupport`:199), and `toLeaderOffers` reads each with a separate `getData` (:309-310) with no NoNode handling.
- If an offer goes away in between, by a peer's `stop()` (:155) or a session end, the server throws at FRP:674. The exception reaches `start()` (:138) or `process()` (:336) and `becomeFailed` (:270-275), which only sets state and dispatches.
- The offer stays live (ephemeral, session still up). No watch is registered and nothing retries, so peers behind it stay READY. `getLeaderHostName` (:291) reports the FAILED host as leader or throws to the caller.
- The same race is handled deliberately one call later (:249-256: "the node has gone missing between the call to getChildren() and exists()"), so this is an omission, not a choice.

Target: reached at level 0 with public APIs (the report's JDI frames; 12/200 and 19/200 FAILED in plain runs; once in the unmodified workload, which still passes). A join or re-determination overlapping one ordinary departure is enough, for example during a rolling restart.

Why tier B, not A:
- **Documented escape:** class Javadoc (:72-75) makes it "up to the user" to `stop()` on failure to become leader. An application following that frees the queue, but the candidate leaves the election; re-joining needs a further application-level `start()`. So the lasting wedge is in the library, and the application can recover it.
- **Scope:** a recipe library with no in-tree user except tests, not the server. The wedge is of the application's election, with no effect on ZooKeeper itself.
- Only a standalone server was run. Permanence beyond the 3 s and 45 s windows comes from the code (I agree with it: only :239 registers a watch).

Novelty: JIRA `toLeaderOffers` 0 hits; 11 `LeaderElectionSupport` hits read by title; ZOOKEEPER-1219, 1225, 1209, 1405 are different mechanisms according to their summaries. ZOOKEEPER-1219 and 1405 are the nearest; I did not read their full text.

### MC-3: DROP, duplicate of MC-1

Same line, same fix. The route is a peer's session close or expiry rather than `stop()`. It adds useful evidence for MC-1: it uses separate sessions and real expiry, and the class doc (:59-62) promises a re-determination when an offer disappears by process failure. Report it as part of MC-1.

### MC-2: DROP, not severe

A participant's own `stop()` races its EventThread determination (`process` checks state once at :330), and FAILED overwrites STOP after `STOP_COMPLETE`. The offer has already been removed and nothing blocks. The harm is one false event on an instance that was leaving. The fix at :310 removes this firing too.

Not checked: the report's adjacent claim of participants ending ELECTED after `stop()` returned. It is off-target; if true it is a more serious symptom and would need its own review.

---

## zk-adhoc-b1 (target `FinalRequestProcessor.java`:674)

Target caveat for the owner: L674 also throws on **every first `setquota`** with no fault. `ZKUtil.visitSubTreeDFS` :237 does `getData` on the not-yet-existing quota path, and `SetQuotaCommand.checkIfChildQuota` catches it. So the target's note "the check does not fail in it" holds only for the workload's outcome. A frame at L674 proves nothing in this case by itself; MC-1 ties the frame to the stats read, which is the right test.

### MC-1: DROP, known

`createQuota` creates limits (`SetQuotaCommand`:236) and stats (:243) in two RPCs; the retry takes the update branch and reads stats at :270. Real, and severity is fair (`ZooKeeperServer`:2183 skips enforcement). It is exactly ZOOKEEPER-5117 (Open, filed 2026-11-03); PR #2488 is open, unmerged. Note the report's own novelty note: the JIRA built the partial nodes by hand, and this run reached them with a real connection loss. That is evidence for the ticket, not a different defect.

### MC-2: DROP, unrealistic

A retry's `getData(stats)` overtakes a `create(stats)` still in a held worker. The reproduction holds the worker for 11.3 s through a test `submitRequest` override, 0 of 200 uncontrolled rounds matched, the report found no natural cause, and the state heals when the late create applies. The underlying observation (requests from a closed connection are not fenced when the throttler is off) was not assessed further here.

### CR-3: DROP, known

`delQuota` deletes children one at a time (`DelQuotaCommand`:137-141). ZOOKEEPER-5117's text describes the delete side, and PR #2488 changes this loop. Interruption alone never fails the target as a failure (the report says so). The route that does needs a second admin running `setquota` between the two deletes, ending in the same limits-without-stats state; it did not occur in 4000 level-0 rounds.

### CR-4: DROP, off-target (real bug)

`SetQuotaCommand`:302-303 catches `InterruptedException | KeeperException` in the `checkIfChildQuota` callback and only prints it, while `checkIfParentQuota` has no such catch. A transient loss on that one read skips the check, so `setquota` succeeds and leaves a forbidden nested quota. The report states the target check is not shown failing. By its figures it is 1 hit in 450 random kills and 20/20 when aimed at that read. No JIRA hit for `checkIfChildQuota`. Worth reporting upstream on its own merits (wrong limit enforcement), but not under this bar.

### CR-5: DROP, off-target and known

The failure is `NodeExists` at `SetQuotaCommand`:236, not the target. It needs fsync stalled ≥1.5 s on two of three servers (a test-installed stall), a connection break, and a reconnect to a different follower. The later L270 failure and missing enforcement are ZOOKEEPER-5117's state. The unhandled `NodeExists` at :236 itself is not in that ticket as a retry race, but it is minor.

---

## zk-adhoc-02 (target `SessionTrackerImpl.java`:323)

### MC-1: DROP, known and not severe

`setOwner` (:327-333) is last-writer-wins, and `Leader.revalidateSession` (:1777-1789) sets the owner to the follower's handler, so a late REVALIDATE from an abandoned attempt causes the throw (:323). `FinalRequestProcessor`:593-602 describes this race as ZOOKEEPER-710's "invalid SESSION MOVED" and handles it by closing the connection. The harm is one ConnectionLoss; the client reconnects (64-520 ms in the report) and the retry succeeds. The level-1 run also holds `Learner.leaderOs` by reflection; level 0 fired 0, 6 and 1 of 200. ZOOKEEPER-2219 (Open) is the mirror. The report itself rates it Low.

### MC-3: DROP, not severe

Same mechanism through a same-follower re-sync: a stale handler's delayed packet. It never fired at level 0 (30 resets, 126,149 writes) and needs a delay from a test-written forwarder. Same recoverable outcome. I also checked the report's `sync` path: `sync` returns OK through `ProposalRequestProcessor`:76-77 despite the throw, the next write takes the same failure, and I see no consistency loss there. The report labels it NEW; the mechanism is not distinct enough from G4 to matter under this bar.

---

## hdfs-adhoc-34 (target `DataStorage.java`:741, frame at :744 since the throw spans 741-744)

### MC-1: DROP, unrealistic

Race is real: `DataNode.refreshVolumes` (:1312-1329) runs one unlocked worker per new volume, and `DataStorage.prepareVolume` (:324-346) → `doTransition` reads and writes shared `layoutVersion`/`namespaceID` (:631, :640, :729-741).

The target's guard requires `!federationSupported`, so some volume must hold a pre-federation LV. `LAST_UPGRADABLE_LAYOUT_VERSION` is -16 (`Storage`:91). No other volume mix can reach :741: every federated LV supports the feature. So the trigger is a 0.20/1.x data dir in the same hot add as a current one. That is the same reason 35/MC-1 was dropped (`hdfs/VERIFY-storage.md`). Also recoverable: the report rates it Low and an operator retry succeeded.

### MC-2: DROP, unrealistic

Same trigger. The consequence is worse than MC-1, which is why I looked harder: `setPropertiesFromFields` (:597-608) can write `{layoutVersion=-16, namespaceID=0}` onto a healthy volume, after which every start throws at the target and, with `failed.volumes.tolerated=0`, the DataNode cannot start. But `controlNoLegacy` (60 attempts × 8 volumes) changed no VERSION file, and I see no route without a legacy disk. Severe only given an input that a current cluster does not meet in practice. Consistent with 35/MC-2.

---

## hdfs-adhoc-39 (target `FSDirAppendOp.java`:133)

### MC-1: DROP, known and not severe

Confirmed: with `dfs.namenode.file.close.num-committed-allowed` ≥ 1 (default 0, `hdfs-default.xml`:5478-5479), a closed file can have a COMMITTED last block, `recoverLeaseInternal` (:126) returns, and the guard at :132 throws at :133. HDFS-17757 (Open, confirmed) reports this exact setup and message. A `RetriableException`, retried for 5 s by the client, clears at the first usable report; visible to the caller only with 30 s report periods or a paused IBR.

---

## hdfs-adhoc-52 (target `FSImageFormatPBSnapshot.java`:467; the yaml's 466 is a closing brace)

### MC-1: DROP, known

`removeSnapshot` returns null at `DirectorySnapshottableFeature`:258-261, and `SnapshotManager`:546-547 decrements anyway. HDFS-17960 confirmed; PR #8672 confirmed merged 2026-09-23 as `2014707f8c3`, which is not an ancestor of the pinned commit. JIRA still shows Open. Severe (NameNode cannot start), but already reported and fixed.

### MC-2: DROP, known

`DirectorySnapshottableFeature` adds to the list at :204 and captures open files at :210-222, and `SnapshotManager`:465-469 increments only afterward. `catch (Exception)` at :218 does not catch `OutOfMemoryError`. HDFS-17399 (Open) reports the same OOM stack from a customer. Needs non-default `capture.openfiles`. The report's level-0 fuzz never hit it; it needed `RLIMIT_NPROC` or a spy. Target frame is a new observation on a known defect, not a different defect.

Off-target note from that report, unverified by me: a fuzz seed terminated the NameNode with `Dangling child pointer found` (`FSImageFormatPBINode`:761) with no injected fault. It deserves its own look.

### MC-3: DROP, known

Same decrement as MC-1, reached by a different route: `-recover` skipping an unreadable create. Needs a corrupt edit with no other copy, then `-recover`. Fixed by the same commit.

### CR-2: DROP, unrealistic and not severe

Real: `FSNamesystem.clear` (:732-741) → `clearSnapshottableDirs` (`SnapshotManager`:753-755) leaves `numSnapshots`. The route is a CheckpointNode whose reload fails (`FSImage`:653, `Checkpointer`:160-161 logs and continues) plus a client `saveNamespace` sent directly to it (`checkOperation(UNCHECKED)` at `FSNamesystem`:5105 passes `BackupNode`:447-460). The report's failure was forced with a codec configured only on the NameNode. Harm is confined to that CheckpointNode's image dir until restart; the active NameNode is untouched. No JIRA match found.

Side note, unverified: the report says a stale count of 0 lets the same save overwrite the checkpoint with an empty image. Off-target.

---

## Could not determine

- **Production frequency** of b3/MC-1, b3/CR-3 and b2/MC-1. All rates are stress figures, and none of these was measured under real load.
- **Whether applications really replace containers with persistent nodes** at the same path (b3/MC-1's tier depends on this). Nothing in the source settles it.
- **Quorum behaviour of b3/CR-3 and b2/MC-1:** neither report ran it.
- **Whether a JIRA with different wording exists** for b3/MC-1, b3/CR-3 or b2/MC-1. The negative searches are bounded.
- **Unverified adjacent claims:** b3/CR-5's log-gap fallback, 52/MC-2's dangling-child crash, b2/MC-2's stale ELECTED, 52/CR-2's empty-image overwrite.
