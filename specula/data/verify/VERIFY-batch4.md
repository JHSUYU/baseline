# Independent verification, batch 4 (HBase 04, 07, 08, 10, 11, 12, 13, 14, 15, 19)

Reviewed 2026-11-05 against the unmodified source: apache/hbase `1790942bb2` (read with `git archive` from `src/hbase`, not from the case trees).

Bar: reaches the target exception at the target line, in the real system, without writing the guard's operands and without injected timing the trigger depends on; a realistic trigger, not designed, not a test artefact, not already reported; and severe.

## How this was checked

- Every decisive code path for a KEEP or a side finding was read in the source. Line citations are at `1790942bb2`. Short forms: AM = `master/assignment/AssignmentManager.java`, TRSP = `TransitRegionStateProcedure.java`, RSN = `RegionStateNode.java`, STRP = `SplitTableRegionProcedure.java`, QOC = `quotas/QuotaObserverChore.java`, HM = `master/HMaster.java`, CSSI = `ClusterSchemaServiceImpl.java`, NSM = `namespace/NamespaceStateManager.java`, RGU = `rsgroup/RSGroupUtil.java`, RMP = `RefreshMetaProcedure.java`.
- **No test was run.** Hit rates, frames and consequences come from the run reports and logs. For the KEEPs I also read: the level-0 test source of 11/MC-3 and 10/CR-1, the timeline excerpt of 10/CR-1, the level-0 output of 11/MC-3, the level-0 test of 11/MC-2, and the `prodShape` test and log of 04/MC-3. For 08/MC-1 and 08/MC-3 I read the report's log excerpts, not the raw logs or tests, so "no hook at level 0" there is the report's claim.
- For DROPs I read the finding record (cause, trigger, consequence, premises) and, where its verdict turned on it, the code or report tail. Findings dropped as "not severe" rest on the run's own consequence text. Where the finding itself says no lasting harm, I did not re-derive that.
- No target is a Java `assert`: all ten are explicit throws, read in the source. The run frames AM:766 (case 10) and MTRP:504 (case 14) are the continuation lines of statements starting at AM:765 and MTRP:503. Case 19's target line is wrong: `target.yaml` says L134 but quotes the name guard, whose throw is `ModifyTableProcedure`:127; L134 is the column-family count throw.
- Web: Apache JIRA REST, the GitHub search API and raw.githubusercontent.com all answered. **Every novelty negative is bounded**: JIRA text search is coarse (class-name queries often return 0), broad queries were judged by title, and only a limited set of results was read. Upstream `master` was read for STRP, TRSP, TruncateRegionProcedure, QOC, NSM, RGU, HM and RMP, by targeted grep (RMP by full diff: identical). AM on master was not read.
- `11/CR-5`, `11/CR-9`, `19/CR-1`, `19/CR-2` are marked FALSE POSITIVE by the runs and were not reviewed, per the brief.
- Nothing under `/bulk/GraphChecker` was read. Nothing was filed or posted.

## Summary

