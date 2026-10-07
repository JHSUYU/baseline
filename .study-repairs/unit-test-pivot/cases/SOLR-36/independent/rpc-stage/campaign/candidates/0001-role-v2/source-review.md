# SOLR-36 role-V2 HTTP candidate 0001

Original system: Solr 8.11.4 release JAR, original embedded-cluster `ShardSplitTest#test` (`@Test`, `@Nightly`). Classification: **`expected_target_rejection`, `new_bug=false`**. The original JUnit completed with `ran=1 ignored=0 failures=0` in 103.526 seconds.

## Exact event sequence

| Trace sequence | Event | Identity and state |
| --- | --- | --- |
| 3941 | `IO_OBSERVED`, strict selected Add delay | `DISTRIB_FROM_PARENT=shard1`; actual request core `collection1_shard1_replica_n1`; parent raw replica `core_node3` equals the unique active leader in the local non-lazy collection state. Exact child `collection1/shard1_0/core_node11`, URL `http://127.0.0.1:40619/collection1_shard1_0_replica_n9/`. |
| 3983 | `FAULT_EFFECT` | The planned 5,000 ms delay ended; the original HTTP call followed. |
| 3985 | exact SOLR-36 guard | Same child `core_node11`, `state=active;phase=FROMLEADER`. |
| 3986 | exact SOLR-36 throw | `SolrException`: `Request says it is coming from parent shard leader but we are in active state`. |

The sender and child are distinct logical cores on the **same Jetty endpoint** (`127.0.0.1:40619_`). The evidence supports a delayed HTTP request across the local collection-state transition; it does not show a cross-machine message loss. The selected plan and full trace, console, JaCoCo, JUnit metadata, and SHA-256 inventory are in this directory. The new effect-time recount leaves strict=1, post-effect SOLR-36 guard=1, exact throw=1; SOLR-37 has no post-effect guard in this trial.

## Original source and test behavior

In `DistributedZkUpdateProcessor.getSubShardLeaders` (source lines 868–891), the parent selects a child leader only while the child slice is `CONSTRUCTION` or `RECOVERY`. The parent then sets `DISTRIB_FROM_PARENT` and sends the Add through `SolrCmdDistributor.submit`. At the child, `doDefensiveChecks` (lines 977–995) deliberately throws `SERVICE_UNAVAILABLE` when a `FROMLEADER` request with `DISTRIB_FROM_PARENT` arrives after the child slice becomes `ACTIVE`. The observed `state=active` and exact message match that protective branch.

The console shows the child 503 at line 20140, the parent `DistributedUpdatesAsyncException` around line 20334, and `BaseCloudSolrClient` retrying the operation after the 503 at line 20380 (`retry=0 maxRetries=5`). The retried Add for document 197 succeeds on the child leader at line 20402. The original test then reaches `checkDocCountsAndShardStates` (source lines 969–1028), which checks both child slices active, replica counts, subshard consistency, and document counts; the JUnit passes and runs its later route-field and route-key phases.

This is a timing-sensitive **protective rejection followed by client recovery**. The fault changed when the parent forwarded an Add, while the child rejected a request that arrived after its slice became `ACTIVE`. The original test's recovery and document/state assertions passed. A same-plan replay is lower priority because this already fits the source's intended protective path; the frozen raw trace remains available. The HTTP campaign resumed from the one completed plan after an audited effect-time recount. Future exact throws outside this reviewed guard/message/JUnit outcome still pause for separate source review and replay.
