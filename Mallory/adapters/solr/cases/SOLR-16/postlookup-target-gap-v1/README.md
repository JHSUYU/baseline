# SOLR-16: exact check remains absent after path-qualified leader reads

The node0 healthy `ShardSplitTest#testSplitWithChaosMonkey` run passed its
unchanged cluster JUnit (1/0/0). The trace binds both native `exists` attempts
to `/live_nodes/127.0.0.1:43151_` on actor `control`, epoch 0, thread 266,
within one `SplitShardCmd.split` occurrence (events 1414 and 1919). The exact
`@539:branch:41` check did not execute. The complete evidence and source hashes
are in `receipt.json`; `python3 -B audit_offline.py` regenerates that receipt
without a JVM.

`SplitShardCmd` records the first znode's ephemeral owner at line 164. After
building sub-shard metadata, it reads the same znode at line 523. Line 524
enters the abort block only if the second stat is null or its owner differs.
The selected line-539 check is inside that block, after the null case. The
trial covered the outer line-524 branch and continued into replica creation;
the later split failed at line 593 because the planned leader stop prevented
replica creation. The stat values themselves were not recorded, so owner
equality is a control-flow inference, not a directly observed data value.

The chaos JUnit waits for two sub-shard replicas and then sleeps for 1000–1499
ms before stopping the parent leader. It restarts that node only after waiting
for the asynchronous split result (test lines 480 and 506). If the second read
occurs during the downtime, the null-stat branch throws at line 538, before
the selected check. Reaching line 539 requires the **same physical node's**
live znode to reappear under a different ZooKeeper session between the two
reads. Changing the test's random seed does not change its restart order.
Related split JUnits reviewed in the pinned Solr 8.11.4 source exercise normal
split, replica-creation failure, or split locking; none deliberately replaces
this parent's session in the read window. An incidental session replacement is
possible, but the existing healthy evidence does not show one. The case is a
**target-unreached skip candidate**; no fault run or completed-check mark
follows from it.
