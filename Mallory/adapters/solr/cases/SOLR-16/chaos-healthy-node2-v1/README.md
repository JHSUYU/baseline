# SOLR-16 isolated healthy split observation

This package selects the unchanged Solr 8.11.4 cluster JUnit
`org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey`.
The test starts a ZooKeeper-backed multi-node cluster, initiates a parent shard
split, stops its leader during the split, restarts it, and checks the resulting
documents and shard state. It explicitly permits the split request to fail.

The exact SOLR-16 check is `SplitShardCmd.split@539:branch:41`, and the selected
throw is `@543:throw:1`. The first `/live_nodes/<parent leader>` stat read is
at line 164; the second is at line 523. The line-539 branch requires the second
stat to be non-null and its ephemeral owner to differ from the first owner.
`SplitShardTest#doTest` performs a normal successful split, so it cannot reach
this abort-only branch in a fault-free run. The chaos JUnit gives a relevant
cluster operation, but a target throw during its planned leader stop is an
expected protective abort, not evidence of a new bug.

`sites.json` pins the retry-internal `SolrZkClient.lambda$exists$2@301:door:1`
typed `KeeperException.ConnectionLossException` point as well as the exact
target. `audit_healthy.py` requires one passing original JUnit, loaded target
class and catalog, a complete fault-free trace, and both line-164 and line-523
caller doors on the same actor, epoch, split occurrence, thread and context.
The next same-thread event after each caller door must be its native `exists`
attempt, and those two attempts must read the same exact
`/live_nodes/<node>` resource. A different split or znode cannot satisfy this
gate. A passing healthy receipt is observation evidence only; this package has
no full or fault mode.

This package now pins the isolated resource-aware agent release
`b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4`.
For the exact Solr 8.11.4 `SolrZkClient.lambda$exists$2` and
`lambda$getData$6` calls, it reads the first String argument and attaches that
path to the existing I/O event. The bytecode matcher requires the exact method
and callee descriptors. An isolated transformed-class test verifies both
methods still return their original values. SOLR-15's earlier chaos healthy
trace used the old agent and showed same-split caller doors but no resource
path. It cannot be reused as SOLR-16 evidence.

The new agent adds path observation; it does not add a path-aware fault-plan
selector. A future fault campaign must bind the second lookup's path to the
same parent leader in each new split execution before injecting a fault.

`python3 run_campaign.py --mode healthy --preflight-only` checks the staged
package, source, bytecode, and release without starting a JVM. A case-local
dispatch GO receipt and the node2 Solr locks are required for execution.
No JUnit, fault campaign, or checklist update is part of this stage.
