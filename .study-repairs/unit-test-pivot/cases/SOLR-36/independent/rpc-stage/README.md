# SOLR-36/37 parent-to-child HTTP stage

This is a separate fault stage for the unchanged Solr 8.11.4 embedded-cluster `ShardSplitTest#test`. The first stage injected only native ZooKeeper I/O exceptions. This stage observes the HTTP add and delete-by-id requests on the direct target path:

In the two original healthy target traces, all SOLR-36 guard events belong to `collection1/shard1_0` or `collection1/shard1_1` (56/36 and 60/40). This is why the HTTP selector is restricted to the original test's `collection1/shard1` parent and these child shards.

`DistributedZkUpdateProcessor.doDistribAdd` or `doDistribDeleteById` → `getSubShardLeaders` → `cmdDistrib.distribAdd` or `distribDelete` with `synchronous=true` → `SolrCmdDistributor.submit` → `Http2SolrClient.request` → child `doDefensiveChecks`.

The case-local ASM probe sits immediately before the original `Http2SolrClient.request` invocation in `SolrCmdDistributor.submit`. It records the logical collection, child shard and replica as its exact selector and records the physical core URL separately. It filters for the original `distrib.from.parent=shard1` add or delete-by-id request, with distinct command markers and resource families. Trial 58's exact target throw came from `processAdd`; trial 78's came from `doDeleteById`. A matched `TIMEOUT` throws `SocketTimeoutException` inside the original `submit` exception handler; a matched `DELAY` waits 5, 15, or 30 seconds before the original HTTP call. `StdNode` created by `getSubShardLeaders` has `maxRetries=0`, so the timeout is recorded by the distributor and the original client/test recovery path determines the outcome. No test method or cluster operation is changed.

Two fresh healthy JUnit runs must each pass and observe both exact target guards plus both parent-forward HTTP command families. Each family must have exact selectors in the intersection of the two runs. The campaign uses its own `campaign/state.json` checkpoint and JaCoCo feedback; every selected trial records plan, trace, JUnit result, elapsed time, exact injection, same-logical-child target guard after injection, and exact target throw. The ZooKeeper and HTTP stage counts remain separate in both checklist rows.

The selected trial is written to the checkpoint before its JVM starts. On restart, the runner keeps that exact selector and reuses an attempt only if its complete `run.json` exists; finished trials are never selected again. The runner hash, agent JAR, and healthy trace digests are pinned in the checkpoint.

The HTTP agent uses the same internal class names as stage one, but a Java 8 `-verbose:class` preflight with the original classpath confirmed that both `research.solrsubshard.Agent` and `Probe` load from the HTTP stage's own agent JAR. Its SHA-256 is recorded in `agent-build.json`. The stage is therefore not accidentally using the earlier ZooKeeper-only probe.
