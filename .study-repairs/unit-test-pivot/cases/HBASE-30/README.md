# HBASE-30: replay batch status check

The selected check is in the unchanged HBase 2.6.6
`RSRpcServices.replay` at source commit
`d5f63f523c065f963992ea4e74db268d17816631`. The actual predicate
is at line 2297, immediately after `doReplayBatchOp` returns. The checklist
anchor at line 2298 is the `IOException` thrown if any returned
`OperationStatus` is not the shared `OperationStatus.SUCCESS` object.
The local `ReplayBatchOperation` can return statuses such as
`BAD_FAMILY`, `SANITY_CHECK_FAILURE`, or `STORE_TOO_BUSY` when a replayed
mutation is rejected. Such a status causes the selected exception by design;
its occurrence alone would not establish a new coordination bug. The replay
decoder constructs only Put/Delete mutations from WAL cells, so the
separately allocated success statuses for Increment/Append in the shared
batch implementation do not explain this test's normal path.

The unchanged original embedded-cluster JUnit
`TestRegionReplicaReplicationEndpoint#testRegionReplicaReplicationWith2Replicas`
starts two RegionServers, creates a primary and secondary replica, writes
1000 rows, and waits for the secondary to receive them. This case has an
independent runner and evidence directory; HBASE-29's trials do not count
here even though it uses the same upstream test.

The case-local ByteBuddy agent observes each server-side replay RPC, resolves
the real table and replica through the receiver's region lookup, and matches
only `testRegionReplicaReplicationWithReplicas_2` replica 1. It can inject
`IOException`, `EOFException`, or `FileNotFoundException` at an observed RPC
identity (`table`, `replica`, production method, hit ordinal). A separate
probe on `doReplayBatchOp` records the actual `OperationStatus[]` immediately
before the selected comparison, including each status's identity relative to
`OperationStatus.SUCCESS`. A `BATCH_RETURN` with positive status count is
admitted as a target execution only when it belongs to that replica. JaCoCo
also checks that the source line and production branches execute.

The graph-free campaign seeds from I/O actually observed in this case's own
healthy run, mutates ordered fault sequences, and admits feedback only after
all planned faults match exactly and the selected check runs after the last
fault. The default budget is 80 effective trials and at most eight ordered
faults; late new production method/branch coverage or stable I/O family
extends to 128 and ten. Each trial's plan, matches, target outcomes, JUnit
result, coverage and elapsed time is atomically checkpointed. A non-success
status and the resulting target `IOException` are candidates requiring source
and replay review, not automatically new bugs. The implementation uses no
GraphChecker runtime, graph, closure, prewoven class, skeleton or static map.

The runner and probes compile independently. Its own healthy calibration and
campaign are pending while HBASE-24 and HBASE-29 use the local cluster-test
resources.
