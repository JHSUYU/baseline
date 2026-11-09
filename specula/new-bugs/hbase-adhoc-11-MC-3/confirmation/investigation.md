# MC-3 investigation record (evidence only)

Line numbers are from the pinned tree (1790942bb2). The worktree carries trace instrumentation, so
reproduction runs use a pristine `git archive HEAD` export (`clean-src/`) plus the test file only.

## Step 1: code audit

Target: `AssignmentManager.preTransitCheck` throws DoNotRetryRegionException at AM:769 when
`regionNode.getProcedure() == null` (else AM:765 throws plain HBaseIOException) and the state is not
in the expected set. Expected sets: STATES_EXPECTED_ON_ASSIGN = {CLOSED, OFFLINE} (AM:2211);
STATES_EXPECTED_ON_UNASSIGN_OR_MOVE = OPEN.

Call chain, attaching the move TRSP:
- Balancer: `HMaster.balance` -> `executeRegionPlansWithThrottling` -> `AM.balance` (AM:920) ->
  `AM.moveAsync` (AM:914) -> `createMoveRegionProcedure` (AM:888) -> preTransitCheck under the
  RegionStateNode lock, then `regionNode.setProcedure` (AM:901). Nothing consults the scheduler lock.
- Operator: `HMaster.move` (HMaster:2488) does the same, then warms up the destination before it
  submits (HMaster:2490-2499), so the TRSP is attached but unsubmitted during the warmup.

Truncate:
- `AbstractStateMachineRegionProcedure.acquireLock` takes the scheduler region lock; holdLock is TRUE
  unless recovery snapshots are enabled (TruncateRegionProcedure:303, default off).
- PRE_OPERATION attaches nothing (TruncateRegionProcedure:73-92), so preTransitCheck still passes.
- MAKE_OFFLINE: `createOneUnassignProcedure(region, true, true)` (Truncate:295) -> AM override+force
  skips the check and calls `regionNode.unsetProcedure(regionNode.getProcedure())` (AM ~1033). The
  displaced TRSP is not stopped or notified.

Detached TRSP after truncate ends:
- Holds no RSN attachment. On lock acquisition `closeRegion` (TRSP:~398) sees OPEN, calls
  `regionClosing` and creates CloseRegionProcedure. It never checks `regionNode.getProcedure()==this`.
- RS closes and reports CLOSED. `AM.reportTransition` (~AM:1370) returns false when getProcedure() is
  null and only logs "No matching procedure found". The RRPB is never woken (RRPB:191-246 is the only
  normal wake path) and stays suspended in DISPATCH with no timeout.

Safeguards recorded for Phase 2 to test:
- `UnassignRegionHandler:114-120`: a CLOSE for a not-online region returns without any report, so a
  re-dispatch after master failover would not complete the RRPB.
- SCP `assignRegions` could attach a fresh TRSP when the host crashes, but needs the region lock the
  detached TRSP holds.
- HBCK2 bypass/override (operator tool, not automatic).

Reachability: public Admin APIs only (truncateRegionAsync, balance/move), no fault needed.

## Step 2: developer knowledge (code-local only so far; Shared Rule 2 defers tracker search)
- UnassignRegionHandler:125-129 comment: "if here we just return without calling
  reportRegionStateTransition, the TRSP at master side will hang there for ever." Shows developers
  know an unreported close hangs a TRSP. It is about coprocessor exceptions on close, not this path.
- AM createOneUnassignProcedure javadoc: "called from HBCK2"; truncate reuses it with override+force.
- TestRegionMove#testDisableAndMove asserts AM:769 for a region that was really unassigned, i.e. a
  legitimate refusal. No test covers a move racing with truncate.

## Phase 2 corrections to the Phase 1 audit
- Pristine line numbers: AM:1017 (unset in createOneUnassignProcedure), AM:794 (same in
  createAssignProcedure), AM:1335 (WARN), AM:1347-1348 (null procedure returns false),
  TRSP:389/400 (closeRegion/regionClosing), Truncate:82 (preTruncate), Truncate:284 (forced unassign).
  The finding's AM:1012, AM:789 and Truncate:282 are offset or instrumented-tree positions.
- After failover the re-sent CLOSE is dropped earlier than Phase 1 predicted: the log shows
  HRegionServer:3673 "Received procedure pid=N, which already executed, just ignore it". The
  UnassignRegionHandler:114-120 branch was not the one hit in this run.
- A balance refused during the crash run logged "because 3 region(s) are scheduled to transit"
  (HMaster:2156). The refusal is region-in-transition, not the later dead-server check (HMaster:2163),
  although areDeadServersInProgress was also true.

## Test defects found and fixed
1. Probe row used startKey + "after-truncate". For the empty start key that sorts after "aaaaa", so
   it probed the next region: a false "Put SUCCEEDED" in the first crash run, and a Put failure from a
   different stranded region in the first Level 1 run. Fixed with a 0x01 suffix and a containsRow
   assertion. Superseded logs: repro/MC-3-logs/runs/before-probe-fix/.
2. First failover run: client registry kept the dead master's port (a test problem, not HBase). Fixed
   by setting hbase.masters to the new master.

## Step 2/3: tracker and history search (run after the verdict was settled; sets Novelty only)
Raw queries and results: logs/novelty.txt, logs/novelty-jira.txt, logs/novelty-github.txt.
- Jira JQL: text ~ TruncateRegionProcedure (0); summary ~ "truncate region" (10); text ~ "truncate
  region" AND "move" (36); text ~ createOneUnassignProcedure (0); "No matching procedure found" AND
  CLOSING (10); preTransitCheck (9); unsetProcedure (4); text ~ truncate_region (98, top 12 read);
  updated >= 2026-08-01 with TRSP / TransitRegionStateProcedure / stuck region in summary (1).
- GitHub apache/hbase PR search (`gh` is not installed, so REST via curl): TruncateRegionProcedure;
  truncate region move; truncate region balancer; createOneUnassignProcedure; preTransitCheck; TRSP
  detached/stranded CLOSING; region stuck CLOSING procedure.
- git log on Truncate and on message greps; commit lists for the three sites on upstream master.
- Upstream master head read-only: createOneUnassignProcedure still unsets at AM:1021, Truncate:284
  still forces it, TRSP has no getProcedure()==this check. No fix present.

Closest, none the same mechanism at the same site:
- HBASE-28582 / #5903 (Resolved): ModifyTableProcedure must not reset the TRSP on a region node.
  Verbatim: "this is not safe as MTP does not like DTP where we hold the exclusive lock all the time.
  Second, even if we hold the exclusive lock all the time, as showed in HBASE-28522, we may still hang
  there forever because SCP will not interrupt the TRSP." Same shape, different procedure. Developer
  evidence that resetting a TRSP is unsafe; the truncate site was not changed.
- HBASE-28522: UNASSIGN stuck on a dead RS (DisableTable + SCP). Different trigger and site.
- HBASE-24885 / #2283, #2989: hbck2 assigns. Operator tool path, different defect.
- HBASE-30043 (Open): truncate with recovery racing merge, non-existent region. Different mechanism.
- HBASE-30353 / #8700 (merged 2026-10-26, after base): split parent re-open. Diff read; unrelated.
- HBASE-30201, HBASE-23895, HBASE-30230: different mechanisms.
Limit: post-base AM commits HBASE-30433, 30335, 30357 were judged by title plus the head check, not by
reading their diffs. Jira text search is keyword based, so a report using other wording could be missed.
Novelty: NEW.
