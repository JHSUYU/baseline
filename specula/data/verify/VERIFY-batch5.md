# Independent verification, batch 5 (HBase 20, 21, 22, 24, 28, 31, 34, 35, 37)

Reviewed 2026-11-05 against the unmodified source: apache/hbase `1790942bb2`, read with `git show 1790942bb2:<path>` from `src/hbase`, not from the case trees.

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands and without injected timing the trigger depends on; a realistic trigger, not designed, not a test artefact, not already reported; and severe.

## How this was checked

- The review was split into four independent passes: 21+22, 34, 35+37, and 20+24+28+31. I re-read the decisive lines of both KEEPs and the key lines of 34 and 37 myself, at the commit above. Short forms: NSM = `namespace/NamespaceStateManager.java`, MQM = `quotas/MasterQuotaManager.java`, CTP = `master/procedure/CreateTableProcedure.java`, SM = `master/ServerManager.java`, RST = `master/RegionServerTracker.java`, ATSM = `security/token/AuthenticationTokenSecretManager.java`, AMM = `master/ActiveMasterManager.java`, MAT = `zookeeper/MasterAddressTracker.java`, MTP = `ModifyTableProcedure.java`.
- **No test was run.** Hit rates, frames, consequences, and claims of "no hooks at level 0" come from the run reports (`confirmed-bugs.md`, `bug-severity.md`, the per-finding `investigation.md`). Raw repro logs and test sources were not read, except where stated.
- **No target is a Java `assert`.** All nine are explicit throws. Several frames name the continuation line of a multi-line `throw`, which is the same statement: NSM:133 for :130 (case 21), NSM:172 for :168 (22), RSRpcServices:1880 for :1878 (31), MTP:134/138 (20).
- Web: Apache JIRA REST answered, with some 503s and empty bodies on later queries in the 21/22 pass. **The unauthenticated GitHub search API was rate-limited (403) in most passes**, so PR coverage is partial. Where it worked, PR #8792 was read in full: description and diff file list. **Every novelty negative is bounded**: JIRA text search is coarse, broad queries were judged by title, and only the nearest issues were read in full.
- PENDING REPAIR and FALSE POSITIVE findings were not reviewed: 22/MC-7, 22/CR-8, 35/CR-1, 37/CR-4, 37/CR-6. 28/MC-3 is listed by the tool as PENDING REPAIR, but `confirmed-bugs.md` records it as FALSE POSITIVE after repair round 1; the report tool's status is stale.
- Nothing under `/bulk/GraphChecker` was read. Nothing was filed or posted. Nothing under `/bulk/specula-adhoc` was changed except this file.

