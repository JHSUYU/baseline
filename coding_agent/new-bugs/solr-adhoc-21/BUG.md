# solr-adhoc-21: CoreContainer.reload racing with DELETEREPLICA's UNLOAD re-registers the deleted core and then fails on the missing replica (assert/NPE), leaving a closed stale core registered on the node.

Severity (reviewer): **minor**

## The ad hoc check (the prompt's only target)

- `solr/core/src/java/org/apache/solr/core/CoreContainer.java:1765`, `CoreContainer.reload(String, UUID)`, throws `java.lang.AssertionError` when `assert replica != null;   (fails when replica == null; replica = docCollection.getReplica(cd.getCloudDescriptor().getCoreNodeName()), inside if (docCollection != null); a Java assert, active only with -ea)`
- Starting test: `org.apache.solr.cloud.api.collections.CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss`

## Verified defect (independent reviewer, `../../data/REVIEW-RUBRIC.md`)

**Verdict:** BUG

**Trigger:** A core-admin RELOAD of a non-leader replica's core is slowed down during new-core construction (a SearchComponent whose inform() waits on a latch, standing in for slow plugin init); meanwhile a client DELETEREPLICA unloads that core and removes the replica from state.json, and then the reload resumes.

**Why (root cause in the source):** The triggers (a delay in plugin initialisation and two concurrent ordinary admin operations) are realistic. CoreContainer.unload (CoreContainer.java:1837-1887) neither waits for nor respects the pending-op marker held by reload, so the old core is removed and the replica deleted while reload is still building its replacement. When reload resumes it calls registerCore(cd, newCore) unconditionally (CoreContainer.java:1742), putting a core for a now-deleted replica back into SolrCores. It then finds the replica missing from the collection state and hits `assert replica != null` (CoreContainer.java:1765); without -ea, replica.getType() throws an NPE. The finally block closes newCore (1784-1786) but leaves it registered, so the node holds a closed or zombie core for a deleted replica until restart, and the RELOAD fails with a 500. Nothing coordinates reload against unload, so this state comes from missing coordination, not from a bad request.

## The agent's explanation (its `result.json`)

**Why it is a bug (agent):** Two ordinary admin operations on the same replica can overlap: a core RELOAD (from an operator, a tool, or the config/schema change listeners that call cc.reload(name, coreId)) and a DELETEREPLICA (from an operator, autoscaling, or MOVEREPLICA). Nothing orders them: CoreContainer.unload ignores the pending-op marker that reload holds, and the Overseer's collection lock does not cover core-admin RELOADs or listener-triggered reloads. CoreContainer.reload assumes the replica it is reloading is still in the cluster state it read after core.reload(), but a concurrent delete can remove it in between. The state the check rejects comes from the system's own unsynchronised coordination, not from a bad user request. Consequences: with -ea the RELOAD fails with an AssertionError (HTTP 500). Without -ea, replica.getType() throws a NullPointerException, which is caught and recorded in coreInitFailures, and the new core is closed even though registerCore has already put it into SolrCores. Either way the node is left with a core registered for a replica that no longer exists in ZK and whose instance/data dirs DELETEREPLICA asked to delete. At shutdown that leftover core is closed again ('Too many closes on SolrCore').

**Execution (agent):** Cluster: 2 Solr nodes plus ZK, configset = cloud-minimal plus a test SearchComponent (SlowInitComponent) whose inform() stands in for slow plugin initialisation by waiting on a latch, only while the core is being reloaded. Collection c8n_1x2 has 1 shard and 2 NRT replicas, one per node. Steps: (1) A client sends a core-admin RELOAD for the non-leader core c8n_1x2_shard1_replica_n1 straight to its node. CoreContainer.reload(name, null) gets the old core, re-reads the CoreDescriptor (coreNodeName = core_node3), marks the core as having a pending op, and calls SolrCore.reload(), which builds the new SolrCore. That construction is held in SlowInitComponent.inform(). (2) While it is held, a client runs DELETEREPLICA for core_node3. The Overseer sends a core-admin UNLOAD to the same node. CoreContainer.unload() does not wait for the pending reload (only reload/create use waitAddPendingCoreOps). It removes and closes the old core and unregisters it. The Overseer removes core_node3 from state.json, and the node's ZkStateReader picks up the new state. DELETEREPLICA returns success. (3) The reload resumes: the new core finishes construction, CoreContainer.reload reads getZkController().getClusterState().getCollection("c8n_1x2") (not null, because replica core_node6 is still there) and calls registerCore(cd, newCore), which puts the deleted core back into the container. docCollection.getReplica("core_node3") then returns null, so `assert replica != null` throws java.lang.AssertionError at CoreContainer.java:1765. The RELOAD request returns HTTP 500 with that trace. Later, at shutdown, 'Too many closes on SolrCore' is logged for the core that was put back.

**Stack frame (agent):** at org.apache.solr.core.CoreContainer.reload(CoreContainer.java:1765)

## Reproduction

- Test: `org.apache.solr.cloud.api.collections.CollectionReloadDeleteReplicaRaceTest#testCoreReloadRacingWithDeleteReplica`
- Command: `source ../env.sh && cd solr/core && ant -lib $IVY_USER_DIR/lib test -Dtestcase=CollectionReloadDeleteReplicaRaceTest -Dtests.method=testCoreReloadRacingWithDeleteReplica -Dtests.jvms=1 -Dtests.useSecurityManager=false -Divy_install_path=$IVY_USER_DIR/lib`
- Test files (in `repro/`, paths relative to the system's tree): `solr/core/src/test/org/apache/solr/cloud/api/collections/CollectionReloadDeleteReplicaRaceTest.java`
- Validation on an unmodified tree with only these files: **REPRODUCED** (1/1 tries hit the check); exception `[junit4]   2> Caused by: java.lang.AssertionError`, frame `[junit4]   2> 	at org.apache.solr.core.CoreContainer.reload(CoreContainer.java:1765) ~[java/:?]`
- Production changes by the agent: none

## Time and tokens

| agent time | sessions | tokens (all) | input | output | cache writes | cache reads | cost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0h05m | 1 | 739,428 | 38 | 19,669 | 51,123 | 668,598 | $0.94 |

Agent time excludes usage-limit waits; tokens include subagents; cost is the CLI's list-price estimate.
