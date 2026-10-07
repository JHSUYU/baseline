# HBASE-32: primary-flush exception check

Selected HBase 2.6.6 site:
`RegionReplicaFlushHandler.triggerFlushInPrimaryRegion(HRegion)`, B7,
`RegionReplicaFlushHandler.java:136`. A secondary region handler asks the
primary to flush through `FlushRegionCallable`, which calls the primary's
`flushRegion` RPC. If the retried call throws `IOException`, this site returns
for `TableNotFoundException` or a disabled table; otherwise it rethrows the
exception. `RegionReplicaFlushHandler.handleException` then aborts the region
server for ordinary `IOException`.

The mapped unchanged original JUnit is
`TestRegionReplicaFailover.testSecondaryRegionKill`. Its `@BeforeEach` starts a
three-region-server MiniHBaseCluster and creates a table with three replicas.
The test loads rows, aborts the server hosting replica 1, waits for secondary
reads after reassignment, verifies replica 2, and starts a replacement server.
This sequence can invoke the secondary's primary-flush request during reopen.

## Runtime identity and target evidence

The unchanged original test runs a three-region-server MiniHBaseCluster on
node1. The healthy JUnit passed (`1/1`) in 55.35 seconds. Its trace contains
three `triggerFlushInPrimaryRegion` invocations and three observed
`FlushRegionCallable.call:81` RPC sends; JaCoCo measured zero instructions on
source line 136. Different cluster runs allocate different numeric region IDs.
The agent therefore selects an I/O point by stable table/start key, replica
ID, target invocation ordinal, and RPC ordinal. Every trace also records the
full raw primary and secondary region names. A planned fault is applied only
when the live RPC's raw primary name equals the active target invocation's raw
primary name.

The first calibrated exact fault on replica 1's second target invocation
injected a `DoNotRetryIOException` immediately before the real `flushRegion`
RPC. The same raw primary region appeared in `FAULT_APPLIED` and the
subsequent line-136 `TARGET_B7_RETHROW`. The test passed (`1/1`) after HBase
aborted and reassigned the affected region server; JaCoCo's merged production
coverage grew by seven branches, and source line 136 gained two executed
instructions. Source `handleException` explicitly aborts the server for this
ordinary exception, so this outcome is an expected control path, not a new
bug. A separate `TableNotFoundException` calibration reached the line-130
guard for the same raw region without reaching B7, then the JUnit failed with
`OperationTimeoutExceededException` after 180.23 seconds. It fabricated a
table-missing response while the table still existed; this violates the
response's state precondition, so the calibration is excluded from the main
fault queue and is not a bug claim.

The resumable coverage-guided campaign is implemented in `work/campaign.py`.
It uses the original JUnit, case-local ASM probes, JaCoCo production coverage,
exact ordered fault plans, and atomic per-trial checkpoints. It searches up to
80 effective target-guard trials, 240 attempts, and eight injected faults per
plan. Every fault trial is tied to the same concrete region as the post-fault
guard; unmatched plans do not count. The campaign remains active on node1 in
tmux session `hbase32-fuzz`, and `result.json` reflects the last synchronized
checkpoint. Raw trial logs and JaCoCo exec files remain under node1's isolated
`work/logs/` until archived.

The second campaign plan injected two no-retry exceptions during successive
recoveries. The original JUnit had already aborted RS
`ms1105.utah.cloudlab.us,37551,1791336903029`; the two target B7 outcomes
caused `handleException` to abort the other two distinct RSs
(`...,33921,1791336902566` and `...,34251,1791336903366`). The master then
reported no region server available. This sequence exhausts all three RSs and
is invalid under the workload's recovery precondition. It is preserved for
independent replay, excluded from the effective denominator and bug candidates,
and not expanded in the queue. Its fault and target-hit counts remain visible.
