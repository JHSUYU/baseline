# MC-2 investigation record

Evidence only. Line numbers are in the pinned tree `1790942bb2` (no instrumentation), unless marked.

## Step 1: code audit

Target: `AssignmentManager.preTransitCheck`, `AssignmentManager.java:769`, throws `DoNotRetryRegionException`
when `!regionNode.isInState(expectedStates)`. For assign, `STATES_EXPECTED_ON_ASSIGN = {CLOSED, OFFLINE}` (AM:2211 instrumented numbering).

Call chain to the target: `Admin.assign` -> `MasterRpcServices.assignRegion:752` -> `AssignmentManager.assign:834/828`
-> `createAssignProcedure:797` -> `preTransitCheck:769`.

Call chain to the leak:
- `HMaster.splitRegion` (2373) -> `AssignmentManager.createSplitProcedure` -> `SplitTableRegionProcedure` constructor:
  `checkOnline` (STRP:119, RSN must be OPEN at this moment), then `checkSplittable` does a region server RPC.
  The procedure is submitted afterwards. Nothing re-checks state, and an attached TRSP on the node is not checked.
- `AssignmentManager.unassign` (855) attaches a TRSP; RSN stays OPEN until the TRSP's first step runs.
- Both procedures take the region xlock (`MasterProcedureScheduler.waitRegions:796`). A split behind the TRSP parks on it.
- `prepareSplitRegion`: `EXPECTED_SPLIT_STATES = {OPEN, CLOSED}` (STRP:505), comment "expected parent to be online or closed";
  then `node.setState(SPLITTING)` (STRP:~590). The prior state is not recorded.
- `preSplitRegion` (STRP PRE_OPERATION): coprocessor `preSplitRegionAction`, or `MasterQuotaManager.onRegionSplit` ->
  `NamespaceAuditor.checkQuotaToSplitRegion:111` throws `QuotaExceededException`. `executeFromState` catches it -> `setFailure` -> rollback.
- `rollbackPrepareSplit` (STRP:601-606): `if state == SPLITTING then setState(OPEN)`, regardless of prior state. In memory only; meta untouched.

Trigger scenario: see the verdict body. Safeguards noted and tested in Phase 2:
- constructor `checkOnline` (does not help: RSN is still OPEN when it runs);
- region xlock (serialises, which is what delivers CLOSED to PREPARE);
- RIT chore, master failover, HBCK force, unassign/move as a workaround (all exercised).

Worktree instrumentation: `git diff` read for the touched paths. It is observational (`SpeculaTrace`, inert unless `SPECULA_TRACE_FILE`
is set; no-op hooks in `StateMachineProcedure`). `preTransitCheck` keeps line 769. Primary runs used a clean `git archive HEAD` copy of the tree
for `hbase-server`; `hbase-procedure` on that classpath came from the shared repo jar, whose only difference is the two no-op hooks
(verified via `surefire.test.class.path`). Stack frames confirm pristine AM numbering there (`createAssignProcedure:797`, no `speculaPreTransitCheck`).

## Step 2: developer knowledge

Run only after the reproduction verdict was settled (adhoc Shared Rule 2).

Comments in the code:
- STRP `prepareSplitRegion`: "expected parent to be online or closed".
- STRP constructor: "When procedure goes to run in its prepare step, it also does these checkOnline checks. Here we fail-fast on construction.
  There it skips the split with just a warning." The prepare step in fact accepts CLOSED, so the comment and code differ.

Commit: `8a2f3ef793 HBASE-28533 On split procedure rollback revert parent region state back to OPEN (#5863)` introduced `rollbackPrepareSplit`.
HBASE-28533 description, verbatim: "...can leave the parent region's in memory RegionStateNode in SPLITTING after rollback is complete, when the parent
region is still online on the assigned region server and according to meta." It also lists, verbatim: "If region quotas are enabled and a split is run for a
region whose namespace is at its maximum region quota limit we will fail in SPLIT_TABLE_REGION_PRE_OPERATION with QuotaExceededException".
So the fix assumes the parent is online, and developers treat the quota failure as a real production path.

Tests: `TestSplitTableRegionProcedure` has no test of rollback with a CLOSED parent (grep for SPLITTING / rollbackPrepareSplit: nothing). Tests do not assert the behaviour either way.

## Step 3: known status. Every query run

Local history:
- `git log -L '/private void rollbackPrepareSplit/,+6:SplitTableRegionProcedure.java'` -> only 8a2f3ef793
- `git log -i --grep='split.*rollback\|rollback.*split\|rollbackPrepareSplit\|split.*closed' -n 25` -> HBASE-28533, HBASE-26383, HBASE-20893, older pre-AMv2 items
- `git log -S'State.OPEN, State.CLOSED' -- SplitTableRegionProcedure.java` -> HBASE-14614 (2017, the AMv2 original)

Apache JIRA REST:
- `project=HBASE AND text ~ "rollbackPrepareSplit"` -> 0
- `project=HBASE AND text ~ "SplitTableRegionProcedure" AND text ~ "rollback" AND text ~ "CLOSED"` -> 9
- `project=HBASE AND summary ~ "split" AND summary ~ "rollback" ORDER BY updated DESC` -> 13
- `project=HBASE AND text ~ "Unexpected state" AND text ~ "assign" AND text ~ "split"` -> 32
- `project=HBASE AND text ~ "SplitTableRegionProcedure" AND updated >= -180d ORDER BY updated DESC` -> 35
- `project=HBASE AND text ~ "SPLITTING" AND text ~ "rollback" AND text ~ "unassign"` -> 30
- `project=HBASE AND (summary ~ "split" OR summary ~ "assign") AND text ~ "location=null" AND text ~ "OPEN"` -> 27

GitHub REST (`gh` is not installed), `/search/issues`:
- `repo:apache/hbase is:pr rollbackPrepareSplit` -> 0
- `repo:apache/hbase is:pr SplitTableRegionProcedure rollback` -> 8
- `repo:apache/hbase is:pr split rollback parent region state` -> 6
- `repo:apache/hbase is:pr split CLOSED parent rollback OPEN` -> 3
- `repo:apache/hbase is:pr is:merged split merged:>=2026-05-01` -> 41 (first 25 listed)
- `/repos/apache/hbase/commits?path=.../SplitTableRegionProcedure.java` (latest 6), `/pulls/8700`, `/pulls/8700/files`
- raw `master` copy of SplitTableRegionProcedure.java

Closest matches, none the same mechanism at the same site:
- HBASE-28533 (fixed): parent stuck in SPLITTING after rollback. It is the source of this code, but reports the opposite case (parent online).
- HBASE-30143 (open): orphaned FAILED holdLock procedure after split failure at CHECK_CLOSED_REGIONS. Different mechanism.
- HBASE-28560 (open): namespace region count drift on rollback. Different symptom.
- HBASE-30353 / PR 8700 (merged 2026-10-26): split parent reopened after failover. Touches AssignmentManager and RegionStateStore, not this path.
- HBASE-30334 (merged): parent reopen on MERGE rollback. Different procedure and state.
- HBASE-14820, HBASE-5100, HBASE-4729: pre-AMv2 split transaction code.
Upstream `master` still has the identical `EXPECTED_SPLIT_STATES` (505) and `rollbackPrepareSplit` (601-606). Latest commit on the file is HBASE-30160 (2026-07-08), unrelated.

Result: no prior report found. Limit: JIRA full-text and GitHub search are keyword based; a report phrased very differently could be missed. The search set the Novelty field only.

Persistent findings: `specula findings lookup --query SplitTableRegionProcedure --query rollbackPrepareSplit --query TargetSafe` -> `[]`.
