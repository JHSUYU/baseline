# Independent verification, batch 6 (Solr 07, 09, 10, 13, 14, 19, 21, 31, 38)

Reviewed 2026-11-05 against the unmodified source: apache/lucene-solr `faca81bff1` (branch_8_11 tip, Solr 8.11). solr-adhoc-05, 39 and 40 finished later and were added on 2026-11-06 (their sections are at the end).

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands and without a source patch or injected timing in the code the trigger depends on; a realistic trigger, not designed, not a test artefact, not already reported; and severe.

## How this was checked

- Findings came from `post_run.py report solr <case>` and from each run's `confirmed-bugs.md` (command-log lines filtered out). Every finding marked REPRODUCED or MASKED was reviewed; ENV_LIMITED ones get one line.
- The decisive code was read at `faca81bff1` with `git show`. Line citations are at that commit. apache/solr `main` was read from raw.githubusercontent.com where a fix status mattered.
- **No test was run.** Hit rates, frames and consequences come from the run reports. For 07/CR-2 I also read the repro test source (`repro/CR-2/SpeculaAdhocCR2ElectionLeakTest.java`) to see what its hook does.
- Web: Apache JIRA REST and the GitHub search API both answered. Novelty is a bounded negative: JQL text search is coarse and broad queries were judged by title. GitHub was searched only for 07/CR-2. For findings that fail on target or severity, novelty was not searched beyond what the runs recorded.
- Nothing under `/bulk/GraphChecker` or `/bulk/wt` was read.

