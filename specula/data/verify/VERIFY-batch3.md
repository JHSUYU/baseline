# Independent verification, batch 3 (ZooKeeper 04, 06, 07, 10, 11, 12, 13, b4, b5, b6)

Reviewed 2026-11-05 against the unmodified source: apache/zookeeper `eab16599`, extracted with `git archive` so no case-tree probe could leak in.

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands and without a source patch or injected sleep; a realistic trigger, not designed, not a test artefact, not already reported; and severe. KEEP-A also needs a default configuration.

## How this was checked

- Every decisive code path below was read in the source. Line citations are at `eab16599`.
- **No test was run.** Hit rates, frames and consequences come from the run reports. I read the repro source or log myself only for: 11/MC-3 (Level 0 test), 10/MC-1 (run log, test's packet calls), b6/MC-3 (limit settings in the test), 04/MC-2 (session settings in the test). For every other finding I relied on the report's own account of what its repro does.
- **Targets:** none of the ten targets is a Java `assert`; all are `throw` statements. Several reports show a frame one to three lines below the target (for example 1237 for 1236, 1259 for 1256, 1525 for 1522, 525 for 522). I read those statements: each is one multi-line `throw`, so these are the target.
- **Web:** Apache JIRA REST, the GitHub REST API (PRs #2454 and #2459 diffs, five PR searches) and raw.githubusercontent.com master all answered. Master here means `87e85f28e7`, 2026-11-04. Novelty is a bounded negative: JQL text search is coarse, broad queries were judged by title, and mailing lists were not searched.
- **zk-adhoc-04** has no `adhoc-result.json` or `bug-severity.md`. I reviewed its REPRODUCED and MASKED findings only; its MC-3 (PENDING REPAIR) and other entries are out of scope.
- 12/CR-1 is ENV_LIMITED and all FALSE POSITIVE entries are out of scope. Nothing under `/bulk/GraphChecker` was read.

## Summary

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| zk-adhoc-11 / MC-3 | **KEEP-B** | in-process stop during sync logs new-epoch txns with no epoch write; peer can never restart. Embedded/controller stops only | high (mechanism); medium (tier) |
| zk-adhoc-11 / CR-1 | **KEEP-B** | one failed epoch write wedges an observer permanently, even after the disk recovers | high (mechanism); medium (realism: needs an I/O error) |
| zk-adhoc-04 / MC-2 | **KEEP-B** | read-only server serves never-committed txns; the client then trips the target | high (mechanism); low-medium (a maintainer may call it a documentation gap) |
| zk-adhoc-b6 / MC-3 | **KEEP-B** | eviction empties the retained queue and skips the gap check; silent, lasting observer divergence | high (mechanism); low (trigger needs stacked non-defaults, owner's call) |
| zk-adhoc-11 / MC-1 | DROP, known | ZOOKEEPER-1653/2354/4283, unfixed. The most real of the epoch class | high |
| zk-adhoc-11 / MC-2 | DROP, known and transient | same on-disk state as MC-1; without a restart it heals | high |
| zk-adhoc-11 / CR-2 | DROP, injected timing | reconfigEnabled, a write fault and a test-held thread; 0 of 11 without the hold | high |
| zk-adhoc-11 / CR-3 | DROP, unrealistic | a stand-in thread holds the lock by reflection; 0 hits black-box | high |
| zk-adhoc-11 / CR-4 | DROP, masked | no harm of its own; next sync or start corrects it | high |
| zk-adhoc-11 / CR-5 | DROP, known and masked | ZOOKEEPER-2562; tmp fallback masks it on common filesystems | high |
| zk-adhoc-11 / CR-7 | DROP, unrealistic | failed write plus zxid gap plus specific leader outage; no acked write lost | medium-high |
| zk-adhoc-12 / MC-1 | DROP, injected timing | 5 s test-held handler, latched writers; no unhooked hit | high |
| zk-adhoc-12 / MC-2 | DROP, known | ZOOKEEPER-4781, unfixed | high |
| zk-adhoc-12 / MC-3 | DROP, unrealistic | two rename failures, a successful delete and a crash, all injected | high |
| zk-adhoc-b5 / MC-1 | DROP, known | ZOOKEEPER-5094, PR #2459 open | high |
| zk-adhoc-b5 / MC-2 | DROP, duplicate | same defect as 11/MC-3; needs timing holds | high |
| zk-adhoc-b5 / MC-3 | DROP, known | ZOOKEEPER-2846 scenario 2; real data loss, but reported | high |
| zk-adhoc-b5 / MC-4 | DROP, unrealistic | a held race times a power-loss window; incomplete ZOOKEEPER-2310 fix | medium |
| zk-adhoc-b5 / MC-5 | DROP, known | ZOOKEEPER-3598 (reverted fix); 0 hits without a sleep | high |
| zk-adhoc-b6 / MC-1 | DROP, known | ZOOKEEPER-5088, PR #2454 open | high |
| zk-adhoc-b6 / MC-2 | DROP, injected timing | same family as 5088; held apply, 0 hits at Level 0. PR #2454 does not cover it | medium |
| zk-adhoc-b6 / CR-2 | DROP, duplicate | gap source is 5088; the waiver is a TODO in the code; held ACKs | high |
| zk-adhoc-b6 / CR-3 | DROP, off-target and known | target fired 0 times; 5088's drop | high |
| zk-adhoc-07 / MC-1 | DROP, known | ZOOKEEPER-4040/3481; ends at a leader change | high |
| zk-adhoc-07 / MC-2 | DROP, injected timing | three holds over a 141-231 µs window; same symptom as 4040 | high |
| zk-adhoc-07 / MC-3 | DROP, not severe | one retried observer handshake | high |
| zk-adhoc-10 / MC-1 | DROP, off-target | target needs LOG_ONLY; default exits earlier at another line. **See side finding S1** | high (off-target); see S1 |
| zk-adhoc-10 / MC-2 | DROP, off-target | same LOG_ONLY limit; needs reconfig. See S2 | high |
| zk-adhoc-10 / MC-3 | DROP, injected timing | 63-75 µs window held; LOG_ONLY; 0 of 180 s stress; heals | high |
| zk-adhoc-10 / CR-1 | DROP, masked | leader commit-order block stops it | high |
| zk-adhoc-13 / CR-7 | DROP, off-target | target not thrown; real divergence. See S3 | high (off-target) |
| zk-adhoc-13 / CR-5 | DROP, off-target and unrealistic | target not thrown (0 refusals); aimed clock in a time namespace | high |
| zk-adhoc-13 / CR-6 | DROP, known | ZOOKEEPER-4253/2503; simulated reboot | high |
| zk-adhoc-13 / MC-1 | DROP, known, by design | ZOOKEEPER-4610; docs say no downgrade | high |
| zk-adhoc-13 / MC-2 | DROP, not severe | one client handle; next quorum resolves it | high |
| zk-adhoc-13 / MC-3 | DROP, injected timing | forced thread hold; 0 of 80 natural | high |
| zk-adhoc-13 / CR-2 | DROP, injected timing | same zombie as MC-3; 0 of 80 natural; a thread leak | high |
| zk-adhoc-13 / CR-4 | DROP, off-target | guard is bypassed, not fired; docs say local sessions are required | medium-high |
| zk-adhoc-13 / CR-11 | DROP, not severe | delayed `Expired` notification | high |
| zk-adhoc-06 / MC-3 | DROP, not severe | 41 s stall with a test-held voter; re-election heals | high |
| zk-adhoc-06 / MC-4 | DROP, not severe | same self-healing rejoin; data kept | high |
| zk-adhoc-06 / MC-1, MC-2 | DROP, masked | automatic retry and recovery | high |
| zk-adhoc-04 / MC-1 | DROP, known and not severe | ZOOKEEPER-3822; refusal is transient | high |
| zk-adhoc-04 / CR-2 | DROP, not severe | needs a multi-second stall; lost watch event only | high |
| zk-adhoc-04 / MC-4 | DROP, masked | non-default setting, empty data dir; misleading message | high |
| zk-adhoc-b4 / MC-1, MC-2 | DROP, not severe | contrib ZooInspector retry helper; a retriable quota error; `recipes.md` documents the pattern | high |

Totals: 48 findings; 0 KEEP-A, 4 KEEP-B, 44 DROP.

**Against `zookeeper/VERIFIED-BUGS.md`:** no overlap. Its three kept bugs are b3/MC-1, b3/CR-3 and b2/MC-1, a different area. `zookeeper/bugs/` holds entries for 04/MC-1, 04/MC-2, 06/MC-3, 06/MC-4 and 07/MC-1; only 04/MC-2 survives here. I changed neither file.

## Root-cause groups

- **G1, durable state ahead of `currentEpoch`** (`Learner`:760/804 before :813, checked at `QuorumPeer`:1236): 11/MC-1, MC-2, CR-2, CR-3, CR-7. The state is ZOOKEEPER-1653's whatever the route; a fix for 2354 would help all their restart failures.
- **G2, `syncWithLeader` treats a stop as a finished sync** (`Learner`:651 then :825-842): 11/MC-3, b5/MC-2. Fix site differs from G1 and from ZOOKEEPER-5094.
- **G3, stale `syncMode` after a failed epoch write** (`Learner`:816 skipped, then :924): 11/CR-1. Also the "no crash" half of 11/MC-2 and 11/CR-7.
- **G4, `acceptedEpoch` writes** (`Leader`:1482-1483, `AtomicFileOutputStream`:90, no shutdown check in `getEpochToPropose`): 12/MC-1, MC-2, MC-3, 07/MC-2.
- **G5, a higher `acceptedEpoch` than the leader's frozen epoch** (`Leader`:1471-1472, `Learner`:522): 07/MC-1, MC-2, MC-3. ZOOKEEPER-4040.
- **G6, TRUNC sync holds committed txns in memory until an unsynced snapshot** (`Learner`:618-628, :690, :760, :924): b5/MC-1, MC-2, MC-3, MC-4. Same hole, four exits.
- **G7, `ObserverMaster` never sees txns from the follower's own sync** (`Follower`:115, `Learner`:840-847): b6/MC-1, MC-2, CR-2, CR-3. ZOOKEEPER-5088 (MC-2 is the branch PR #2454 leaves open).
- **G8, `startForwarding` skips its gap check when `committedPkts` is empty** (`ObserverMaster`:294-295, :330): b6/MC-3, and the activation step of b6/MC-1 and MC-2.
- **G9, logged-only txns fast-forwarded into a served tree** (`ZooKeeperServer`:936, `FileTxnSnapLog`:330-360): 04/MC-2, 06/MC-4, 13/MC-2.
- **G10, placeholder zxid `(e,0)` held only in the leader's memory** (`Leader`:1609): 04/MC-1, 06/MC-3.
- **G11, `roZk.shutdown()` is a no-op before startup** (`ZooKeeperServer`:903, :923; `QuorumPeer`:1549-1550, :1575): 13/MC-3, CR-2.
- **G12, session-id reuse** (`SessionTrackerImpl`:98-106): 13/CR-5, CR-6.

---

## KEEP findings

### zk-adhoc-11 / MC-3 (and b5/MC-2): KEEP-B

Target `QuorumPeer.java`:1236. A stop during sync leaves a peer that can never restart.

**Root cause, read in the source:**
1. `QuorumPeer.shutdown` sets `running = false` first (`QuorumPeer`:1682). The socket is closed later, inside `follower.shutdown()` (:1687-1688, `Learner`:919).
2. The sync loop's only other exit is `break outerLoop` on UPTODATE (`Learner`:745). `while (self.isRunning())` (:651) ending falls through to the same code.
3. That code writes the ACK (:825-826), starts zk (:827) and logs every buffered proposal (:838-842).
4. `setCurrentEpoch` runs only under NEWLEADER (:813) or pre-Zab-1.0 UPTODATE (:741). On this path it never runs, so no `currentEpoch.tmp` exists either.
5. The next start replays new-epoch txns: `epochOfZxid > currentEpoch`, no tmp, throw at `QuorumPeer`:1236 (reached from :1194 before any network). Nothing can repair it from inside.

**Trigger:** an in-process stop while a learner drains PROPOSAL and COMMIT packets before NEWLEADER; the report's route is a late joiner receiving SNAP under write load. `QuorumPeer.shutdown`'s production callers are `QuorumPeerMain.close` (:253-256, Javadoc "not a public API"), used by `ZooKeeperServerEmbeddedImpl.close` (:224-231), and `ZooKeeperServerController` (:80). I found no shutdown hook that calls it (the only `addShutdownHook` is in `ZKAuditProvider`), and the report says `zkServer.sh stop` sends SIGTERM. So a plain server is not exposed, and a SIGKILL cannot produce this: the post-loop code must run.

**Evidence (report):** fired 29 times in 437 stop trials on a pristine tree, no hooks. I read that test: it starts, writes and stops, choosing the moment by polling read-only getters and adding a random delay. A failed start repeated on a second attempt. The control, stopped after sync, restarts fine. 29/437 is an aimed stress figure, not a production rate.

**Consequence:** one peer down for good, ensemble keeps serving. Redundancy is lost until an operator acts. No data loss shown.

**Recovery:** delete `version-2` and resync. `zookeeperAdmin.md`:527-535 documents this for "file corruption" with an IOException at load, after checking the other servers are healthy. The doc does not mention epoch files, but the procedure applies. On a majority of peers it would risk data.

**Why B:** severe, but only embedders and controller stops. The window is the sync drain, which grows with write load during a SNAP.

**Novelty:** JIRA (`syncWithLeader` + `shutdown`, `isRunning` + `syncWithLeader`, `older than the last zxid`, embedded + `currentEpoch`) and GitHub PR search show no report. ZOOKEEPER-5094 / PR #2459 is the nearest: it changes only `Learner.shutdown` and does not touch the fall-through. ZOOKEEPER-1653/2354 is the same symptom by a crash route. ZOOKEEPER-2653 has the same message and an embedded stack, but its file list has `snapshot.400000109`, which fits the MC-1 route, not this one. Master still has `while (self.isRunning())` at `Learner`:651.

**b5/MC-2 is the same defect** seen through TRUNC, firing at `ZKDatabase`:341. It needed timing holds, so it does not stand alone, but any fix should cover both.

### zk-adhoc-11 / CR-1: KEEP-B

Target `QuorumPeer.java`:1236. One failed epoch write permanently wedges an observer.

**Root cause, read in the source:**
1. `syncMode` is set at `Learner`:588, :597, :620 and reset only at :816, after `setCurrentEpoch` (:813). Those are all its writers.
2. If :813 throws from opening, writing or syncing the tmp, the tmp is gone: `AtomicFileOutputStream`:59 throws before creating it, or :100-103 and :119 delete it. (A failed rename keeps it and takes the fallback.)
3. `Learner.shutdown` sees stale SNAP and passes `fullyShutDown=true` (:924). `ZooKeeperServer`:946-947 clears the database even if the server never started.
4. Observers do not reload in election (`FastLeaderElection`:864-868). They reload in `registerWithLeader` (`Learner`:490, `QuorumPeer`:1387-1388).
5. The snapshot from the aborted sync is on disk, so the load throws at `QuorumPeer`:1236. `registerWithLeader` never reaches `syncWithLeader`, so nothing can reset `syncMode`.
6. `Observer`:131 catches it, `QuorumPeer`:1600 calls `observer.shutdown()`, and step 3 clears the database again. `ZKDatabase`:291 had set `initialized` before the check, but the clear undoes that, so the loop never ends.

A follower escapes: its reload happens in election, the catch at `QuorumPeer`:1586 retries with `initialized` still true, and the next sync repairs the file (report's 11/MC-2 testA).

**Trigger:** one real SNAP sync of an observer plus one I/O error on a small file, for example a nearly full disk after the snapshot landed, or a read-only remount. The report has a thrown-fault variant through the `writeLongToFile` override `EpochWriteFailureTest` uses, and a variant with a real `Permission denied`. The disk being healthy afterwards does not help.

**Evidence (report):** 429 attempts and 428 target throws in 45 s; the loop survives a leader change; a restart fails at the same line; a client that only knows that observer never connects; participants keep serving. Control: resetting `syncMode` per attempt gives one throw, then the observer serves.

**Consequence:** a wedged observer with log flooding and no self-healing. It neither exits nor serves, so a supervisor sees a live process.

**Recovery:** delete `version-2`, per `zookeeperAdmin.md`:527-535. Report did not test it.

**Why B:** observers are not default, and it needs an I/O fault. The window is the one write, but the fault need only happen once, and the wedge lasts.

**Novelty:** JIRA `syncMode` and `observer` + `older than`, GitHub PR search for `syncMode observer` (0 hits). ZOOKEEPER-1653/2354/4283 share the on-disk state but not the runtime loop; PR #2459 edits the same line and would extend the stale-mode clear to TRUNC. ZOOKEEPER-2162 ("infinite exception loop when dataDir is lost") has a similar shape, which I judged by title only. Master has the same code at `Learner`:924.

### zk-adhoc-04 / MC-2: KEEP-B

Target `ZooKeeperServer.java`:1516. A read-only server returns data that was never committed.

**Root cause, read in the source:**
1. A leader that loses quorum shuts down through `ZooKeeperServer.shutdown(false)`, which fast-forwards the tree over the log (`ZooKeeperServer`:928-936).
2. The replay in `FileTxnSnapLog`:330-360 has no notion of commit. The log holds no commit records.
3. `QuorumPeer`:1536 builds the read-only server on that same `zkDb`, and it starts after a grace period (:1548-1550). Reads are served from the replayed tree.
4. The client's `lastZxidSeen` becomes that never-committed zxid. A next-epoch server without it refuses at :1516: the guard working correctly.

**Trigger:** `readonlymode.enabled=true` plus `localSessionsEnabled` (the test sets both; `zookeeperAdmin.md`:1919 requires the latter), a `canBeReadOnly` client, and a leader that loses its followers with writes in flight, since it checks quorum only once per tick. A partitioned leader under write load is enough. Level 0: client API and server stops only.

**Evidence (report):** 281 writes, 0 acknowledged, 260 visible at the read-only server; all 260 absent from the next epoch; the client refused 4 times in 6 s; after one new-epoch write it reconnects and the znode it read is `NoNode`. Next-epoch route 3/3 on both Netty and NIO; restart route 1/1. On default NIO the exception is swallowed at `NIOServerCnxn`:380, so the frame comes from Netty and the log line `ZooKeeperServer@1515`.

**Consequence:** a wrong result that cannot be undone: a client acts on data the ensemble never committed. The refusal itself is transient and is not the harm. Servers converge afterwards.

**Why B, and the weak point:** non-default, opt-in on the client too. `zookeeperAdmin.md`:1921-1925 promises reads that may not "see changes from other clients", which is staleness, not phantom data. A maintainer could still treat this as a limitation to document. The run is also incomplete (no final classification), though this finding itself reached REPRODUCED.

**Novelty:** JIRA `read-only` + `uncommitted` (14 hits, none on this), `read-only` + `fastForward` (0), and GitHub PR search (only an unrelated #2141). ZOOKEEPER-2845 is the same fast-forward for a different consequence. ZOOKEEPER-2506 "Document use of read-only mode" is open and empty. Master still fast-forwards at `ZooKeeperServer`:957.

### zk-adhoc-b6 / MC-3: KEEP-B

Target `ZKDatabase.java`:341. Eviction drops a commit the follower has not applied; the observer never gets it.

**Root cause, read in the source:**
1. A follower forwards a commit before applying it: `fzk.commit` queues it (`Follower`:201, `FollowerZooKeeperServer`:110-112), then `om.proposalCommitted` (`Follower`:204).
2. `cacheCommittedPacket` adds the packet and evicts up to 5 at 0.8 of the limit, then down to a hard cap (`ObserverMaster`:377-398). One packet above 0.8 × limit can empty the queue, including itself.
3. An observer syncing now is positioned from the follower's applied state, which is behind the forwarded commit.
4. `startForwarding`'s "too far behind" check runs only if the queue has a head (`ObserverMaster`:294-305). Empty: it activates the observer directly (:330).
5. The next INFORM has a same-epoch gap. `ZKDatabase`:333-341 throws, after the txn is already in the tree.

**Trigger:** `observerMasterPort` set, a packet above 0.8 × `zookeeper.observerMaster.sizeLimit` (default 32 MiB, `ObserverMaster`:86-87), and an observer (re)sync in the forward-to-apply window. Two ways to get the packet:
- Lower `sizeLimit` to about one packet. It is not in `zookeeperAdmin.md`; JMX can also set it (`FollowerBean`:63). The test uses 1024.
- Default limit with `jute.maxbuffer` raised above about 26.8 MB and a znode that large. Reproduced only at Level 1, with holds.

**Evidence (report):** Level 0, no holds, `sizeLimit=1024`: fired in 4 of 5 runs, about 1 per 300 observer restarts at about 50 writes/s, one JVM. Control with packets that fit: 0 fires, observer converges.

**Consequence:** by route, the observer cannot restart (gap on disk), or restarts and serves the hole: `exists(/z2)=false` after `sync()` for a committed znode while reporting the follower's zxid. Resync sends an empty DIFF, so nothing repairs it. Voters are unaffected.

**Recovery:** delete the observer's `version-2` (report did not test it). This matters because the silent route gives no signal that it is needed.

**Why B, and why low sureness:** the mechanism is clear and the outcome is severe, but the realistic path stacks three uncommon settings or an undocumented limit set below one packet. An owner who counts that as misconfiguration should drop it. It is the weakest of the four.

**Novelty:** JIRA `cacheCommittedPacket` and `committedPkts` hit only the feature issue ZOOKEEPER-3140; GitHub PR search 0. ZOOKEEPER-5088 has a different cause, and PR #2454 only seeds `proposedPkts`. Master has the same lines at `ObserverMaster`:295 and :381.

---

## Dropped findings worth a note

### The epoch class: 11/MC-1, MC-2 and 12/MC-2 are known

**11/MC-1 is the well-known class you asked about.** ZOOKEEPER-1653 describes the same window in nearly the same words; its `updatingEpoch` fix shipped only in 3.4.6. ZOOKEEPER-2354 (Patch Available, PR #1109 open) and ZOOKEEPER-4283 (Open, an identical workload on 3.6.3) track the port. There are field reports in 2354's comments (2019), and ZOOKEEPER-2653 fits. `Learner`:760 before :813 is still there on master.

- **Window:** from the snapshot file becoming valid to `currentEpoch.tmp` being opened (`AtomicFileOutputStream`:59). With no buffered commits that is microseconds, which is why the report aimed its SIGKILL with a file watcher: its 5/5 is reachability, not a rate. With commits, ZOOKEEPER-4785's reordering put `fzk.getZKDatabase().commit()` (`Learner`:804) inside it, so about one log fsync, typically milliseconds. I did not measure either. The DIFF route is newer than the tickets, but the state and fix are theirs.
- **Recovery:** `zookeeperAdmin.md`:527-535 (delete `version-2`, resync) is the documented answer, though it speaks of corruption, not epochs. On 2 of 3 peers at once it would risk committed data.

**11/MC-2:** the same state from a failed write. Without a restart it heals in milliseconds. With one, it is MC-1's state, and the report's own `testE` needed a latch to stop before resync.

**12/MC-2:** `Leader`:1482 clears the flag before the write at :1483, as ZOOKEEPER-4781's comment says. Read and confirmed; unfixed on master (:1482-1483). A one-line swap fixes it, and the report's control shows that.

### 12/MC-1 and 07/MC-2: real gap, injected timing

`getEpochToPropose` (`Leader`:1469-1502) has no shutdown check, and `setAcceptedEpoch` (`QuorumPeer`:2346-2349) is neither monotonic nor serialized. Both are real. But 12/MC-1 holds a handler 5 s until its `Leader` dies and latches writers, with no unhooked hit. 07/MC-2 needs three holds of 2-6 s against a natural window its report measured at 141-231 µs. An unusually slow fsync in a handler could stretch this; nothing shows it.

### 12/MC-3: Windows fallback runs on POSIX, but the trigger is unrealistic

`AtomicFileOutputStream`:88-93 has no platform check, so a failed rename deletes the target. It needs two rename failures with a successful delete, then a crash before the next write, and no durable txn in the current epoch. The one natural route to a failed rename with a successful delete is 12/MC-1's overlapping writers, which is in the row above.

### b5/MC-4: closest call among the b5 drops

`Learner`:618-628 never sets `syncSnapshot`, unlike SNAP at :617, so the only copy of a TRUNC-window commit sits in an unsynced snapshot. The report showed loss on default ext4 through a filesystem shutdown. This is ZOOKEEPER-2310's mechanism; that issue was closed via ZOOKEEPER-2872, which covers SNAP only. Dropped because it multiplies a race the workload forces with holds (a follower ahead of an uncommitted txn on the same leader) by a power-loss window of up to about 30 s, for one follower and a recoverable result. A one-line fix exists, so it may be worth a note on 2310.

### b6/MC-2: a residual of ZOOKEEPER-5088

Confirmed by reading: `FollowerZooKeeperServer`:110 removes the txn from `pendingTxns` when committed, and PR #2454 seeds only from `pendingTxns`, so a commit read in the sync window but not yet applied stays uncovered. Dropped because Level 0 missed in 25 cycles, Level 1 holds the apply, and under load `committedPkts` fills within milliseconds and the head check disconnects the observer instead (the report saw 2 such disconnects). Useful as a review comment on #2454, not as its own bug.

---

## Side findings (off-target, not kept; decide separately)

These fail bar 1 for their case, so they are not in the totals. S1 is the one to look at first.

**S1 (from 10/MC-1): a write whose body fails to deserialize duplicates a zxid, default configuration.**
- `PrepRequestProcessor`:782 parses before allocating. The catch at :928-936 builds the error header with `zks.getZxid()`, the previous txn's zxid, and :766 reuses it. `ProposalRequestProcessor`:82-85 proposes anything with a header.
- `Leader.propose` puts it back in `outstandingProposals` (`Leader`:1330). If that zxid was already committed, its ACKs are discarded (:1081-1087), so it stays forever, and `tryToCommit` refuses every later zxid (:978).
- Report's run log, `flushDelay=0`: `lastCommitted` stuck with `outstandingProposals` growing, later writes absent, for the 19 s observed. If the zxid was still outstanding, the follower reaches `FollowerZooKeeperServer`:108 and exits with code 12 by default.
- **Why it fails here:** the target at `ObserverMaster`:371 is reached only under LOG_ONLY (`ZKTestCase` default, or `ExitHandler.LOG_ONLY` for embedders) with `observerMasterPort` and `flushDelay=300`, and that route heals by resync. No single configuration gives both the target and severe harm.
- **Weakest point:** the commit stall was seen only in that test setup (LOG_ONLY, observer master). From reading the code neither matters for the leader's stall, but no plain-default run exists. I read no code that ends the stall short of a leader change, and did not prove there is none. The report did not check the client's reply either.
- **Novelty:** JIRA `marshalling`, `ErrorTxn`, `duplicate zxid`, `next pending txn`, `malformed` and GitHub PR search show no report. ZOOKEEPER-5112 is a different malformed request; ZOOKEEPER-4418 has the same follower symptom with no root cause. Master has the same line (`PrepRequestProcessor`:989). CVE databases were not checked.
- **Handling:** any connected client could send this without special rights, as far as I read. If you take it upstream, it looks like a case for the ASF security list, not a public JIRA.

**S2 (from 10/MC-2):** `Leader.tryToCommit` removes the proposal (:998) before `getDesignatedLeader` (:1013), which throws on an empty candidate set (:936-938). The report's three real JVMs: a follower exits 12, the leader's `CommitProcessor` dies, a replica ends up without an unacknowledged znode, with digest mismatch logged. It needs `reconfigEnabled=true`, `standaloneEnabled=false` and a reconfig to the leader alone on a changed quorum port.

**S3 (from 13/CR-7):** after an aborted observer SNAP, `ZooKeeperServer`:946-947 clears the database, nothing reloads it (`FastLeaderElection`:864-868), and `roZk.shutdown()` fast-forwards the log onto the empty tree and sets `initialized` (`ZKDatabase`:304-306). The next DIFF leaves the observer at the voters' zxid without snapshot-only data, surviving restart. Needs `readonlymode.enabled`, an observer, voters lost mid-SNAP and differing log windows. ZOOKEEPER-2389 is related (read-only observer does not load its log) but reports only refused connections.

**S4 (my reading, not tested, no report):** the guard at `ZKDatabase`:333-335 passes any gap crossing an epoch. A TRUNC sync that receives new-epoch txns through `queueCommittedProposals` (`LearnerHandler`:868-872) could, on losing its unsynced snapshot, skip them with no exception: b5/MC-4 made silent. Unverified.

---

## What could not be checked

- **Production frequency** of all four KEEPs. Every rate is a stress figure or an aimed one.
- **Reproductions:** nothing was rerun. Level 0 claims rest on the reports, apart from the test source I read for 11/MC-3.
- **Recovery by wiping** was not tested in any report for these findings; I cite the documented procedure only.
- **Whether a differently worded report exists:** all negatives are bounded. Mailing lists not searched; GitHub search was five unauthenticated queries by title; several JQL lists were judged by title. ZOOKEEPER-2162 and 3182 were judged by title or a partial read.
- **Off-target claims** (S1 to S4) were read in code but not established as bugs on a plain default cluster.
- **Report details not re-derived:** 11/CR-4 and CR-5's filesystem matrix, 13/CR-4's mechanism beyond the report text, the tail of 06/MC-1 and MC-2, b4/MC-2.
