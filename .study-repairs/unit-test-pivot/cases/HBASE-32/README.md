# HBASE-32 source-only preparation

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

**Runtime verification is still pending.** Healthy execution may enter
`triggerFlushInPrimaryRegion` without taking the selected B7 exception arm.
The healthy run must distinguish method entry, catch entry, and the exact
non-disabled/non-`TableNotFoundException` guard outcome before any fault
campaign is credited. The original JUnit alone does not establish B7 reach.
No fault trial or bug result is claimed here.