## Summary

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| 07 / CR-2 | DROP, known | Orphan election znode after unload during `joinElection` leaves the shard leaderless, and FORCELEADER cannot fix it. It is severe and real, but SOLR-18558 (Open, 2026-10-20) reports the same consequence and names this race family and the `core == null` early return as its suspected cause | medium-high |
| 07 / MC-1 | DROP, known | SOLR-17700 (`unload` takes no `pendingCoreOps`), fixed in 9.9 and not backported | high |
| 21 / MC-1 | DROP, known; assert target | same root cause as 07/MC-1 (SOLR-17700); needed a test-held window | high |
| 07 / MC-2 | DROP, not severe | deferred register vs DELETEREPLICA UNLOAD: one ERROR log and a DOWN publish the Overseer ignores; the cluster ends correct | high |
| 07 / MC-3 | DROP, not severe | shutdown during register: error noise and a redundant DOWN on a node that is already going down | high |
| 09 / MC-1 | DROP, not severe | Overseer QUIT during DELETEREPLICA: a wrong failure reply after about 60 s; the next Overseer removes the replica | high |
| 09 / MC-2 | DROP, narrow, not severe | PRS only; the lasting form needed an injected ZK write error (Level 2); a retry removes the replica. Counter reset is SOLR-16453 | medium-high |
| 09 / MC-3 | DROP, unrealistic, not severe | HDFS plus two conflicting admin commands on one replica; one fails and a retry works | high |
| 09 / MC-4 | DROP, non-default, not severe | legacyCloud=true; designed legacy re-registration; a retry works | high |
| 09 / CR-2 | DROP, off-target | does not reach DRC:278; early "success" of count-based delete; fixed in main (passes `shardId`) | high |
| 09 / CR-3 | DROP, not severe | misleading error (self-catch and rewrap) | high |
| 09 / CR-4 | DROP, masked, needed a patch | target not reached at Level 0; Level 3 source patch | high |
| 10 / MC-1 | DROP, known | SOLR-18562 / apache/solr PR #5191 (open): the `router.start` fix-up writes an old snapshot | high |
| 13 / MC-1 | DROP, known; injected timing | same SOLR-18562 lambda; fired only at Level 3; the alias heals on the next document | high |
| 10 / MC-2 | DROP, not severe | an admin redefines a TRA as a plain alias mid-request; one rejected update, at most a wrong error code | high |
| 10 / MC-3 | DROP, test-held, not severe | new Overseer's stale alias cache; 0 hits at Level 0; the retry succeeded | high |
| 13 / MC-2 | DROP, test-held, not severe | same stale-cache read; Level 3 only; the requester is told it failed; a resend works | high |
| 13 / MC-3 | DROP, test-held, non-default, not severe | `router.autoDeleteAge`; microsecond window stretched by a test stall; the document had aged out anyway | high |
| 13 / MC-4 | DROP, not severe | concurrent ALIASPROP `router.interval`; one 500, a retry succeeds | high |
| 10 / CR-3 | DROP, off-target | never reaches L117; same root cause as 39/MC-2 (G8, Aliases:315), which does reach its target | high |
| 10 / CR-4 | DROP, off-target, not severe | NPE at RoutedAliasUpdateProcessor:175 in place of a clear error | high |
| 14 / MC-1 | DROP, not severe | SPLITSHARD rejected when the leader's session expires; nothing left behind; resubmit works | high |
| 14 / MC-2 | DROP, not severe | graceful stop of the leader during SPLITSHARD; designed fail-safe (SSC:166 comment) | high |
| 14 / MC-3 | DROP, injected timing, not severe | Level 3 sleep; masked by the default `checkDiskSpace` | high |
| 14 / CR-2 | DROP, not severe | misleading error message | high |
| 19 / MC-1 | DROP, non-default, not severe | legacyCloud=true plus connection loss; one CREATE rejected and cleaned up | high |
| 19 / MC-2 | DROP, injected timing, non-default | Level 3 pause in ZkStateReader; legacyCloud | high |
| 19 / MC-3 | DROP, non-default, not severe | operator flips legacyCloud mid-CREATE; it fails cleanly | high |
| 19 / CR-2 | DROP, non-default, test-held | legacyCloud; a ~15 s outage without expiry; held event thread (real watch defect; see notes) | medium-high |
| 21 / MC-2 | DROP, assert target | with -da an NPE at CC:1766 fails one RELOAD; designed forced delete | high |
| 21 / MC-3 | DROP, assert target | real defect is in `unload`, not at the target (see notes) | high |
| 21 / MC-4 | DROP, assert target, test-held | held core construction; orphan core comes from `register` | high |
| 21 / CR-3 | DROP, assert target, PRS, Level 3 | source latches in ZkStateReader; 0/5 at Level 0; same root cause as 05/MC-3 (ZSR:2062) | high |
| 31 / MC-1 | DROP, non-default, not severe | PRS; FORCELEADER refused, but the shard heals after `leaderVoteWait` (about 163 s after the refusal) | high on mechanism; medium on tier |
| 31 / MC-2 | DROP, injected timing | Level 3 sleep plus a whole-ensemble outage; healed in 2.3 s | high |
| 31 / MC-3 | DROP, test-held, not severe | handler's ZK event thread paused; a retry succeeds | high |
| 31 / CR-1 | DROP, injected timing | pause hook added before SLEB:189-190; lasting effect (see notes) | high on rule 1 |
| 31 / CR-2 | DROP, ENV_LIMITED | Level 2 injection; transient wrong error | high |
| 38 / MC-1 | DROP, not severe | transient 503 for about 2.5 s; CloudSolrClient retry succeeded 3/3 | high |
| 38 / MC-2 | DROP, test-held, not severe | 4 s register delay via hook; transient 503 | high |
| 38 / CR-1 | DROP, known, not severe | SOLR-11685 (9.4 changed only 503 to 510) | high |
| 38 / MC-3 | DROP, ENV_LIMITED | Level 3 fault hook; transient 503 | high |
| 05 / MC-1 | DROP, test-held window | first-watch fetch with no data watch shadows a fresher lazy ref; the replica stays DOWN while ADDREPLICA reports success. Level 0: 0 hits. Level 1 held the reader's update lock and the CollectionRef monitor from the test | high on rule 1; the strongest 05 lead |
| 05 / MC-2 | DROP, injected timing | watched-to-lazy hand-off seen half done; Level 3 sleeps in ZkStateReader; probably closed in main by the SOLR-16257 restructure (inferred) | high |
| 05 / MC-3 | DROP, injected timing, PRS | conjunctive version/cversion skip test lets an older state.json win; Level 3; same site as 21/CR-3; still in main | high |
| 05 / CR-2 | DROP, injected timing | stale `/collections` snapshot `clear()`/`retainAll` drops a fresh lazy ref; Level 3 hold; 0/100 at Level 0; still in main | high |
| 05 / CR-1 | DROP, ENV_LIMITED, off-target | out-of-order Notification makes UnloadCoreOnDeletedWatcher delete a healthy replica; Level 3 only; does not reach ZC:1274 | high |
| 39 / MC-1 | DROP, not severe | DELETEALIAS of a routed alias while a commit/delete is in flight: that one request gets a 503 (Level 0/1, client-side chunk pause). The later failures are at RAUP:133, a different line, and follow from the admin deleting the alias | high |
| 39 / MC-2 | DROP, contrived trigger | Level 0 and lasting: the routed alias keeps its `router.*` props with no list (Aliases:315), so every commit/delete to its collection 503s at RAUP:247 until an admin deletes the alias. But both routes are odd admin sequences on unguarded APIs (RENAME a member collection, which already breaks routing by itself; or an alias named after a member). Same root as 10/CR-3; no JIRA; unfixed in main | medium (an owner could call it KEEP-B) |
| 39 / MC-3 | DROP, injected timing | same orphan-props state via TRA auto-delete plus a CREATEALIAS overwrite; Level 3 sleep in the async task | high |
| 39 / CR-1 | DROP, masked | `assert` in `Aliases.toJSON`:118 fires only with -ea. With -da the Overseer writes an empty aliases.json, the same end state as deleting the routed alias | high |
| 40 / MC-1 | DROP, known, test-held, not severe | SOLR-18559 (Open): a node's stale alias cache rejects routed updates; Level 1 held n2's `AliasesManager` monitor; heals when the watch applies | high |
| 40 / MC-2 | DROP, known, injected timing | the erased-alias case of SOLR-18562 (Open, PR #5191). Only Level 3 erased the concurrently created alias; at Level 1 the same lost update hit a sibling TRA's `router.start` on its own | high |
| 40 / MC-3 | DROP, known, test-held window | aliases watch not re-armed after ConnectionLoss (ZSR:2312, 2317-2319). Lasting until session expiry or restart, but SOLR-18559's description already names it. The repro needed a SocketProxy hold of the watch event plus a ~146 s whole-ensemble outage | high on rule 1; mechanism real |
| 40 / CR-1 | DROP, not severe | CREATEALIAS adopting an existing collection sets `routedAliasName` (AliasCmd:94-98) before writing the alias (CreateAliasCmd:153-155): in-flight writes get a 500 for that short window. Level 0 | high |

Totals: 55 findings (42, plus 5 from 05, plus 4 each from 39 and 40); 0 KEEP-A, 0 KEEP-B, 55 DROP.

## Root-cause groups

- **G1, `CoreContainer.unload` ignores `pendingCoreOps`** (SOLR-17700, fixed in 9.9): 07/MC-1 and 21/MC-1. 07/MC-2 is the same unload on the startup-register path, which holds no op in main either.
- **G2, register/unregister are not serialised around the election context** (`ZkController`:1546-1552 vs :1760-1763; `ElectionContext`:61-63): 07/CR-2. This is SOLR-18558's suspected-cause family.
- **G3, `TimeRoutedAlias` `router.start` fix-up writes a stale snapshot** (`TimeRoutedAlias.java`:377-387, SOLR-18562): 10/MC-1, 13/MC-1, 40/MC-2.
- **G4, `MaintainRoutedAliasCmd` reads the alias cache with no `update()` first** (`MaintainRoutedAliasCmd.java`:108-110): 10/MC-3, 13/MC-2. Its data-node twin is G9.
- **G5, cached leader flag disagrees with the live or local leader** (`CollectionsHandler.java`:1475-1477 ignores liveness and reads the cached view; `DistributedZkUpdateProcessor.java`:1009-1025 re-reads only the local flag): 31/MC-1, MC-2, MC-3, CR-1, CR-2 and 38/MC-1, MC-2, MC-3, CR-1.
- **G6, legacyCloud split view between Overseer and node** (`Overseer.java`:1007-1010, `CoreContainer.java`:1327-1330): 19/all. Legacy mode was removed in 9.0, so the mechanism does not exist in main.
- **G7, ZkStateReader publishes a cluster state older than one a reader already matched, and `register` re-reads it** (ZC:1266-1274; ZSR:610-617, 724/732, 1410, 2009-2010, 2050-2052, 2062): 05/MC-1, MC-2, MC-3, CR-2 and 21/CR-3. One defence-in-depth fix (register uses the `DocCollection` that satisfied `waitForState`, or force-refreshes before throwing at 1274) covers all of 05's on-target findings. The harm is completed through the same `ZkContainer.registerInZk` swallow as G1 (ZkContainer.java:222-231): the failed register is logged, the replica published DOWN, and nothing retries.
- **G8, deleting an alias prunes emptied lists but keeps their properties** (`Aliases.java`:302-315): 10/CR-3, 39/MC-2, MC-3, CR-1. The orphaned props of a routed alias make `RAUP.wrap` build a routed processor with no list behind it (RAUP:131-133 passes, RAUP:245-247 throws). Unfixed in main (main Aliases:328, 339). No JIRA found.
- **G9, a node's alias cache goes stale and RAUP trusts it** (RAUP:129-134 reads only `getAliases()`; `AliasesManager.process` ZSR:2312, 2317-2319 does not re-arm the watch after ConnectionLoss): 40/MC-1, MC-3, both covered by SOLR-18559's text. The lost-watch half follows the same pattern as 19/CR-2 (`loadClusterProperties` ZSR:1176-1178). Main still only logs in the same catch for aliases (main ZSR:2108-2111), and also for collection-list and live-node watchers (main ZSR:1326-1328, 1392-1394, 1427-1430).

---

## solr-adhoc-07 (target `ZkController.java`:1326)

Target confirmed at the pinned commit: `try (SolrCore core = cc.getCore(desc.getName()))` at ZC:1317, `throw new SolrException(SERVICE_UNAVAILABLE, "SolrCore is no longer available to register")` at ZC:1326. `ZkContainer.registerInZk` swallows it (ZkContainer.java:222-231: publish DOWN, log).

### CR-2: DROP, known (SOLR-18558); the strongest finding in this batch

Walk, all read at `faca81bff1`:
1. `ZkController.joinElection` builds a new `ShardLeaderElectionContext` and puts it into `electionContexts` (ZC:1547-1551) **before** `LeaderElector.joinElection` creates the ephemeral-sequential znode and sets `context.leaderSeqPath` (LeaderElector.java:260-265).
2. A concurrent `CoreContainer.unload` removes the core from SolrCores (CC:1864), then calls `ZkController.unregister` (CC:1893). It removes that context and calls `cancelElection()` (ZC:1760-1763).
3. `leaderSeqPath` is still null, so `ElectionContext.cancelElection` only logs "cancelElection skipped as this context has not been initialized" (ElectionContext.java:53, 61-63).
4. The register thread then creates the znode (LE:260), and `register` throws at ZC:1326 because `getCore` returns null. Its catch calls `unregister` again (ZC:1370-1372), but the context is already gone from the map, so nothing deletes the znode.
5. When the real leader goes, the orphan's `ElectionWatcher` (LE:332-350) makes it head. `ShardLeaderElectionContext.runLeaderProcess` returns at SLEC:98-101 ("shutdown or removed") without cancelling. The next replica watches only the orphan (LE:144-155), so it is never notified.
6. FORCELEADER cannot repair it: `forceLeaderElection` (CollectionsHandler.java:1473-1513) only raises terms and polls for an active leader. It never touches the election queue. The shard stays leaderless until node B's ZK session ends (restart or expiry), or until someone deletes the znode by hand.

Repro (from the report, test source read): Level 0, 60 attempts: the target fired once and nothing leaked. Level 1: the hook `ZkContainer.testing_beforeRegisterInZk` parks the register thread for a calibrated offset of up to a few ms relative to an in-JVM `cc.unload` (test lines 113-138). That aligns the start; it does not hold the put-to-create window open. The leak appeared once in 150 attempts, then again in a rerun. The shard was leaderless for 60 s and updates failed with "No registered leader". The control elected a new leader in 2.5 s.

Against the bar:
- **Rule 1:** the target is reached with no hook (Level 0). The leak, which is the severe part, was seen only with test-aligned timing. The window itself is natural: one ZK create round trip.
- **Trigger realism:** something must unload a core while it is between ZC:1551 and LE:265. Possible sources are a CoreAdmin UNLOAD, a DELETEREPLICA UNLOAD after the shard lock is lost, or, most plausibly, a DELETEREPLICA landing during the deferred startup register of a restarting node. Rare, but it needs no special mode.
- **Severity:** lasting loss of availability for updates on the shard, which FORCELEADER cannot repair. That would be KEEP-B.
- **Novelty, why DROP:** SOLR-18558 (Open, created 2026-10-20, affects 10.0) is titled "Stale leader election znode left after DELETEREPLICA blocks the remaining replica from becoming leader". Its suspected causes include "ZkController.unregister vs register: … finds no context and cancels nothing. The registration thread then creates the election znode and context … and nothing cancels them afterward", and the `runLeaderProcess` `core == null` return without `cancelElection()`. Its proposed fix 1 (cancel there) would also clear CR-2's orphan. CR-2's exact sub-window is slightly different: unregister finds the context but `leaderSeqPath` is null, whereas the ticket has unregister finding no context at all. The defect, consequence and fix site are the same. The run called SOLR-18558 a different mechanism; I disagree. CR-2 is in effect a reproduction of SOLR-18558's unconfirmed suspected cause, which may be worth offering to that ticket. That is the owner's call; nothing was posted.
- **Main:** the gap is unchanged. Main `ZkController`:1845-1846 still puts the context before the join, and main `ElectionContext`:64 still skips an uninitialised cancel. SOLR-17700's lock does not cover it: main's startup load releases the pending op before the background `registerInZk` (main CC:988-1004).
- Other searches (JIRA: `text ~ "cancelElection"`, `"election node" AND unload`, orphan + election, "no leader" + unload/deletereplica; GitHub: `repo:apache/solr cancelElection`, register/unregister race, `SOLR-18558`; `repo:apache/lucene-solr cancelElection uninitialized`) found SOLR-6159 (added the null-path no-op), SOLR-17077, SOLR-7198 and SOLR-18525, all different.

### MC-1: DROP, known

CREATE holds `pendingCoreOps` (CC:1343-1347) while it registers (CC:1268 → ZkContainer:241). `unload` (CC:1837-1893) never takes it. This is SOLR-17700, fixed in 9.9 (apache/solr PR #3260); main `unload` takes `waitAddPendingCoreOps` (main CC:2073-2075). The consequences were real (CREATE returns 0, `core.properties` re-persisted at CC:1345, a restart deletes an instance dir the UNLOAD asked to keep), but the defect is known and fixed in main.

### MC-2: DROP, not severe

Deferred startup register vs DELETEREPLICA UNLOAD, Level 1 (existing hook). The report itself found the cluster ends correct: DELETEREPLICA returns 0, and the late DOWN is ignored. That leaves an ERROR log only. This ordering (unload completes before `joinElection`) does not leak: the catch at ZC:1370-1372 cancels a context whose `leaderSeqPath` is set.

### MC-3: DROP, not severe

`isShutDown` is checked once (ZkContainer.java:211). Shutdown during register gives a logged ERROR and a DOWN publish from a node that is going down anyway; it re-registered normally on restart.

---

## solr-adhoc-09 (target `DeleteReplicaCmd.java`:278)

Read: DRC:248-252 (UNLOAD only to a live node), :254-266 (two 30 s `waitForCoreNodeGone` waits), :275-284 (the throw at 278-279 is inside the try, so the catch at :282-283 rewraps it), :153/:158 (`shardId` computed but the request's null `shard` passed); OCMH:432-448 (a null slice counts as gone); Overseer:447-453 (QUIT closes the collection processor on the state-updater thread); OTP:380-386; ZkStateWriter:131-145, :211-214, :232-235, :284-285; SliceMutator:131-134; ReplicaMutator:247.

- **MC-1:** ADDROLE overseer during DELETEREPLICA. `OTP.close()` waits for the running DELETEREPLICA, which waits for state updates that the blocked updater cannot apply. The client gets a failure after about 60 s; the next Overseer applies the delete. A wrong reply and a transient stall. Related to SOLR-17421 (same QUIT path, different defect).
- **MC-2:** PRS only. The Level-0 effect is a delayed removal (counter reset, SOLR-16453, fixed in 9.1). The lasting "dropped deletecore" form needed an injected ZK write error. A retry removes the replica. Main still calls `callback.onWrite()` in `finally` (main ZkStateWriter:160-161). By reading, that could drop other buffered non-PRS updates on a failover; not reproduced.
- **MC-3:** HDFS plus MOVEREPLICA without `shard` racing DELETEREPLICA of the same replica. Two conflicting commands; one fails.
- **MC-4:** legacyCloud=true (removed in 9.0, SOLR-12823). The restarting node re-adds its core, which is legacy behaviour; DELETEREPLICA reports failure; a retry works.
- **CR-2:** does not reach 278. Count-based delete passes `shard=null`, so the wait returns at once (OCMH:432-448). Main passes `shardId`.
- **CR-3:** a misleading error only.
- **CR-4:** target not reached without a Level 3 patch.

JIRA ("Could not remove replica", "corenode gone", deletereplica + overseer + quit, PRS + onWrite): nothing matching. GitHub not searched for 09.

---

## solr-adhoc-10 and solr-adhoc-13 (targets `MaintainRoutedAliasCmd.java`:117, `RoutedAlias.java`:350)

Read: MRAC:72-174, TRA:365-392 and 599-626, RA:85-90 and 325-410.

Severity, common to all on-target findings: the end effect is one update rejected with HTTP 500 and the client told. No acknowledged document is lost or misrouted. No finding creates a collection left out of the alias while the requester is told it succeeded. A resend succeeds.

- **10/MC-1, 13/MC-1 (G3):** `(a) -> aliases.cloneWithCollectionAliasProperties(aliasName, props)` ignores its argument and writes an old snapshot (TRA:386-387). This is SOLR-18562 (Open, 2026-10-22), which quotes this lambda; PR #5191 is open. 13/MC-1 also fired only at Level 3, and the alias heals on the next document (MRAC:142-156).
- **10/MC-2:** after an admin redefines the alias, `fromProps` returns null (RA:87-89) and L117 throws SERVER_ERROR where the BAD_REQUEST at L111-113 was meant. At most a wrong error code.
- **10/MC-3, 13/MC-2 (G4):** both needed the new Overseer's alias watch held or slept. 13/MC-2's `calcAdd` (TRA:599-612) creates next(head) instead of the requested collection, and the requester gets a 500.
- **13/MC-3:** non-default `router.autoDeleteAge`; the async ENSURE_REMOVED (MRAC:125-137) is unlocked, but the window is microseconds and was stretched by a test stall.
- **13/MC-4:** a concurrent ALIASPROP of `router.interval`; the Overseer follows the new interval; one 500.
- **10/CR-3, CR-4:** off-target (see notes).

---

## solr-adhoc-14 (target `SplitShardCmd.java`:167)

The guard at SSC:164-168 is a deliberate fail-safe; its comment at :166 reads "we just got to know the leader but its live node is gone already!". Every route gives one rejected SPLITSHARD with no sub-shards left behind, and a resubmit works.
- MC-1: 1/17 at Level 0.
- MC-2: 1/120.
- MC-3: needed a Level 3 sleep and is masked by the default `checkDiskSpace`.
- CR-2: a misleading message.

---

## solr-adhoc-19 (target `CoreContainer.java`:1330)

`Overseer.isLegacy` defaults to false (Overseer.java:1007-1010). CC:1327-1330 throws when the node sees non-legacy and `coreNodeName == null`. That only happens when the Overseer has created cores in legacy mode, so every route needs `legacyCloud=true`, which is deprecated and was removed in 9.0. Main CC:1547 throws "coreNodeName missing" unconditionally. The outcomes are a rejected CREATE that is cleaned up and works on retry (MC-1, MC-3), or need a Level 3 pause (MC-2) or a held event thread (CR-2).

---

## solr-adhoc-21 (target `CoreContainer.java`:1765, a Java assert)

The target is `assert replica != null;`. With assertions off, as in production, it does not fire. The next line, `replica.getType()` at CC:1766, throws an NPE, which is caught at CC:1779-1781, recorded in `coreInitFailures`, and wrapped as "Unable to reload core". So the production consequence never reaches the target line, and all five findings fail rule 1. The assert is still in main (main CC:2004).
- MC-1 is G1 (SOLR-17700) and needed `TestInjection.newSearcherHook` (0/60 at Level 0).
- MC-2: the forced delete after a lost UNLOAD is designed behaviour.
- MC-4 and CR-3 needed held construction or source latches; CR-3 also needs PRS.

---

## solr-adhoc-31 and solr-adhoc-38 (targets `CollectionsHandler.java`:1477, `DistributedZkUpdateProcessor.java`:1023)

38's frame reads 1025: the `throw new SolrException(SERVICE_UNAVAILABLE, …)` statement runs from :1023 to :1025, and it is the only throw with that message (:1021-1026). That is the target.

- **31/MC-1:** in PRS mode, `Replica.getState()`/`isLeader()` and `Slice.getLeader()` read PRS only. `preClose` skips `publishNodeAsDown` when ZK is disconnected (ZC:612-616). The next candidate's clear (SLEC:115-120 → `SliceMutator.setShardLeader`:144-179) edits replica props that PRS readers ignore. So the guard at CH:1475-1477, which never checks liveness, refuses on a leaderless shard. Not kept: PRS is non-default, and the shard heals when a survivor wins after `leaderVoteWait` (default 180 s; observed about 163 s after the refusal). FORCELEADER exists to shortcut that wait, so the harm is a refused shortcut. An owner who weights a 3-minute leaderless window more heavily could call it KEEP-B. JIRA (FORCELEADER/"force leader" with PRS; "already has an active leader") found no report; the nearest, SOLR-18570, is a different mechanism.
- **31/CR-1:** a lasting bad state: state.json names a non-elected replica ACTIVE+leader, updates get 503 at DZUP:1000-1004, and FORCELEADER refuses for more than 60 s. But it was reproduced only with a pause hook added before SLEB:189-190, so it fails rule 1. The hook-free attempt got `SessionExpiredException` and dropped the message.
- 31/MC-2, MC-3, CR-2 and 38/MC-1, MC-2, MC-3 are transient, injected or held; see the table.
- **38/CR-1** is SOLR-11685.

---

## solr-adhoc-05 (target `ZkController.java`:1274)

Added 2026-11-06. Same method as 07, one guard earlier. `register` waits until `waitForState` sees its replica (ZC:1266-1271), then re-reads the published cluster state (ZC:1272) and throws "replica is removed from clusterstate" if the replica is absent (ZC:1273-1274). Every finding is a way for node N's `ZkStateReader` to publish, between those two reads, a state that lacks a replica present in ZooKeeper. All mechanisms below were read at `faca81bff1` (`solr/solrj/.../ZkStateReader.java`, "ZSR"). Repro levels and outcomes come from the run's `confirmed-bugs.md`.

Consequence, common to all four on-target findings: `ZkContainer.registerInZk` swallows the throw (ZkContainer.java:222-231), publishes DOWN, and nothing calls `register` again. The replica stays DOWN outside the election until a reload, session expiry or restart, while ADDREPLICA reports success (MC-1) or CREATE times out (CR-2). That is a lasting loss of redundancy, so severity would pass. All four fail rule 1.

- **MC-1 (first watch shadows a fresher lazy ref).**
  - Mechanism: the first `StateWatcher.refreshAndWatchChildren` fetches state.json with **no data watch** (`fetchCollectionState(coll, null, …)`, ZSR:1408-1410).
  - `updateWatchedCollection` installs it into an empty slot by `putIfAbsent` with no version check (ZSR:2050-2052).
  - `constructState` lets watched entries shadow lazy ones (ZSR:610-617).
  - So r1's older fetch hides the live lazy ref through which r2's `waitForState` already saw r2.
  - Trigger: two concurrent ADDREPLICAs of different shards to a node that hosts nothing of the collection. Realistic, and ADDREPLICA takes a shard-level lock.
  - Repro: Level 0 control: 0 hits. Level 1: the existing `testing_beforeRegisterInZk` hook **plus the test holding the monitors of the reader's `getUpdateLock()` and the published lazy `CollectionRef`**, which parks r1 before `constructState` and r2 inside `waitForState`. That is a test-held window inside the code the trigger depends on, so it fails rule 1. It hit on attempt 2. The run also found a natural mask: if r1 is the new shard leader, `getLeader`'s temporary watcher leaves a data watch armed that refreshes the entry first.
  - Main: the same no-watch first fetch (main ZSR:1349) and install-when-empty (main ZSR:298-301) remain, and `register` still re-reads (main ZkController:1453-1461).
  - JIRA: `"replica is removed from clusterstate"`, `updateWatchedCollection`, `LazyCollectionRef` found nothing matching. SOLR-16257 (fixed 9.1) is the nearest, a different interleaving. Bounded negative.
  - Not kept, but it is the best lead in 05 if someone wants to try a hook-free stress run.
- **MC-2 (half-done watched-to-lazy hand-off).**
  - Mechanism: `removeDocCollectionWatcher` removes the watched entry (ZSR:2009) and only then puts the lazy ref (ZSR:2010), under the map's per-key lock only.
  - `refreshCollectionList` skips adding a lazy ref while `collectionWatches.containsKey` is still true (ZSR:735), so a `constructState` in between publishes no entry.
  - Repro: Level 3, six `Thread.sleep` hooks patched into ZkStateReader; Level 0 did not trigger. Fails rule 1.
  - Main moved the cached state into the watch entry (SOLR-16257), which probably closes this window. I inferred that from reading and did not test it.
- **MC-3 (PRS skip test is conjunctive).**
  - Mechanism: the skip at ZSR:2062 requires *both* the znode version and the PRS cversion to be no newer, so an older state.json carrying a newer cversion replaces a newer entry (ZSR:2068).
  - Needs PRS, which is non-default.
  - Repro: Level 3 pauses in ZkStateReader; Levels 0 and 1 got 0/20. Fails rule 1.
  - Same site and root cause as **21/CR-3** (merged).
  - Still in main: main ZSR:315-316 accepts the new state if `oldZ < newZ || oldC < newC`.
- **CR-2 (stale `/collections` children snapshot).**
  - Mechanism: `refreshCollectionList` reads the children (ZSR:718) and applies them later with `clear()` (ZSR:724) or `retainAll` (ZSR:732). Nothing orders this against the lazy ref that `removeDocCollectionWatcher` writes (ZSR:2010).
  - Repro: Level 3, a hook holds the children-watcher thread; 0/100 at Level 0. The run itself calls the natural window microseconds wide. Fails rule 1.
  - Still in main (main ZSR:681, 689).
- **CR-1 (ENV_LIMITED).**
  - Mechanism: an out-of-order `Notification` hands `UnloadCoreOnDeletedWatcher` a pre-replica snapshot, and it unloads and DELETECOREs a healthy replica.
  - Off-target: it does not reach ZC:1274, and it was seen only with a Level 3 sleep in `Notification.run`.
  - The consequence is destructive (index deleted). It belongs with the off-target notes below as a separate lead, not verified by me.

Overlap with 07/21: the target method is the same as 07's, and the harm comes through the same `registerInZk` swallow as 07/MC-1. The root causes are different: here a cache regression in ZkStateReader, there `unload` taking no lock. 21/CR-3 merges into 05/MC-3. 19's cache findings (CR-2, MC-2) concern `loadClusterProperties`, a different cache; no merge.

---

## solr-adhoc-39 (target `RoutedAliasUpdateProcessor.java`:247)

Added 2026-11-06. Target read at faca81bff1: `lookupShardLeadersOfCollections` takes a fresh `getAliases()` (RAUP:244), gets the alias list (:245), and throws `newAliasMustExistException` when it is null (:246-247). That exception is a 503 raised at `RoutedAlias.java`:72. Reached from `processCommit`/`processDelete`.

- **MC-1 (alias deleted mid-request): DROP, not severe.** `wrap` checks props against one snapshot (RAUP:131); commit/delete re-reads later (:244), and nothing pins the snapshot. Reproduced at Level 0/1 by pausing a chunked request body on the client side. The 503 text ("appears to have been removed during request processing") shows the developers expected this case. The outcome is one rejected request after an admin deleted the alias. The follow-up failures the run saw are at RAUP:133 (off-target): member collections keep `routedAliasName` after DELETEALIAS, which is how 8.11 behaves when a routed alias is deleted and its collections are not.
- **MC-2 (orphan router props): DROP, contrived trigger, medium sureness.**
  - Root cause read in source: the REMOVE branch removes the deleted alias's own props (Aliases:304) and drops any list that became empty (Aliases:315), but never removes the dropped aliases' props.
  - The `assert` in `toJSON` (Aliases:117-118) shows the intended rule: no props without a list.
  - `cloneWithRename` guards only a routed *source* name (Aliases:351-356).
  - Result: `getAliasProps` passes (RAUP:131-133) and RAUP:247 throws for every commit/delete. Per the run's CR-1 control, adds fail too, at `TimeRoutedAlias.parseCollections`:326. It is lasting: nothing re-adds the list, and the fix is an admin DELETEALIAS of the routed alias.
  - Reproduced at Level 0 through the public API, so rule 1 holds.
  - Why I still drop it: both routes are admin misuse of unguarded APIs. (2a) RENAME a routed alias's member collection; the run's CR-1 notes that the RENAME alone already breaks routing (`StringIndexOutOfBoundsException` at `TimeRoutedAlias.parseInstantFromCollectionName`:219). Then DELETEALIAS of the rename target. (2b) CREATEALIAS an alias named after a member collection that points at the routed alias, then delete it.
  - The more natural route is MC-3, and it needed injected timing.
  - Novelty: JIRA (`cloneWithCollectionAlias`; alias properties + deletealias; recent "routed alias" summaries) found nothing. Bounded negative. Unfixed in main (Aliases:328, 339).
  - If the owner reads "admin reshapes aliases, a later unrelated-looking delete leaves the routed alias un-writable" as realistic, this is a KEEP-B. It is the on-target form of 10/CR-3 (G8).
- **MC-3: DROP, injected timing.** The TRA auto-delete's alias update runs on `ocmh.tpe` outside the alias lock (MRAC:86-98, 127-136, per the run). It empties a list that a concurrent CREATEALIAS overwrite had just set; an unrelated DELETEALIAS then prunes it (G8). Fired only with an 8 s sleep patched into the async task; Level 0 lost the race the other way, leaving the alias pointing at a deleted collection (a separate anomaly).
- **CR-1: DROP, masked.** The last-alias case trips `assert collectionAliasProperties.isEmpty()` (Aliases:118) only with -ea. With -da `toJSON` returns null, the Overseer writes an empty aliases.json, and the end state equals a plain DELETEALIAS of the routed alias, as the run's control showed.

## solr-adhoc-40 (target `RoutedAliasUpdateProcessor.java`:133)

Target read: `getAliasProps` reads props only from the node's cached `getAliases()` (RAUP:131) and throws when they are empty (:132-133). `wrap` rethrows it as SERVER_ERROR (:122-123), which also stops SolrJ from retrying the inner 503.

- **MC-1: DROP, known.** SOLR-18559 (Open, 2026-10-21) is this site and mechanism; its PR #5189 is open. The repro was Level 1, with the test holding n2's `AliasesManager` monitor (a test-held window; 0/10 at Level 0). The cache heals when the watch applies.
- **MC-2: DROP, known (SOLR-18562), and it does not fire unaided.** I read SOLR-18562 (Open, 2026-10-22). It describes exactly this: the `router.start` fix-up's modification function returns the old snapshot, so its retry writes old aliases over a newer version and "any alias created … after the snapshot was taken is silently removed". The run cites the same lambda (TimeRoutedAlias:386) and says main still has it (main TimeRoutedAlias:418-421). Erasing a concurrently created alias, which is what reaches RAUP:133, took a Level 3 sleep in the `runAsync` lambda (0/20 at Level 0). At Level 1, though, the same lost update happened on its own against a sibling TRA's `router.start`. So the mechanism is reachable unaided, but the target outcome was not shown unaided. Not new: same lambda, same fix (G3).
- **MC-3: DROP, known and test-held; the mechanism is real and lasting.**
  - Source: `AliasesManager.process` re-arms the one-shot watch only through `getData(ALIASES, this, …)` (ZSR:2312). On `ConnectionLossException`/`SessionExpiredException` it only logs (ZSR:2317-2319), and no watch remains.
  - Only `refreshAliases` re-arms it, via `onReconnect` on session expiry (per the run, ConnectionManager:130-170).
  - **Persists:** yes. The run's adds failed 3/3 over 20 s; two later probe aliases never reached n2. An alias-named request through `HttpSolrCall` refreshed the cache once but did not re-arm the watch. It lasts until session expiry or restart.
  - **Fires without injection:** not shown. The repro held n2's watch event in a `SocketProxy` until a whole-ensemble ZK shutdown, then needed the outage to outlast `ZkCmdExecutor`'s retries (~146 s) without expiring the session (ZK cannot expire sessions while it is down). The proxy hold is a test-held window. Without it the window is between event delivery and the `getData` call.
  - **Novelty:** SOLR-18559's description names this exact path ("AliasesManager.process() catches ConnectionLossException … logs it, and doesn't re-register the watch") and calls the re-registration "a separate issue (the other watchers in ZkStateReader handle it the same way)". I found no separate ticket for the re-arm (JIRA: `AliasesManager` since 2025; watch re-register/lost phrasing), so it is reported in text but not filed on its own.
  - Same pattern as 19/CR-2 on the clusterprops watch (G9). Main has the same catch for aliases (main ZSR:2108-2111) and for the collection-list and live-node watchers.
- **CR-1: DROP, not severe.** Creating a routed alias sets the `routedAliasName` marker and waits for it (AliasCmd:94-98) before the alias is written (CreateAliasCmd:153-155). Writes to an adopted existing collection in that window get a 500. Level 0, 6/6. One rejected write per in-flight request, in a short window, with the client told. The "pre-created with the marker" variant is the user's own declaration.

---

## Notes: off-target defects seen in passing (not verified to the bar)

1. **21/MC-3, UNLOAD after a failed reload deletes files and leaves the core loaded.** A failed reload records `coreInitFailures` while the old core keeps serving (CC:1779-1781). `unload` then takes the init-failure branch (CC:1841-1855): it deletes the dirs, removes the descriptor and `core.properties`, and returns without closing or unregistering the loaded core. The run saw DELETEREPLICA return 0 with the core still serving, after a transient ZK outage during a RELOAD (Level 0, 2/2). The branch is unchanged in main (CC:2095-2108). This is the most promising lead for its own case. Nearest JIRA: SOLR-6232, SOLR-12889; neither matches.
2. **19/CR-2:** `ZkStateReader.java`:1176-1178 only logs a KeeperException when reading clusterprops, and re-arms no watch, so a same-session reconnect misses later cluster-property changes until expiry or restart. Default config; unchanged in main (:1199-1201).
3. **10/CR-3:** DELETEALIAS of a nested alias drops emptied compound aliases but keeps their properties (`Aliases.java`:302-315), and a re-created alias inherits them. Lasting; not searched.
4. **07/CR-2:** see above. It is a reproduction of SOLR-18558's suspected cause.
5. **05/CR-1:** UnloadCoreOnDeletedWatcher trusts a snapshot taken when the notification was submitted (ZkStateReader `Notification.run`) and deletes a healthy replica's index when the snapshot predates it. Level 3 only.
6. **G8 / G9 for a report, if wanted:** the Aliases:315 props orphan (10/CR-3, 39/MC-2) and the unre-armed watches in ZkStateReader (19/CR-2, 40/MC-3, and the other same-shaped catches in main) are real default-config robustness defects with lasting effects. They are dropped here only on trigger realism or rule 1.
