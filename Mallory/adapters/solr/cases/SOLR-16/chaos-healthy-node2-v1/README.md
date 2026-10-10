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
Native `exists` attempts must read the same exact `/live_nodes/<node>` resource
on both sides of the handoff. A different split or znode cannot satisfy this
gate. A passing healthy receipt is observation evidence only; this package has
no full or fault mode.

The currently pinned agent does not record the ZooKeeper resource path on
`DOOR_OBSERVED`, so the path gate will fail closed until a separately built and
verified resource-aware agent is available. SOLR-15's prior chaos healthy trace
showed line-164 and line-523 caller doors in the same split occurrence, but its
native doors lacked the resource path. That trace cannot be reused as SOLR-16
evidence. The `chaos-target-discovery-v1/resource-path-v1` proposal under
SOLR-15 describes the required instrumentation; it is not an active release.

`python3 run_campaign.py --mode healthy --preflight-only` checks the staged
package, source, bytecode, and release without starting a JVM. A case-local
dispatch GO receipt and the node2 Solr locks are required for execution.
No JUnit, fault campaign, or checklist update is part of this stage.