## Summary

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| **21/MC-4 + 22/CR-1** (merged, G-D) | **KEEP-B** | the master's rebuild counts region replicas but live paths reserve primaries; every master restart inflates a replicated table's count, and valid create, restore and split are refused for good. Quota is off by default | mechanism high; tier medium |
| **31/MC-3** | **KEEP-B** | after a failover, a crashed RS with a pending SCP and a lingering znode is both online and dead; expiry becomes a no-op, so it stays in `onlineServers` forever and cluster shutdown never completes. Narrow failover window, test-chosen moments | mechanism high; tier medium |
| 21/MC-2, 22/MC-2 (G-B) | DROP, known | truncate leaves the count stale: HBASE-30483 (Open); PR #8792 (open) fixes exactly this | high |
| 22/MC-1 (G-B) | DROP, known and transient | same stale count plus a delete in flight; a retry after the delete succeeds | high |
| 21/MC-3, 22/MC-5 (G-C) | DROP, known | an N-way merge applies a fixed -1: HBASE-28559 (Open) | high |
| 21/MC-6, 22/MC-3 (G-F) | DROP, known | a split rollback leaks its +1: HBASE-28560 (Open); `onRegionSplitReverted` (MQM:646) has no caller | high |
| 22/CR-5 (G-F) | DROP, known and off-direction | merge side of HBASE-28560; it over-admits, so it never throws at the target | high |
| 22/CR-4 | DROP, known | "no reconciling chore" is why G-F lasts, not a separate defect | high |
| 21/MC-1, 22/CR-2, CR-3, MC-6 (G-A) | DROP, not severe (borderline) | restore and clone count the manifest's split parents and the MOB pseudo-region; a restore or clone at the quota boundary is refused, or the count is about 1 too high per table until restart. No JIRA found | mechanism high; severity medium |
| 21/MC-7, 22/CR-6 (G-H) | DROP, narrow and heals on restart (borderline) | a clone's rollback removes a live table's entry when it loses a race with a create; then that table's split and merge NPE and creates are over-admitted until restart. No JIRA found. Owner may overrule to KEEP-B | mechanism high; verdict medium |
| 22/CR-7 | DROP, masked | the run's own verdict; `TableProcedureWaitingQueue` serializes the two creates | high |
| 21/MC-5, MC-8, 22/MC-4 (G-E) | DROP, not severe and narrow | a master crash between the cache delta and the meta update; heals at the next restart; restore and create need a hook (create hit 0 of 9 unaided) | high |
| 20/MC-4 | DROP, unrealistic (borderline) | severe if hit (an acknowledged family and its directory are removed), but needs a test-held SHARED table lock to order the pids, plus `ProcedureExecutor.Testing` kill hooks; 0 of 16 rounds without hooks lost a family | medium-high |
| 20/MC-1 | DROP, unrealistic | stale `FSTableDescriptors` cache put; needs a held writer and a test DFS subclass that parks a reader; 0 hits in 167 unaided rounds | high |
| 20/MC-2 | DROP, duplicate and unrealistic | same root cause as MC-1 at L138; the FilterFileSystem stall is test-held; 0 of 181 unaided | high |
| 20/MC-3 | DROP, unrealistic | a deposed master that is still writing after its session timeout, with holds; 0 of 6 unaided; harm is a rejected modify | high |
| 24/CR-3 | DROP, not severe and non-default | false flush success only with `hbase.flush.procedure.master.threads` of 2 or more (default 1) and a test latch; data stays in the memstore and WAL; the ZK flush path is the legacy fallback | high |
| 24/MC-3, CR-2 | DROP, not severe | two injected ZK failures in a reset leave an empty `acquired/<P>`; one same-name flush stalls 60 s; its reset clears it | high |
| 24/MC-4 | DROP, not severe and known | false ERROR log; HBASE-13388 (same null read, "no functional impact") | high |
| 24/MC-1, MC-2, MC-5, CR-1 | DROP, masked | the runs' own verdicts; MC-1 is HBASE-13388, MC-5 is HBASE-29381 (PR #7078 open) | high |
| 28/MC-1, MC-2 | DROP, not reproduced | ENV_LIMITED; MC-1 needs a configured bind address plus descriptor exhaustion, MC-2 a stale resolver answer | high |
| 28/MC-3 | DROP, false positive | FALSE POSITIVE after repair round 1; nothing in case 28 is REPRODUCED | high |
| 31/MC-2 | DROP, unrealistic and not severe | needs the RS clock stepped back about 28 s across a restart (injected through EnvironmentEdgeManager); recovers in about 30 s | high |
| 31/MC-4 | DROP, not severe | hostname case mismatch after failover; recovery about 6x slower, then heals at session expiry | high |
| 31/MC-1 | DROP, masked | SCP recovers | high |
| 34/MC-1 | DROP, unrealistic | new key master drops a pending key; level 0 hit 0 of 676; level 1 holds the stop thread between ATSM:310 and :314 | high |
| 34/MC-3 | DROP, unrealistic | needs a failed `zkWatcher.start()` and no other running elector (0 of 60 with one running); Mockito ConnectionLoss | medium-high |
| 34/CR-3 | DROP, off-target | :160 never throws; the symptom is a DIGEST password mismatch. Real and severe on secure clusters: **side finding S1** | high |
| 34/MC-4 | DROP, not severe and narrow | needs an injected ZK create fault for about 15 s; only tokens issued in a 229-337 ms window are lost; a new token fixes it | medium |
| 34/CR-5 | DROP, needs a held window | 20-200 ms stall from a test subclass of `stop()`, a parked next master, a non-default 3 s roll interval; unharmed under normal timing | high |
| 34/MC-2 | DROP, not severe | real (288 of 300 at level 0), but it affects only a server already stopping; the client retries elsewhere | high |
| 34/MC-5 | DROP, not severe | a token loses its last seconds of a 7-day life; needs an 8 s held stall or clock skew | high |
| 34/MC-6 | DROP, not severe | rejected either way; only the reason text is wrong | high |
| 34/CR-1 | DROP, not severe | injected 4-8 s follower lag; heals; default client retries mask it | high |
| 34/CR-2, CR-4, CR-6 | DROP, masked (CR-4, CR-6 also off-target) | the runs' own verdicts | high |
| 35/MC-1 | DROP, unrealistic trigger; target harm not severe | needs a hand-written `Hbck.setRegionStateInMeta` call on meta; shipped HBCK2 never makes it; hbck1 is deprecated | medium-high |
| 37/CR-5 | DROP, needs a held window | double `AMM.stop` deletes the successor's znode; needed Mockito stalls on the delete, 0 of 42 unaided. Severe if hit | high |
| 37/MC-4 | DROP, known and needs a held window | unversioned stale-znode delete on restart: HBASE-17305 (Abandoned); held the delete 28-30 s, 0 of 5 unaided | high |
| 37/MC-5 | DROP, needs a held window | `master clear` versioned-delete ABA (every new znode has version 0); needed a TCP relay holding the delete about 30 s; 0 of 5 unaided | high |
| 37/CR-3 | DROP, off-target and needs a held window | L206 fired with the race removed too; 0 of 640 at level 0 | high |
| 37/MC-2, MC-3 | DROP, not severe | transient port-0 link on a status page; the designed 0 return (HBASE-26215) | high |
| 37/MC-1, CR-2 | DROP, masked | the runs' own verdicts | high |