| Case / finding | Verdict | Reason | Sure? |
|---|---|---|---|
| **11/MC-3 + 10/CR-1** (merged) | **KEEP-A** | truncate_region force-detaches a concurrent move's TRSP; the TRSP still runs; region stuck CLOSING and unserved, survives failover; default config, level 0 | mechanism high; tier medium |
| **11/MC-2** | **KEEP-B** | split admits a CLOSED parent; rollback sets OPEN with no location; `assign` refused at L769; region unserved until HBCK force or failover. Needs saturated namespace quota or a coprocessor veto | high (mechanism); medium (tier) |
| **04/MC-3** (scope corrected) | **KEEP-B** | new master forgets a quota-DISABLE; raising the limit never re-enables; manual enable denied. Only the `prodShape` part counts; quota is off by default | high (mechanism); medium (tier) |
| **08/MC-3** | **KEEP-B** | meta RS crash in master init with rsgroup on: meta's assignment needs the namespace cache, the cache needs meta; master aborts | high (mechanism); medium (tier) |
| **08/MC-1** | **KEEP-B** | recovered DeleteNamespaceProcedure races quota init; new active master aborts. Weakest keep: ms crash window plus a second race | medium |
| 10/CR-4 + 12/MC-2 (merged) | DROP, unrealistic | severe if reached (region OPEN under DISABLED, enable hangs), but needs a test-held handler stall of 200-800 ms; 0/250 unaided; no independent natural stall found | medium-high |
| 11/CR-4 | DROP, duplicate | truncate route is the KEEP-A bug; attachment-clearing route needs HBCK2 `-o` plus a level-1 delay | high |
| 11/CR-10 | DROP, needs held window | same force-detach; needs a coprocessor delay (0/360 unaided); L769 never fires. Listed as a route of the KEEP-A bug | high |
| 11/CR-7 | DROP, off-target | run says L769 does not fail on these paths; path C is HBASE-30353. Arm A is real and severe: **side finding S2** | high |
| 14/CR-3 | DROP, off-target | target only with injected fault, injected delay, parked merge and 2 workers. Real and severe: **side finding S1** | high |
| 11/CR-3 | DROP, known and off-target | HBASE-30385 (open, PR #8658); level 0 throws from L765, not L769 | high |
| 11/CR-12 | DROP, not severe | expert-only `Admin.offline`, then offload stops; regions keep serving; `assign` clears it | medium-high |
| 11/MC-1 | DROP, not severe | deprecated `abortProcedure`, 5/1722 under hammering; region keeps serving; failover clears. Mechanism real (`StateMachineProcedure`:117-119) | high |
| 11/CR-8 | DROP, not severe | same abort mechanism on merge; reads keep working; failover clears | high |
| 11/CR-1 | DROP, not severe | non-default replica the operator asked to close; primary unaffected; HBCK force or disable/enable clears | medium |
| 11/CR-6 | DROP, not severe | RegionMover returns false; re-run drains | high |
| 11/MC-4 | DROP, not severe | offload stops mid-loop; re-issue finishes; HBASE-22254 (abandoned) named this weakness | high |
| 11/MC-5 | DROP, not severe | rsgroup moveServers refused after failover; a rejected call on a CLOSED region | high |
| 11/CR-2, CR-11 | DROP, masked | runs' own verdict; recovery paths work | high |
| 10/MC-3 | DROP, known limitation | undocumented non-default `hbase.assignment.maximum.attempts`. The harm comes from SCP being rolled back (HBASE-21372, HBASE-21039); the new part, a stale attachment, only changes the error | medium |
| 10/MC-4 | DROP, not severe | same config; region FAILED_OPEN is refused either way | high |
| 10/CR-6 | DROP, unrealistic | needs `-ea` on the master (Java `assert` at TRSP:435, not the target) and a held RS report; self-heals with assertions off | high |
| 10/MC-1 | DROP, not severe | false failure on retry; server state correct; 60 s timeout or a master crash needed | high |
| 10/CR-7, MC-2 | DROP, masked | next master completes it; client retry absorbs it | high |
| 04/MC-1 | DROP, known | HBASE-30484, open; PR #8791 makes the same reorder | high |
| 04/MC-2 | DROP, known and not severe | same site; held stall; retries=0 in the workload; table self-heals | high |
| 07/CR-1 | DROP, not severe | rejected restore; no data changed | high |
| 07/CR-2 | DROP, unrealistic | simulated clock read, coprocessor-delayed Put, several master crashes in order | high |
| 07/MC-1 | DROP, not severe | wrong exception type; T, X and S unchanged | high |
| 07/MC-2 | DROP, not severe | non-default quota; rejected restore; leftover failsafe snapshot | high |
| 07/MC-3 | DROP, not severe | deposed master; retry through the new master succeeds | high |
| 08/MC-6 | DROP, known | HBASE-21455 (open): same chore, same line, same exception, same fix. The lost post-hook is a new route to it | high (known); medium (route) |
| 08/MC-2 | DROP, known | HBASE-30008, PR #7957 open | high |
| 08/MC-4 | DROP, not severe | one wrong non-retried error in an init window | high |
| 08/MC-5 | DROP, masked | chore catches it; next run recovers | high |
| 12/CR-10, MC-3 | DROP, not severe | disable completes; rejection is accurate (AM:772 counts DISABLING by design) | high |
| 12/MC-1 | DROP, not severe | offload stops within ms of a disable; re-issue fixes; regions keep serving | high |
| 13/MC-1 | DROP, not severe | needs clock skew; one merge refused until the next janitor pass | high |
| 13/MC-2 | DROP, unrealistic | held poll-to-acquire gap; 0/60 unaided; retry succeeds | high |
| 14/MC-1 | DROP, not severe | second merge refused, no harm; HBASE-24256 reports the same message via fixOverlap | high |
| 14/MC-2, MC-3, MC-4 | DROP, not severe | merge refused; no state or data harm; MC-3 needs a held region lock, MC-4 a held handler | high |
| 14/CR-1, CR-2 | DROP, masked | NPE in rollback swallowed; CR-2's harm needs a hand-deleted meta row. Its notes feed S1 | high |
| 15/MC-1 | DROP, not severe | regions recover; the merge fails anyway without the move (at L519), so only the error changes; needs a held meta Get, 0/6 unaided | high |
| 15/MC-4 | DROP, not severe | same as MC-1 after failover; paused workers and emulated crash; control fails too with another error | high |
| 15/MC-2 | DROP, known and not severe | HBASE-19851 (open); retry succeeds | high |
| 15/MC-3 | DROP, not severe | accepted merge refused; retry after re-assign succeeds | high |
| 19/CR-3 | DROP, unrealistic and known | case-insensitive root dir only; HDFS unaffected; HBASE-13652 (abandoned) | high |

Totals: 55 findings reviewed; 1 KEEP-A (2 findings merged), 4 KEEP-B, the rest DROP; 2 side findings.

## Root-cause groups

- **G1, TRSP has no attachment fence** (HBASE-22074 removed it): 11/MC-3, 10/CR-1, 11/CR-4, 11/CR-10. Truncate-region's forced unassign is the unprivileged route.
- **G2, attached but unsubmitted TRSP is invisible to disable** (AM:1115, AM:1173): 10/CR-4, 12/MC-2.
- **G3, split admits a CLOSED parent** (STRP:505): 11/MC-2, 11/CR-7 arm A.
- **G4, `abortProcedure` lands mid-step, state stack one deeper than rollback steps** (`StateMachineProcedure`:117-119): 11/MC-1, 11/CR-8.
- **G5, QOC's state is memory only**: 04/MC-1, MC-2, MC-3. HBASE-30484 covers the first two; its reorder does nothing for a new master (04/MC-3).
- **G6, init ordering** (HM:1610 publish before load; HM:1300 `setInitialized` before HM:1335 `initQuotaManager`): 08/MC-1, MC-2, MC-3, MC-4.

Merge duplicates requested: 10, 11 and 12 share `AM.preTransitCheck` but only G1 and G2 cross cases. 13, 14 and 15 share `prepareMergeRegion`; none of them keeps, because a refused merge is the guard working and a retry fixes it.

---

## KEEP-A: 11/MC-3 + 10/CR-1, truncate_region strands a region through a concurrent move

Targets: AM:769 (case 11), AM:765 (case 10). Both are explicit throws, reached as a consequence of the bad state.

Root cause, read at the pinned commit:
1. `preTransitCheck` (AM:762-774) checks only the node's attachment, state and table state, not the scheduler's region lock. `createMoveRegionProcedure` (AM:883-886) therefore attaches a move TRSP while truncate holds the region xlock.
2. `TruncateRegionProcedure` holds its lock across steps (`:292-298`, `AbstractStateMachineRegionProcedure`:82-84). At MAKE_OFFLINE (`:103-104`) it calls `createOneUnassignProcedure(region, true, true)` (`:284`).
3. With override and force, AM:1012-1018 unsets the attached TRSP. It does not cancel it. `RSN.unsetProcedure` (:220-224) checks ownership by `assert` only.
4. The displaced TRSP has no attachment check. `TRSP.executeFromState` (:483-519) goes straight to the switch, even though AM:1084-1087, RSN:50-52 and TRSP:727-729 still say it "will quit immediately". `git log -S'regionNode.getProcedure() != this'` shows the check's last change is `5f6143ebde` (HBASE-22074, 2019).
5. Truncate finishes and releases the lock. The displaced move runs on the reopened region: TRSP:397 accepts OPEN, writes CLOSING, adds a CloseRegionProcedure.
6. The RS closes and reports. `AM.reportTransition` (:1347-1349) routes by `regionNode.getProcedure()`, finds null, returns false, and AM:1335 logs "No matching procedure found". The TRSP waits in CONFIRM_CLOSED with no timeout.

The docs never allowed this: RSN:55-56 covers `TruncateTableProcedure`, which has the table xlock, not truncate-region. HBASE-28582 removed the same reset from ModifyTable, saying it "is not safe".

Trigger: `Admin.truncateRegion(R)` and `Admin.move(R, dst)` (or a balancer plan) with the move arriving after truncate takes the lock and before MAKE_OFFLINE. Recovery snapshot off (default).

Reproduction, no held window needed:
- 10/CR-1 `level0PureRace`: two clients, plain Admin calls, no hook. Read the test. Stuck in round 0 at offset 0 in 3 of 3 runs. The timeline excerpt shows xlock pid=25, `Stored pid=26`, `Finished pid=25 SUCCESS`, `Took xlock pid=26`, CLOSING, then AM:1335.
- 11/MC-3 `testLevel0PureRace`: 5 of 5 runs, at attempts 9, 8, 8, 8, 2. Read the test: an unarmed coprocessor (the hook checks `armed`), 16 procedure threads (the production floor), `Admin.move` and `truncateRegionAsync`. Log: `LEVEL0 HIT at attempt 2 jitterMs=2 ... rsnState=CLOSING rsnProc=null`, then `Admin.move ... frame769=true`, `Admin.assign ... frame769=true`.
- The balancer route was shown only with a level-1 hold on `preTruncateRegionAction` (real `Admin.balance`, 3 of 3 regions stranded). By reading it uses the same `createMoveRegionProcedure`.

Consequence: truncate reports success, then the region goes unserved. Client Put/Get fail with `NotServingRegionException`; other regions are fine. Move, assign and unassign fail at L769. After a master failover the TRSP re-attaches (AM:393), the RS ignores the re-sent close, and requests fail at L765-766. Still stuck in the runs' bounded watches: 150-180 s idle, 150-180 s after failover, 180 s after an RS crash, where the crash procedure itself then waits on the stuck TRSP's lock. **HBCK2 bypass was not tested**, so "manual repair" is inferred.

Novelty (bounded): JIRA queries on `TruncateRegionProcedure` (2 hits, unrelated), `truncate_region`, `truncate region` + move, `createOneUnassignProcedure` (0), `HBASE-22074`, `unsetProcedure`, "No matching procedure found", TRSP + quit. GitHub PR searches on `TruncateRegionProcedure`, `attached TRSP truncate` (0). Closest: HBASE-30043 (open; recovery-snapshot truncate vs merge, a different defect), HBASE-28522 (fixed; disable path), HBASE-28582 (fixed; ModifyTable). PR #8700 mentions truncate but changes only AM, RegionStateStore and tests, for split parents. Upstream `master`: `TruncateRegionProcedure`:284 still passes `true, true`, and TRSP has no `getProcedure() != this` check.

Weakest points, for whoever sets the tier:
- The window is a few ms (2-3 ms in the two logs read). Hits come from tests that aim both calls at one region.
- `truncate_region` is a rarely used admin command (HBASE-28064, 2023). Production needs that command to overlap a move of that region.
- No data is lost beyond what truncate intended. The harm is availability of one region per hit.

## KEEP-B: 11/MC-2, split rollback leaves a CLOSED parent OPEN with no location

Target: AM:769. Explicit throw.

Root cause:
1. The split constructor's `checkOnline` (STRP:119) takes no lock, so it can pass while the region is OPEN. The split then queues behind a concurrent unassign.
2. PREPARE sees CLOSED and accepts it: `EXPECTED_SPLIT_STATES = {OPEN, CLOSED}` (STRP:505, :561). It sets SPLITTING in memory only (:590).
3. PRE_OPERATION fails: `onRegionSplit` throws `QuotaExceededException` (STRP:625, `MasterQuotaManager`:542-544), or a coprocessor vetoes.
4. `rollbackPrepareSplit` (STRP:601-606) sets OPEN whenever the state is SPLITTING. That line came from `8a2f3ef793` (HBASE-28533, 2024), which assumed the parent was open. Meta stays CLOSED and the location is null.
5. `Admin.assign` then fails at AM:769: OPEN is not in `STATES_EXPECTED_ON_ASSIGN` (AM:2181).

Trigger: `Admin.unassign(R)` overlapping a split of R, split started 0.4-7.2 ms before the unassign, with the namespace at its region quota (`hbase.quota.enabled=true`, non-default) or a coprocessor veto.

Reproduction: level 0, 13 of 13 runs (11 pristine, 2 worktree). I read the test: real quota, `unassign` and `splitRegionAsync` with up to 8 ms offset, no failpoint. It hammers until a hit, so this is reachability, not a rate. No held window needed.

Consequence: the region is unserved and the operator's `assign` is refused. Unchanged after 30 RIT chore cycles (30 s observed only; "lasting" rests on no other code path changing the node). `hbck.assigns(override=true, force=false)` returns -1; `force=true` or a master failover recovers. `unassign` or `move` makes it worse: `CloseRegionProcedure` gets a null target and `RegionRemoteProcedureBase`:406 throws an NPE that kills a PEWorker. Severity caveat: the operator asked for the close, so the initial unavailability is intended; the defect is that the normal way back is refused and the obvious workaround does damage.

Novelty (bounded): JIRA `rollbackPrepareSplit` (0), split + unassign since 2023 (only HBASE-28533, which reports the opposite symptom and is the source of this line), "Worker terminating UNNATURALLY" (HBASE-21039 is generic). GitHub `rollbackPrepareSplit` (0). Upstream `master` has the same STRP:505 and rollback.

## KEEP-B: 04/MC-3, a new master forgets a quota-DISABLE (scope corrected)

Target: `AbstractStateMachineTableProcedure`:163. Explicit throw.

**What the run's title claims is partly an artefact.** Its level-0 and level-1 shapes keep the observer in the test JVM across the crash, with retries=0. Those do not show a real master. I keep only the `prodShape_masterRestart` test, where the master's own observer does the work and the kill is a real `killMaster`. The run itself calls that a sibling case. A real crash inside the enable window should reach a milder form of the same state, by reading: the row already says observance, so a manual enable works.

Root cause, a real master restart while a table is disabled by a DISABLE violation:
1. `QOC.getTableQuotaSnapshot` returns `NO_QUOTA` when nothing is tracked ("No tracked state implies observance", QOC:541), and the new master's map is empty.
2. The disabled table has no open regions, so no size reports arrive. The HBASE-22012 fix that keeps its reports (`MasterQuotaManager`:734-737) is in memory, so it does not survive. The table is filtered into limbo (QOC:721).
3. The limbo branch acts only if the in-memory status is in violation (QOC:187). It is not, so nothing happens. `updateTableQuota` (with its enable at QOC:332-333) is never reached.
4. The `hbase:quota` row keeps `inViolation=true`. The log shows it 45 s after the limit was raised, at short test chore periods.
5. `HMaster.enableTable` reads that row and denies (HM:2850-2857).

Trigger: `hbase.quota.enabled=true`, a table disabled by a DISABLE space quota, active master restart or failover, then the operator raises the limit.

Evidence (`repro/MC-3.pristine.part2.log`): flush throws `TableNotEnabledException` with server frame `:163`; `enableTable` throws `AccessDeniedException ... disallowed due to a violated space quota`; `finally disabled=true`. Control without a crash: re-enabled about 2 s after the limit was raised, flush OK.

Consequence: the table stays offline although it is within quota, and the documented action does nothing. By reading, removing the quota clears it (`MasterQuotaManager`:291-300 reads the persisted row and enables); **the run did not test that**. So recovery exists but is not obvious. Note the flush failing at L163 is accurate in itself; the defect is the stuck table.

Novelty (bounded): HBASE-30484 / PR #8791 is a failed enable in a live chore; its reorder does not help a new master. HBASE-20662 and HBASE-22012 are the live-master forms and are fixed. JIRA space quota + failover/restart + disable gave nothing matching; GitHub likewise. Upstream `master` QOC still has `setCurrentState` before the enable (:325) and no reconcile.

## KEEP-B: 08/MC-3, meta assignment depends on the namespace cache during master init

Target: CSSI:111. Explicit throw.

Root cause:
1. `initClusterSchemaService` publishes the field (HM:1610) before the cache loads (`startAsync` HM:1611; `CSSI.doStart` :60-61 calls `notifyStarted` then `tableNamespaceManager.start`, which loads at `TableNamespaceManager`:166).
2. `RGU.getRSGroupInfo` guards only a null service (:107-116), with the stated intent of using the default group for meta. Non-null but empty reaches `getNamespace` (:117), and CSSI:111 throws for `hbase`.
3. `processAssignmentPlans` catches and re-queues (AM:2633-2636). So the load needs meta, and meta's plan needs the load.
4. The scan's retries run out (about 60 s), the service fails, and HM:2630 aborts the master.

Trigger: `hbase.balancer.rsgroup.enabled=true` (default false, RGU:50). The RS holding meta crashes after the master passes `waitForMetaOnline` (HM:1179) and before the namespace scan completes. No master crash needed.

Reproduction (from the report): level 0 aborted the master in 1 of 4 runs, the crash timed by polling the service field through an inert hook. Level 1 every time. Control with rsgroup off: 0 target frames, master initializes.

Consequence: the active master aborts with a live RS available. A one-master cluster stays down until a master is started; a fresh master initialized in about 7-10 s through the null-service path, so a standby limits it to a failover. The user-region path and standby takeover were not exercised.

Novelty (bounded): JIRA rsgroup + `NamespaceNotFoundException` (2, unrelated), `RSGroupUtil` + namespace (HBASE-24591, unrelated), `getNamespace` + rsgroup (HBASE-22089, open: the null case the guard handles). Upstream `master` RGU has the same guard and HM the same assignment.

Weakest point: the window is a master-startup interval, so it needs an RS crash during a master takeover or boot.

## KEEP-B: 08/MC-1, recovered namespace delete aborts the new master

Target: CSSI:111. Explicit throw.

Root cause: HM:1300 `setInitialized(true)` releases recovered procedures before HM:1335 `initQuotaManager`. `NSM.initialize` lists namespaces (:224) and then looks each one up (:227) through `listTableNamesByNamespace`, with no handling of a namespace deleted in between. The recovered `DeleteNamespaceProcedure` removes it from the cache. The exception reaches `startActiveMasterManager`, and HM:2630 aborts.

Trigger: quota enabled (default off). Master dies after the procedure is stored and before its meta delete, a window of a few ms. On the next master, the cache removal lands between NSM:224 and :227. Tables in namespaces sorting earlier widen this.

Reproduction (from the report; crash is `HMaster.abort`, not a process kill): level 0 with no hook: 3 of 10 rounds with 5 or 20 extra tables, kill deliberately racing the delete. **With the workload's namespace alone it fired only with a held observer (3/3) and 0/3 naturally.** So the exact workload needs a hold; the unheld form needs extra earlier-sorting tables, which any real cluster has.

Consequence: one master crash costs a second master. In a two-master setup no active master remains until one is started; a third master recovered in every round that logged it. No data loss.

Novelty (bounded): HBASE-30008 / PR #7957 has the same ordering, but its diff only changes how the procedures get the quota manager, which runs after the cache removal and so cannot close this window. JIRA `NamespaceStateManager` (0 by summary). Upstream `master` has the same ordering (HM:1310, :1345) and NSM code.

Weakest points: needs a crash in a ms window during a rare admin call, plus a second race, plus non-default quota. Keep only if a crash-recovery abort at that rarity counts.

---

## Side findings (fail the bar on target, but real)

### S1. 14/CR-3: `refresh_meta` deletes tables on a swallowed storage error. Does not reach the target.

The target was reached only with a merge parked on a region lock, two workers, an injected list fault and an injected delayed delete. Without the delay the merge gets an NPE at MTRP:482 instead. So it fails bar 1. On its own it is the most damaging item in this batch.

Read in the source:
- `scanBackingStorage` swallows failures: RMP:357-359 (namespace), :376-380 (table, returns empty), :401-403 (`exists`), :421-424 (`.regioninfo` read).
- `prepareMutations` treats anything missing as gone: meta row deletes (:259-261), and a table with no regions goes into `deletedTables` (:271-277).
- `executeFollowup` (:210-214) ends in `FSTableDescriptors.remove`, which runs `fs.delete(tabledir, true)` with no archive. The master's descriptors are writable (`HMaster.canUpdateTableDescriptor`, HM:772-774).
- `HMaster.refreshMeta` (HM:4724-4738) has no precondition, although the shell help says the command is for read replica clusters.

Run evidence: one failed table listing destroys the table, and a later refresh does not restore it; one failed namespace listing destroys every table in it; procedure reports `success=true`. Level 0 used real block corruption of the only replica on one DataNode; the listing sites used a one-shot injected `IOException`, not a natural NameNode or object-store error. Replication 3 and natural faults were not tested.

**No-fault variant, from 14/CR-2's notes plus my reading:** `scanBackingStorage` skips the `hbase` namespace (RMP:348) but `getCurrentRegions` (:433-436, `MetaTableAccessor.getAllRegions` with a null table) does not, so every `hbase:` table with regions looks deleted on any refresh. The run showed `tableExists=false` and regions absent for tables it created in the `hbase` namespace, with no fault. **A built-in table such as `hbase:acl` or `hbase:quota` was not exercised, and the directory was still present in its idle run (`tableDir=true`, unexplained, while merge runs showed `tableDir=false`).** Treat this as a strong lead to check, not a confirmed loss.

Novelty (bounded): `RefreshMetaProcedure` (HBASE-30014, HBASE-30081, both unrelated), `refresh_meta`, `scanBackingStorage` (0), PRs #7058, #7974, #8084. Upstream `master` RMP is identical to the pinned file.

### S2. 11/CR-7 arm A: split racing unassign kills a PEWorker. Does not reach L769.

The run states L769 does not fail on these paths. Same admission as 11/MC-2, but with no veto the split proceeds: TRSP:397 accepts SPLITTING, `CloseRegionProcedure` is built with a null location (STRP:505 admits CLOSED, so nothing checks it), and `RegionRemoteProcedureBase`:406 throws an NPE in serialization. Default config, public calls, about 0.5 ms apart, hit on attempt 1 in four runs per the report. Reported: worker lost for good, region node lock held, CLOSING for 260 s including a failover, and operator `assign`/`disableTable` time out. Draining all workers took 5 hits on a 5-worker mini cluster; production's floor is 16.

Arm B (assign in the split's close-to-meta window) reports an acked write invisible to a fresh client, but took about 6000 hammered assigns. Arm C is HBASE-30353 (PR #8700 merged 2026-10-26, after the base; JIRA still Patch Available). HBASE-21039 (open, generic) asks for workers not to die.

### S3. Enable hang under G2

10/CR-4 and 12/MC-2 report `enableTable` hanging because `AssignRegionHandler` silently ignores OPEN for an online region. The handler's silent skip is already reported in HBASE-30048 (open, read title and summary only). Not separately kept.

## Why G2 (10/CR-4, 12/MC-2) is dropped although it looks severe

The defect is real by reading: `AM.assign` attaches at AM:800 and submits at AM:829; disable skips attached regions (AM:1115) and CONFIRM counts only state (AM:1173); TRSP never checks table state. But the runs needed a test `HMaster` subclass holding the handler, with 0 hits in 250 unaided rounds, and the sweeps show 200-800 ms is needed. A shorter stall is safe because a TRSP that reaches the scheduler takes the table shared lock and blocks the disable. The only code in that gap is `store.insert`, whose stall would slow the disable's own store writes too. A GC pause stops both. I found no independent natural cause. If you accept a long stall of one handler as realistic, this becomes KEEP-B.

## Could not check

- No test was run, so every hit rate and permanence claim is the runs'. All permanence is bounded watches plus code reading.
- HBCK2 bypass as a recovery for KEEP-A was not tested by any run.
- Quota removal as recovery for 04/MC-3 is by reading only.
- Real multi-host behaviour: everything ran on mini clusters.
- JIRA comments were read only for a few issues; a mention deep in an unrelated thread could exist.
- AM on upstream `master` was not read for KEEP-A; TRSP and TruncateRegionProcedure were.
