# SOLR-16: existing cluster JUnit source review

**Disposition:** target-unreached skip candidate for the unchanged Solr 8.11.4
cluster tests. This is a source-review limit, not evidence that the check is
unreachable in Solr or that an exception would be a new bug. No JVM or fault
campaign was run for this review.

The pinned source revision is
`e27f44e3d78dfcec230c97e0a1240e3751daeff9`. In
`SplitShardCmd.split`, line 164 reads and retains the parent leader's
`/live_nodes/<nodeName>` znode `ephemeralOwner`; line 523 reads that **same
path** again. The selected line-539 condition is evaluated only after line 524
finds a missing node or changed owner and line 536 rules out a missing node.
Consequently, the parent leader must leave and re-register the same live-node
path with a different ZooKeeper session between those two reads. A different
node becoming leader, a missing second znode, or a restart after the split
request completes does not reach the selected check.

I searched all Solr test-source files with a `splitShard`, `SPLITSHARD`, or
`trySplit` reference and reviewed their split/lifecycle ordering. The 23
matching Java test/support files comprise 21 under `solr/core/src/test`, one
SolrJ request-parameter test, and one test-framework backup helper. Relevant
cluster tests are:

| Existing test | Lifecycle relative to split | Why it does not deliberately reach line 539 |
| --- | --- | --- |
| `ShardSplitTest#testSplitWithChaosMonkey` (`solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java:416`) | Stops the original parent leader after two sub-shard replicas appear (lines 454–460); starts it only after `requestStatus(...).waitFor(...)` and the monkey thread have finished (lines 480–506). | The second `exists` can see the original session or no znode, but the test does not re-register that node during the split. The observed healthy run covered both reads on the same path, passed JUnit 1/0/0, and missed the exact line-539 check; see `receipt.json`. |
| `ShardSplitTest#testSplitStaticIndexReplication` and `#testSplitStaticIndexReplicationLink` (lines 125–208) | Wait for async split completion and active child shards before stopping and starting the former parent/child host. | Restart occurs after the split, despite the method comment about restarting a sub-shard leader. |
| `ChaosMonkeyShardSplitTest#test` (`solr/core/src/test/org/apache/solr/cloud/ChaosMonkeyShardSplitTest.java:52–145`) | Stops the old leader, waits for a different leader, restarts the old host, and then calls split. Its concurrent `OverseerRestarter` closes an overseer client, not the new parent leader's live-node registration. | No restart of the selected parent leader within the two-read interval. This entire class is also `@Ignore("SOLR-4944")`. |
| `CollectionsAPISolrJTest#testSplitShard`, `SplitShardTest#testSplitFuzz`/`#testLiveSplit`, `MultiThreadedOCPTest` split cases, `SplitByPrefixTest`, `CollectionsAPIAsyncDistributedZkTest`, and `TestCoordinatorRole#testSplitShard` | Invoke split and check ordinary results or task state. | No parent-leader session replacement during their split calls. |
| `ScheduledMaintenanceTriggerTest` split case (line 262) | Completes split before maintenance waits; its `addNode()` helper is called in a separate test (line 368). | No relevant live-node re-registration in the split test. |
| Autoscaling simulator/policy/trigger tests and request/status/API tests | Simulate, plan, validate, or issue split requests. | None contains the required same-parent stop/re-register transition in the read window; some do not execute `SplitShardCmd` at all. |

The source search does not exclude incidental ZooKeeper session expiry from an
uncontrolled environment. It finds **no existing, unchanged cluster JUnit
that intentionally produces the required same-path owner transition during
the split**. Under the current rule to use existing cluster tests without
writing a new workload, this case should remain a target-unreached skip
candidate. It must not be marked as a completed high-quality fuzz case.