Totals: 61 findings reviewed. 0 KEEP-A; 2 KEEP-B (3 findings, one pair merged); the rest DROP; 1 side finding.

## Root-cause groups

**Namespace quota (21, 22).** Merged across the two cases. Every member needs `hbase.quota.enabled=true` and an operator-set `hbase.namespace.quota.maxregions` or `maxtables`, so none can be KEEP-A. The groups:

- **G-A:** the manifest size counts split parents and the MOB pseudo-region: 21/MC-1, 22/CR-2, CR-3, MC-6.
- **G-B:** truncate leaves the count stale (HBASE-30483): 21/MC-2, 22/MC-2, MC-1.
- **G-C:** merge arity (HBASE-28559): 21/MC-3, 22/MC-5.
- **G-D:** the rebuild counts replicas: 21/MC-4, 22/CR-1. **KEEP-B.**
- **G-E:** a crash between the cache delta and meta: 21/MC-5, MC-8, 22/MC-4.
- **G-F:** rollback leaks (HBASE-28560): 21/MC-6, 22/MC-3, CR-5, CR-4.
- **G-H:** a clone's rollback removes another table's entry: 21/MC-7, 22/CR-6, CR-7.

The NamespaceAuditor Javadoc (`NamespaceAuditor.java`:54-56) mentions a "namespace state chore" that corrects the cache. It does not exist. The only rebuild is `NSM.initialize` at master start (:223-239), so every group except G-D heals at the next restart. G-D is recreated by that rebuild.

**Other groups:**

- **G31, a server both online and dead cannot be retired** (SM:675-678): 31/MC-3.
- **G34-1, a new key master never loads keys and rolls from a stale `idSeq`** (ATSM:180-185, :252, :319-321): 34/MC-1, MC-3, CR-3. MC-4 and CR-5 end in it after takeover.
- **G34-2, a stopping non-leader sets `isMaster`** (ATSM:307-321): 34/MC-2.
- **G34-3, a key is made current before it is published** (ATSM:257-259): 34/MC-4, CR-5.
- **G37-A, master znode deletes without an owner check** (AMM:285, :342-347; MAT:318-322): 37/CR-5, MC-4, MC-5. All need held windows.
- **G20a, an unversioned `FSTableDescriptors` cache put**: 20/MC-1, MC-2. **G20b**, a preload before the fence: 20/MC-3. **G20c**, a reload in pid order after a restart: 20/MC-4.
- **G24, `ZKProcedureUtil` reset placeholders and same-name reuse**: all of 24.

