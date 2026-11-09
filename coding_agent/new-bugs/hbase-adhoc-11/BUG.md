# hbase-adhoc-11: Decommission with offload aborts with a non-retryable error, leaving the server draining with regions still on it, if one of its regions is in the SPLITTING window (no procedure attached yet).

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `hbase-server/src/main/java/org/apache/hadoop/hbase/master/assignment/AssignmentManager.java:769`, `AssignmentManager.preTransitCheck(RegionStateNode, RegionState.State[])`, throws `org.apache.hadoop.hbase.client.DoNotRetryRegionException` when `!regionNode.isInState(expectedStates)`
- Starting test: `org.apache.hadoop.hbase.regionserver.TestRegionMove#testDisableAndMove`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A split of region P on RS1 is in progress, held between PREPARE and CLOSE_PARENT by a latch in preSplitRegionAction, when an operator calls decommissionRegionServers([RS1], offload=true).

**Why (root cause in the source):** SplitTableRegionProcedure.prepareSplitRegion sets P to SPLITTING (SplitTableRegionProcedure.java:590) without attaching a procedure to the RegionStateNode. getRegionsOnServer still lists P. HMaster.decommissionRegionServers (HMaster.java:4165-4174) calls moveAsync for every region with no error handling, and preTransitCheck throws the NON-retryable DoNotRetryRegionException (AssignmentManager.java:768-769) instead of the retryable 'in transition' error. The offload loop aborts after RS1 has already been put on the draining list, so the remaining regions on RS1 are never moved. Because the error is DoNotRetry, the client does not retry. Rejecting a move of a splitting region is reasonable, but a routine auto-split makes a valid drain fail half-done. The operator has to notice and rerun it after the split finishes; the system does not recover by itself.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** The split and the assignment manager coordinate ownership of a region through the RegionStateNode: a region that is being transitioned is supposed to carry its owning procedure, so other operations see 'in transition' and back off or retry. SplitTableRegionProcedure (and MergeTableRegionsProcedure, which sets MERGING the same way) breaks this: it moves the parent to SPLITTING/MERGING without registering a procedure on the node. preTransitCheck therefore treats a normal, transient in-progress split as a permanent 'unexpected state' and throws a DoNotRetry exception, when it should have reported a retryable in-transition condition. In a real deployment, auto-splits run all the time, so any concurrent move hits this: decommission/offload (graceful_stop, draining), rsgroup server moves, the balancer, the system-region mover, or a plain Admin.move. For decommissionRegionServers(offload=true) the effect is worse than a failed call: the offload loop aborts after RS1 is already marked draining, so its remaining regions stay on the server that is about to be taken down. The client gets a non-retryable error, so the operator's tooling gives up instead of retrying, and stopping the server then makes those regions unavailable and forces crash recovery.

**Execution (agent):** Mini cluster with 1 master and 2 region servers (RS1, RS2). A table with 5 regions is created and some rows are written and flushed. A region P hosted on RS1 is split (Admin.splitRegionAsync; in production the RS itself can also request this when P grows past its size limit). The master runs SplitTableRegionProcedure: SPLIT_TABLE_REGION_PREPARE (prepareSplitRegion) sets P's RegionStateNode state to SPLITTING in memory but attaches no procedure to the node. It then enters SPLIT_TABLE_REGION_PRE_OPERATION, where a test MasterObserver.preSplitRegionAction latch holds it. That latch stands in for any delay there: coprocessor work, a slow PE worker, and so on. Only the later CLOSE_PARENT_REGION step attaches the unassign TRSP to the node. While the split is in this window, an operator calls Admin.decommissionRegionServers([RS1], offload=true). HMaster.decommissionRegionServers puts RS1 on the draining list and goes through getRegionsOnServer(RS1), which still includes P because a SPLITTING region stays in the server's region list. For each region it calls AssignmentManager.moveAsync -> createMoveRegionProcedure -> preTransitCheck. For P, regionNode.getProcedure() is null, so the retryable 'currently in transition' HBaseIOException branch is skipped. P's state is SPLITTING, not OPEN, so DoNotRetryRegionException('Unexpected state for state=SPLITTING ...') is thrown at AssignmentManager.java:769. The exception aborts the offload loop, so regions after P on RS1 are never moved, and it reaches the client as DoNotRetry, so the client does not retry. The split then finishes normally once released.

**Stack frame (agent):** at org.apache.hadoop.hbase.master.assignment.AssignmentManager.preTransitCheck(AssignmentManager.java:769)

## Reproduction

- Test: `org.apache.hadoop.hbase.regionserver.TestRegionMoveDuringSplit#testDecommissionWhileSplitting`
- Command: `source /bulk/codingagent/cases/hbase-adhoc-11/agent/env.sh && mvn -B -o test -PrunAllTests -pl hbase-server -Dtest='org.apache.hadoop.hbase.regionserver.TestRegionMoveDuringSplit#testDecommissionWhileSplitting' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false`
- Test files (in `repro/`, paths relative to the system's tree): `hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMoveDuringSplit.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `org.apache.hadoop.hbase.client.DoNotRetryRegionException: Unexpected state for state=SPLITTING, location=agent-host,34937,1794071217715, table=testDecommissionWhileSplitting, region=9938775dfe8eeeeb50c28c0e70c96f97`, frame `at org.apache.hadoop.hbase.master.assignment.AssignmentManager.preTransitCheck(AssignmentManager.java:769)`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h04m | 1 | 722,797 | 32 | 15,549 | 58,443 | 648,773 | $0.91 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
