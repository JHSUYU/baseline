# SOLR-07 trial 38: exact selected throw under review

The unchanged `AddReplicaTest.testAddMultipleReplicas` runs a three-Jetty
embedded SolrCloud cluster. Trial 38 of the actor-bound campaign applied two
ordered `ConnectionLossException` faults to the same `SolrZkClient` on
`JETTY/node1`: an `exists` watch at `LazyCollectionRef.get:811` (ordinal 13),
then `getData` at `ZkStateReader.fetchCollectionState:1641` (ordinal 4), both
on `/collections/testAddMultipleReplicas/state.json`. Raw `IO_APPLIED` events
423 and 434 have client identity `759820166`. After both faults, selected
`ZkController.register:1325` event 530 reached the exact NRT core
`shard1/core_node2/testAddMultipleReplicas_shard1_replica_n1` on the same
client and physical Jetty. Event 531 records its `SolrCore is no longer
available to register` exception. The independent audit of the complete
39-trial prefix reports 25 exact plans, six postfault same-actor targets, one
exact selected throw, and zero raw/checkpoint discrepancies.
The [raw trial archive](evidence/trial038-raw.tar.gz) contains the exact plan,
events, JUnit log, JaCoCo output, and trial/run receipts; its SHA-256 is
`23eac87c9308cb1e9ef81276dcc6abe6c54a602f9a63d77a1e7bac501ddb377d`.

The original JUnit failed with an HTTP response timeout from another Jetty.
The log records the test ending at elapsed 98,268 ms, the target Jetty's
`CoreContainer` beginning shutdown at 98,379 ms, and its selected core
closing at 98,398 ms. The same request thread then logs an error at
98,516 ms. At `ZkController.register:1323-1326`, `cc.getCore(desc.getName())`
throws the selected exception when the local core is absent. These timings
make test teardown a likely explanation for this throw; the trace alone does
not show a live, serviceable core disappearing before teardown. This is an
exact target-exception *candidate*, not a confirmed new bug.

Five fresh-fixture same-plan replays completed with passing original JUnits.
Their applied fault counts were `0, 0, 1, 0, 0`; none applied both requested
faults, so they supply **no evidence either way** about exact reproduction of
the target throw. The [independent replay audit](trial038-replays-audit.json)
re-read every raw trace and found no receipt or actor-identity discrepancies.
The [replay raw archive](evidence/trial038-replays-raw.tar.gz) has SHA-256
`154acc2f7945a9149edfde8af62a5c37341996059209c796ca1b49388270134c`.
The live fuzz checkpoint was paused at 39 selected attempts during replay, so
these diagnostic JUnits do not consume the campaign budget.

## Trial 48: same selected guard during shutdown

V4 trial 48 applied the same first two faults and a third `getData` fault at
`ZkStateReader.fetchCollectionState:1641` (ordinal 5), all on the same
`JETTY/node1` client identity `274237255`. Raw `IO_APPLIED` events 424, 435,
and 517 precede the exact `ZkController.register:1326` throw at event 526;
the independent 53-trial checkpoint audit reports zero errors. The original
JUnit failed after an HTTP response timeout. Its log places the test's end
at 98,579 ms, `CoreContainer.shutdown` at 98,695 ms, the selected core's
`CLOSING` event at 98,710 ms, and the request-thread error at 98,826 ms.
The third injected fault is on the shutdown path
`CoreContainer.shutdown -> ZkController.preClose -> publishNodeAsDown`.
Thus this is another exact target-exception candidate in the same teardown
family, not evidence of a live-core coordination failure or a confirmed new
bug. Trial 48 has not yet had an exact same-plan replay. The
[six-file raw archive](evidence/trial048-raw.tar.gz) has SHA-256
`8cd8623e9241bb79fe6c71a5b31c1bed6ff9ea6c76ab05e6b414513d96a588a9`.

## Trial 64: fourth fault, same teardown family

V4 trial 64 added a fourth same-client `EXISTS_WATCH` fault (ordinal 20) to
trial 48's three-fault prefix. Raw `IO_APPLIED` events 423, 434, 517, and
521 precede the exact selected throw at event 525. The unchanged JUnit ended
at 97,719 ms; the target Jetty began `CoreContainer.shutdown` at 97,833 ms,
the selected core logged `CLOSING` at 97,849 ms, and its request thread
continued later. The original JUnit failed after a roughly 90-second create
collection timeout. The target throw is again after test teardown began, so
it remains in the same candidate family and is not a confirmed new bug. The
[raw six-file archive](evidence/trial064-raw.tar.gz) has SHA-256
`ca80a8f12172e3f1b8ac24acc6cd5a301f365c580c38a61e67df59abde17d54b`.