**Comparison with batch 4 (`hbase/VERIFIED-BUGS.md`).** No duplicates:

- 08/MC-1 is in the same NSM class, but a different mechanism: a recovered namespace delete racing quota init and aborting the master.
- 11/MC-2's trigger uses a saturated namespace quota, but its defect is the split admission.
- 04/MC-3 is space quota.

---

## KEEP-B: 21/MC-4 + 22/CR-1, the master's rebuild counts region replicas

Targets: NSM:130 (case 21, through restore) and NSM:168 (case 22, through create). Both are explicit throws.

Root cause, read at the pinned commit:
1. **Live paths reserve primaries only.** `CTP.preCreate` reserves `newRegions.size()` (CTP:334-337). At that point `newRegions` holds primaries only. Replicas are added later, in `addTableToMeta` (CTP:405-407, `RegionReplicaUtil.addReplicas`). Split and merge apply ±1 per primary (`NamespaceAuditor`:116, :128-129, by the 21/22 pass).
2. **The rebuild counts every located replica.** `NSM.initialize` (:223-235) calls `MetaTableAccessor.getTableRegions(conn, table, true)` (:232-234). That goes through `getTableRegionsAndLocations` (`hbase-server/.../MetaTableAccessor.java`:367-379) to `ClientMetaTableAccessor.CollectRegionLocationsVisitor.add` (`hbase-client/.../ClientMetaTableAccessor.java`:481-490), which adds one entry per non-null replica location.
3. **Throw sites:** create at NSM:166-174; restore at NSM:126-133 via `RestoreSnapshotProcedure`:380-386. By reading, splits in the namespace are refused by the same inflated total (NSM:88-97); not run.
4. **Gate:** `hbase.quota.enabled` defaults to false (`QuotaUtil`:70-71). With it off, `MQM.start` returns before building the `NamespaceAuditor` (MQM:96-99, :114-116).
5. Upstream `master` `NamespaceStateManager.java` is byte-identical to the base, by diff (21/22 pass).

Trigger: quota on, a namespace with `maxregions`, and a table in it with `REGION_REPLICATION > 1`. Then any master restart or failover.

Reproduction: level 0, with Admin calls and a real master stop and start. The cache was only read, and no window was held. It fired 4 of 4 times on 22 (including pristine) and in every run on 21. No test-held window is needed.

Consequence: the table's cached count becomes regions × replication. At quota 2, a 1-region table with replication 2 is cached as 2, and a valid 1-region `createTable` is refused.
- Case 21 shows a restore that fits still refused after 20 s, after a janitor run, and after a second failover: the rebuild itself recreates the inflation.
- It lasts until the table is deleted or the quota raised. The namespace's effective quota shrinks by (replication − 1) × regions on every restart.
- No data is lost.

Not designed: create counts primaries, and nothing documents that replicas count. PR #8792's description says the accounting "only counts default replicas". HBASE-22013 removed replica counting from space quotas.

Why tier B: non-default feature plus operator-set limits, and the harm is refused admin operations and blocked splits. It is kept, unlike the groups that heal at restart, because it survives restarts and the restart is what causes it. The owner's "borderline" quota case applies here: I judge it B and not a drop, because nothing short of deleting the table or raising the quota clears it.

Novelty (bounded):
- JIRA `text ~ NamespaceStateManager` (24 hits) and `NamespaceAuditor` (22): all titles read.
- Also searched: namespace and region quota summaries (42), `"namespace quota" AND replica` (11), `maxregions` with replica, snapshot, clone or MOB (2). None matches.
- Read in full: HBASE-30483 (truncate only), HBASE-28559 (merge arity), HBASE-28560 (rollbacks).
- GitHub: "NamespaceStateManager replica" found only #8792 and #8787, both truncate. #8792's diff touches TruncateTableProcedure, NamespaceAuditor, NamespaceStateManager (adds `setRegionCountForTable`), NamespaceTableAndRegionInfo, MasterQuotaManager and a test, but not `initialize()`.
- Some later JIRA queries returned 503s, and one GitHub query was rate-limited.

