# HBASE-27 exploratory full campaign, v3

This package runs the existing `TestClusterBootOrder#testBootRegionServerFirst`
MiniCluster JUnit with the exact `HRegionServer.blockAndCheckIfStopped` target
at lines 1052–1053. It uses a fresh healthy JUnit in each new campaign and
admits named, typed I/O doors before a named target check. It does not claim
that every admitted door has an observed causal path to the check. The
offline causal audit reports that quality separately.

The previous healthy run passed JUnit 1/0/0, reached the exact target twice
on `rs0` (events 4 and 7), and observed four pretarget typed
`ZKNodeTracker.start@75` ConnectionLoss doors: `rs0` at 1/2 and `master0`
at 5/6. The `rs0` fault is source-predicted to erase later `rs0` checks:
`ZKNodeTracker.start` catches KeeperException and calls its `abortable`,
which is the same RegionServer; `abort` calls `stop`, and `run` immediately
returns if stopped. By contrast, `master0` faults abort the master while
the independent `rs0` thread can still wait on its null tracker data and
check `this.stopped` again. A JUnit teardown race may still erase the check,
so target retention is measured per fault trial, never assumed.

`preflight.py --node1` requires the exact 2.6.6 source, target class,
instrumentation and site catalog hashes, plus the prior healthy result,
event gzip, JUnit pass, named actor, and typed `master0` doors at 5/6 before
the `rs0` check at 7. `run_full_node1.sh` requires the dispatch grant
`MALLORY_HBASE27_NODE1_GRANT=full-v3`, an idle node1 HBase lane, and disk and
memory headroom. It creates only the distinct
`data/mallory/cases/HBASE-27/campaigns/boot-order-tracker-v3-full` output.

The budget is **80 fault trials, 3600 seconds, up to 3 faults per trial**.
A natural `budget_exhausted` or `queue_exhausted` terminal with at least one
fault trial is a completed campaign. A targeted IOException alone is the
source's shutdown response and is not classified as a new bug without
separate source and replay evidence. The earlier monitor healthy audit in
`../identity-v2-offline-proof/` explains why graph-path quality is zero for
the `nodeCreated` doors in that seed. No JUnit or fault trial was launched
while staging this package.
