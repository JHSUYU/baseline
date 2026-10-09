# SOLR-09 independent CoreAdmin HTTP follow-up

This is a separate graph-free fault campaign for the original Solr 8.11.4
`DeleteReplicaTest.deleteReplicaAndVerifyDirectoryCleanup` four-node embedded-cluster
JUnit. It does not change the original test, the running ZooKeeper-only campaign,
or that campaign's checkpoint. The source checkout is Solr revision
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`.

The first phase only injects ZooKeeper API failures. It cannot directly fail
the CoreAdmin `UNLOAD` HTTP request; that response enters the selected
`DeleteReplicaCmd.deleteCore` callable and determines whether its fallback
state deletion runs. This stage adds that separately observed I/O family while
keeping the same original JUnit and exact target check.

The selected check remains `DeleteReplicaCmd.deleteCore`'s
`if (!callable.call())` guard. A false result marks the exact target exception;
an unrelated JUnit error does not. A trial is valid only if every requested
fault is uniquely matched and applied in order, and this guard executes after
the final fault. The trial ledger retains the original event trace, JaCoCo
execution file, JUnit log, injected selector, and elapsed time.

The independent probe records the actual CoreAdmin request before
`ShardRequestor.call` invokes HTTP I/O. Its selector includes `HTTP_POST`, the
exact `qt/action/core` resource, production caller, and hit ordinal. The trace
also records the concrete node and URL. An injected `IOException` is caught by
the original `ShardRequestor.call` and reaches the original response/fallback
logic. The six SolrZkClient read/write hooks are retained for later mutations
after the HTTP root fault; they inject `KeeperException.ConnectionLossException`.
Relative later selectors record the preceding applied fault ID, relative count,
and observed global hit ordinal. Stable callsite/operation/resource identity,
not hit ordinal growth, determines new I/O feedback.

Healthy calibration passed on the unchanged JUnit (12.853 seconds) and on the
case-local instrumented JUnit (15.974 seconds). The instrumented run recorded
one normal target guard and one earlier `HTTP_POST` to
`/admin/cores?action=UNLOAD&core=deletereplica_test_shard1_replica_n1` from
`ShardRequestor#call:130`. Two additional healthy instrumented runs passed;
one observed the same core identity and one observed the `replica_n2` identity.
Both exact identities seed the separate HTTP campaign. These runs are in
`evidence/healthy-*`; `evidence/healthy-summary.json` records the first pair.

The stage budget is 80 valid trials and at most eight ordered faults, with at
most 240 attempts. It extends to 128 valid trials and ten faults, at most 384
attempts, only if the last eight valid trials add production coverage or a
stable I/O identity. Source-reviewed candidates require an exact target guard
throw and a clean replay. Stage results live in this directory's `result.json`
until the two SOLR-09 phases are reviewed together. The root SOLR-09 result
then reports each phase and the combined attempts, valid trials, post-fault
target executions, and elapsed time. Production coverage gains remain separate
because the two phases have distinct healthy baselines and instrumented classes.
An independent replay is recorded separately and never added to fuzz trial counts.