**What HBASE-30483 / PR #8792 cover:** only G-B (21/MC-2, 22/MC-2, 22/MC-1). Its title matches 22/MC-1's citation.

## KEEP-B: 31/MC-3, a crashed RS stays online forever after a failover

Target: `RSRpcServices.throwOnWrongStartCode`:1878 (frame :1880, same statement). Explicit throw: stale RPCs to the ghost's successor fail the start-code check.

Root cause, read at the pinned commit:
1. **Upgrade records a lingering server online.** On a new active master, `RST.upgrade` runs every server with a znode through `checkAndRecordNewServer` (RST:150-158). A crashed RS whose znode still lingers is recorded online.
2. **The same server is then marked dead.** `SM.findDeadServersAndProcess` (SM:445-449) puts it into `deadservers` from its pending SCP (`putIfAbsent`, :446).
3. **Expiry becomes a no-op.** `SM.expireServer` returns early when `isDeadServer` (SM:675-678), before `moveFromOnlineToDeadServers`. That method holds the class's only `onlineServers.remove` (SM:726-735, remove at :734).
4. **Nothing re-expires it.** The znode deletion (`RST.processAsActiveMaster`, :176-177) and a successor's stale-expire (SM:421-425) both reach that early return. The dead entry is cleared only by `cleanPreviousInstance` after initialization (SM:494-500), and that does not expire the server either.
5. **Shutdown waits on it.** On shutdown the master stops only when `onlineServers.isEmpty()` (SM:697-701).
6. Upstream `master` has the same early return (master SM:690-692, by the pass's reading).

Trigger:
1. An RS crashes with an RPC in flight, and its znode lingers.
2. Dispatcher fail-fast stores an SCP, 28.5 s after the crash at the default limit.
3. The active master aborts or is stopped while that SCP is pending.
4. A same-port successor registers before the new master is initialized.
5. The crashed RS's session expires before initialization.

By reading, the successor may not be needed; that variant was not run.

Held-window note: level 0 fired 0 of 2. At level 1:
- The test parks the RS exit before `deleteMyEphemeralNode`. That stands in for kill -9 and does not insert code timing.
- It aborts the master within milliseconds of the SCP being stored.
- It expires the session at 34.6 s instead of the 90 s default.

These are test-chosen moments for external events, not delays inside the code the trigger depends on, but the window is narrow and was not hit unaided. The run argues that a kill -9 of the master would not work, so a prompt abort or stop is needed.

Consequence: permanent in 4 of 4 `Early` runs, 3 of them pristine.
- `Admin#shutdown` never completes: not done after 180 s, master still idle about 8 min later.
- `getRegionServers` lists the dead server.

Untested: whether a master restart clears it (by reading it should, since the next upgrade sees no znode), and whether assignments to the ghost cause harm (one move to it was harmless).

Why tier B: the trigger needs a master failover inside an SCP's pending window. The harm is a wedged shutdown and a false live server, not data loss.

Novelty (bounded): JIRA text "already in DeadServer" returned 0 hits. Searches on "dead server"/"online" summaries, shutdown + hang summaries, and `expireServer` + DeadServer found HBASE-5875, 20144, 21259, 21844 and 21518, all different mechanisms. GitHub search was rate-limited and did not run.

---

## Notes on specific drops

- **20/MC-4** is the most severe consequence among the drops: an acknowledged column family and its directory are deleted. The decisive lines (by the 20 pass):
  - `ProcedureExecutor`:495-523: unexecuted procedures reload in pid order.
  - `ModifyStoreFileTrackerProcedure`:192-201: the child is built from the current descriptor.
  - MTP:82-90: the two-argument constructor skips the descriptor check.

  The reproduction depends on a test-held SHARED table lock and on `ProcedureExecutor.Testing` kill hooks, and the trigger is an SFT migration, plus an addColumn inside a ms window, plus a master crash at one step. By reading, the FINISH_MIGRATION child may widen the pid window during its region reopen. Not run. Owner may overrule.
- **24/CR-3, "false flush success".** By the 24 pass's reading, `Admin.flush` uses the proc-v2 `flushTable` and falls back to the ZK procedure only on `DoNotRetryIOException` from an old master (`RawAsyncHBaseAdmin`:1041-1068). The overlap also needs master flush threads ≥2, against a default of 1 (`MasterFlushTableProcedureManager`:76). An unflushed memstore is still in the WAL, so nothing is lost.
- **34, configuration.** The token secret manager exists only when `hbase.security.authentication=kerberos` (`RpcServer`:309, :424-425; `User`:245-246), so no 34 finding is in a default configuration. Severity was judged on its own merits as well.
- **34/MC-2 and the failed TLC rerun.** `findings.json` records MC-2's config as `MC_hunt_S1.cfg`, but that config yields MC-1's ordering. MC-2's trace (`spec/output/probe_S1_Settled.out`, 15:53) came from `probes/MCProbe_Settled.cfg`, whose `MCProbe.tla` was edited at 16:42, after the trace. So the recorded model evidence for MC-2 cannot be regenerated and should be treated as unreproducible.

  MC-2 does stand independently on the Java side and in the code: level 0 hit 288 of 300 with no hooks, the no-stop control hit 0 of 300, and a one-line patch at ATSM:321 also gave 0 of 300. The path is ZKLeaderManager:105, :136-141, then ATSM:312, then ATSM:321. The verdict does not change: it is dropped for severity, not reality. The provenance gap is a Specula record-keeping defect worth noting in the results.
- **37, target.** MAT:206's only production caller, `AMM.getActiveMasterInfoPort` (AMM:164-171), catches everything and returns 0. That was made deliberate in HBASE-26215, and the caller is reached only from `backupMasterStatus.jsp`. So L206 itself is always handled, and a 37 finding matters only through what removed the znode.

  An unreproduced route to G37-A deserves a look: `RecoverableZooKeeper.delete` retries on CONNECTIONLOSS (RZK:216-221). A lost reply plus the retry's version -1 delete could remove a successor registered during the retry sleep, with no held window. Not run. Also by reading: an active master that loses its znode never re-registers (AMM:194-216, the only create at :238).
- **35/MC-1.** The mechanism is real: `MasterRpcServices.setRegionStateInMeta` (:2688-2718) has no meta guard, and :2708 writes row `hbase:meta,,1`. But the shipped HBCK2 `setRegionState` scans meta and never calls this RPC, so it writes nothing for 1588230740. The API is marked "DO AT YOUR OWN RISK" (`Hbck.java`:34-37). Watch item: HBASE-27181 (Open) would move HBCK2 onto this RPC, and that would make the operator route real.

## Side finding (off-target, not counted)

- **S1, from 34/CR-3 (G34-1).** On a secure cluster, a key-master handoff that misses a key event reuses the key id with a new secret:
  - `addKey` ignores keys once `isMaster` is set (ATSM:180-185).
  - `LeaderElector.run` sets `isMaster` without reading ZK (ATSM:319-321) and rolls at once.
  - The roll uses `++idSeq` (ATSM:252), and `createSetData` overwrites the znode.

  Unexpired tokens signed with the old secret then fail SASL on every server until they expire; the run left a 167 h token unrecoverable. It does not reach :160: the symptom is a password mismatch. Level 0 hit 23 of 400, with stops timed right after an election. No JIRA found (34 `AuthenticationTokenSecretManager` hits read by title; nearest HBASE-15039, HBASE-22253).

## Not checked

- Raw repro logs and test sources for all nine cases. "No hooks" and hit rates are the runs' claims.
- GitHub PR search for 20, 24, 31, 34, 35 and 37 (rate-limited).
- The split-refusal half of G-D (code reading only), and the MOB path of G-A in `RestoreSnapshotHelper`.
- 31/MC-3's recovery by a master restart, and its second path through a `ServerNotRunningYetException` retry.
- Upstream `master` for the 20 and 24 files, except `ProcedureExecutor`'s reload sort, which is unchanged.
- The full comment threads of HBASE-5926 and HBASE-17305.
