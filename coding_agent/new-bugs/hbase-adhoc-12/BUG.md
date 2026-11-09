# hbase-adhoc-12: Decommission with offload aborts with DoNotRetryIOException, leaving the server half-drained, when it meets an OPEN region of a DISABLING table (a state reachable when a move races with disable).

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/assignment/AssignmentManager.java:772`, `AssignmentManager.preTransitCheck(RegionStateNode, RegionState.State[])`, throws `org.apache.hadoop.hbase.DoNotRetryIOException` when `isTableDisabled(regionNode.getTable())`
- Starting test: `org.apache.hadoop.hbase.regionserver.TestRegionMove#testDisableAndMove`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** Three ordinary admin operations run concurrently: disableTable (held briefly in PRE_OPERATION by a latch), a move of the table's region accepted while the table is still ENABLED, and decommissionRegionServers(offload=true) of the move's destination. The procedure retry back-off is set to 30s, a valid setting.

**Why (root cause in the source):** CloseTableRegionsProcedure skips regions that are in transition and backs off (AssignmentManager.submitUnassignProcedure for disabling tables). Meanwhile the already-accepted move reopens the region, which leaves it OPEN with no procedure while the table is DISABLING. HMaster.decommissionRegionServers (HMaster.java:4165-4174) calls moveAsync on that region with no error handling. preTransitCheck sees isTableDisabled, which includes DISABLING (AssignmentManager.java:563-566), and throws DoNotRetryIOException (AssignmentManager.java:771-772). The decommission RPC fails non-retryably after the server has already been marked draining, and the regions after this one, from any table, are not offloaded. Refusing to move a region of a disabling table is correct, but the drain should skip such a region, which the disable is about to close, rather than abort. The impact matches hbase-adhoc-11: the operator has to rerun the drain.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The disable/move coordination lets a region of a DISABLING table be OPEN with no procedure attached for an arbitrary back-off period. That happens because CloseTableRegionsProcedure skips in-transition regions and sleeps, while a move accepted just before the state flip re-opens the region. Server-side region movers like HMaster.decommissionRegionServers(offload) treat such a region as an ordinary movable region, and preTransitCheck turns that into a fatal DoNotRetryIOException. The decommission request is valid: draining a server does not depend on any table's state, and this region is about to be closed by the disable anyway, so it should be skipped. Instead the operator gets a non-retriable 'table is disabled' error for a decommission. The server is already marked decommissioned in ZooKeeper, but the offload loop aborts at that region, so the remaining regions on the server (of any table) are never moved off. Operators who then stop the 'drained' server cause unplanned region unavailability and WAL-split recovery instead of a graceful drain. The same race affects recommissionRegionServer(server, regions) and the balancer's plan execution, which logs the exception and skips. All the inputs are ordinary concurrent admin operations (disable, move or balancer, decommission) on a production cluster.

**Execution (agent):** Mini cluster with 1 master and 2 region servers (rs1, rs2). Table T has one region R, which is OPEN on rs1. (1) Client A calls disableTable(T). DisableTableProcedure takes the table exclusive lock and runs PREPARE and PRE_OPERATION. A MasterObserver.preDisableTableAction latch holds it there briefly, which only fixes the interleaving. T is still ENABLED. (2) At that moment client B (or the balancer) issues move(R, rs2). HMaster.move -> createMoveRegionProcedure -> preTransitCheck passes because T is ENABLED, and a MOVE TransitRegionStateProcedure is attached to R. The TRSP then waits for the table shared lock. (3) The disable continues. SET_DISABLING_TABLE_STATE writes DISABLING to meta, and MARK_REGIONS_OFFLINE adds a CloseTableRegionsProcedure child, which runs on the parent's lock. It finds R in transition (the MOVE TRSP), schedules no unassign, and suspends for the procedure retry back-off (hbase.procedure.retry.sleep.interval.ms; the test sets it to 30s to make the window deterministic, the default is 1s with exponential growth). The table lock is released while it is suspended. (4) The MOVE TRSP takes the shared lock and moves R: it closes R on rs1 and opens it on rs2. R is now OPEN on rs2 with no procedure attached, while T is DISABLING. It stays that way until the CloseTableRegionsProcedure back-off expires. (5) In this window client C calls decommissionRegionServers([rs2], offload=true). HMaster.decommissionRegionServers marks rs2 as draining in ZooKeeper and the ServerManager. It then calls AssignmentManager.moveAsync for every region on rs2. For R, createMoveRegionProcedure -> preTransitCheck: R has no procedure and is OPEN, but isTableDisabled(T) is true (DISABLING), so it throws DoNotRetryIOException('T is disabled for state=OPEN, location=rs2, ... region=R') at AssignmentManager.java:772. The exception propagates out of the offload loop and the decommission RPC fails.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.assignment.AssignmentManager.preTransitCheck(AssignmentManager.java:772)

## Reproduction

- Test: `org.apache.hadoop.hbase.regionserver.TestRegionMoveDecommissionDuringDisable#testDecommissionDuringDisableAndMove`
- Command: `mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.regionserver.TestRegionMoveDecommissionDuringDisable#testDecommissionDuringDisableAndMove' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMoveDecommissionDuringDisable.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `Caused by: org.apache.hadoop.hbase.DoNotRetryIOException: org.apache.hadoop.hbase.DoNotRetryIOException: testDecommissionDuringDisable is disabled for state=OPEN, location=agent-host,40661,1794072027642, table=testDecommissionDuringDisable, region=ded34c5fe24b8e8b28de20e753347de6`, frame `at org.apache.hadoop.hbase.master.assignment.AssignmentManager.preTransitCheck(AssignmentManager.java:772)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h10m | 1 | 1,755,300 | 54 | 40,652 | 102,489 | 1,612,105 | $1.96 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
